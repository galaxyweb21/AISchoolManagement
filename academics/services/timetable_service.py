# academics/services/timetable_service.py
from collections import defaultdict

from django.db import transaction

from school.services.scheduler_engine import (
    GeneticTimetableSolver,
    LessonRequirement,
    RoomOption,
)
from academics.models import (
    ClassSubject,
    ClassSubjectRequirement,
    Room,
    TeacherAssignment,
    TimeSlot,
    Timetable,
    TimetableEntry,
    TeacherWorkload,
)


class TimetableGenerationError(Exception):
    """Raised when there isn't enough configured data to generate a timetable."""


class AITimetableService:
    """
    Turns a school's TeacherAssignment / ClassSubjectRequirement / Room /
    TimeSlot data into lesson requirements, runs the genetic algorithm, and
    persists the winning chromosome as Timetable + TimetableEntry rows.

    Split into create_pending() + run() so the actual GA work can be handed
    off to a Celery task instead of blocking the HTTP request - a real
    school's timetable can take anywhere from a couple of seconds to well
    over a minute depending on how tightly constrained it is.
    """

    # ------------------------------------------------------------------
    # Data gathering
    # ------------------------------------------------------------------
    @staticmethod
    def _build_requirements(school, academic_term):
        """Build a practical weekly lesson set for the simple timetabler.

        The older implementation treated every configured ``periods_per_week``
        value as mandatory.  That made demo data such as 11 subjects x 4
        periods impossible inside a 40-period week.

        This replacement keeps the existing subject/teacher assignments, but
        treats the configured periods as *requested weighting* and creates a
        balanced weekly teaching budget.  A normal class receives up to 32
        instructional lessons per week, while a class with fewer requested
        lessons keeps its full allocation.  KG classes in the demo naturally
        remain at their configured 28 lessons.

        This does not modify ClassSubject or TeacherAssignment records.  It
        only determines how many occurrences the timetable generator places.
        """
        from academics.services.timetable_readiness import _resolve_teacher_group

        WEEKLY_LESSON_BUDGET = 32

        classes = list(
            school.classes.filter(is_active=True)
            .select_related('homeroom_teacher__user', 'grade_level')
        )
        assignments = list(
            TeacherAssignment.objects.filter(
                school=school,
                is_active=True,
                school_class__is_active=True,
                subject__is_active=True,
                teacher__is_active=True,
                teacher__user__is_active=True,
            ).select_related('school_class', 'subject', 'teacher')
        )
        assignments_by_key = defaultdict(list)
        for assignment in assignments:
            assignments_by_key[(assignment.school_class_id, assignment.subject_id)].append(assignment)

        class_subjects = list(
            ClassSubject.objects.filter(
                school=school,
                school_class__is_active=True,
                subject__is_active=True,
                is_active=True,
            ).select_related('school_class', 'subject')
        )
        class_subject_keys = {(cs.school_class_id, cs.subject_id) for cs in class_subjects}

        overrides = {
            (req.school_class_id, req.subject_id): int(req.periods_per_week)
            for req in ClassSubjectRequirement.objects.filter(school=school)
        }

        # Gather one effective record per class/subject first.
        records_by_class = defaultdict(list)
        for class_subject in class_subjects:
            key = (class_subject.school_class_id, class_subject.subject_id)
            group = _resolve_teacher_group(
                class_subject.school_class,
                assignments_by_key.get(key, []),
            )
            if not group:
                raise TimetableGenerationError(
                    f"{class_subject.school_class.name} — {class_subject.subject.name}: "
                    "no active teacher is assigned."
                )

            primary = next(
                (item for item in group if isinstance(item, TeacherAssignment) and item.is_primary),
                group[0],
            )
            fallback_periods = (
                primary.periods_per_week
                if isinstance(primary, TeacherAssignment)
                else class_subject.periods_per_week
            )
            requested = int(overrides.get(
                key,
                class_subject.periods_per_week or fallback_periods,
            ) or 0)
            if requested <= 0:
                continue

            teacher_ids = tuple(
                str(item.teacher_id if isinstance(item, TeacherAssignment) else item.id)
                for item in group
            )
            records_by_class[class_subject.school_class_id].append({
                'class_subject': class_subject,
                'requested': requested,
                'teacher_ids': teacher_ids,
            })

        # Include legacy TeacherAssignment-only records.
        for key, group in assignments_by_key.items():
            if key in class_subject_keys or not group:
                continue
            primary = next((a for a in group if a.is_primary), group[0])
            requested = int(overrides.get(key, primary.periods_per_week) or 0)
            if requested <= 0:
                continue
            records_by_class[primary.school_class_id].append({
                'class_subject': None,
                'school_class': primary.school_class,
                'subject': primary.subject,
                'requested': requested,
                'teacher_ids': tuple(str(a.teacher_id) for a in group),
                'is_lab': bool(primary.subject.requires_lab),
            })

        def allocate_periods(records):
            """Scale requested periods down fairly to the class lesson budget."""
            total_requested = sum(r['requested'] for r in records)
            if total_requested <= WEEKLY_LESSON_BUDGET:
                for r in records:
                    r['allocated'] = r['requested']
                return

            # Every active subject gets at least two lessons when possible.
            # Remaining lessons are distributed by requested weight and core
            # status, making the result predictable rather than random.
            count = len(records)
            target = WEEKLY_LESSON_BUDGET
            minimum = 2 if target >= count * 2 else 1
            allocated = {id(r): minimum for r in records}
            remaining = target - (count * minimum)

            ranked = sorted(
                records,
                key=lambda r: (
                    bool(getattr(r.get('class_subject'), 'is_core', False)),
                    r['requested'],
                    getattr(r.get('class_subject'), 'subject_id', None) or str(getattr(r.get('subject'), 'id', '')),
                ),
                reverse=True,
            )
            while remaining > 0:
                changed = False
                for r in ranked:
                    if remaining <= 0:
                        break
                    if allocated[id(r)] < r['requested']:
                        allocated[id(r)] += 1
                        remaining -= 1
                        changed = True
                if not changed:
                    break

            for r in records:
                r['allocated'] = allocated[id(r)]

        for school_class in classes:
            records = records_by_class.get(school_class.id, [])
            if not records:
                continue
            allocate_periods(records)

        lesson_requirements = []
        for school_class in classes:
            records = records_by_class.get(school_class.id, [])
            for record in records:
                class_subject = record.get('class_subject')
                subject = class_subject.subject if class_subject is not None else record['subject']
                student_count = class_subject.school_class.student_count if class_subject is not None else school_class.student_count
                cohort_id = class_subject.school_class_id if class_subject is not None else school_class.id
                for session_index in range(int(record['allocated'])):
                    lesson_requirements.append(
                        LessonRequirement(
                            cohort_id=str(cohort_id),
                            subject_id=str(subject.id),
                            session_index=session_index,
                            student_count=student_count,
                            is_lab_required=bool(subject.requires_lab),
                            eligible_teacher_ids=record['teacher_ids'],
                        )
                    )

        return lesson_requirements

    @staticmethod
    def _build_room_options(school):
        return [
            RoomOption(room_id=str(r.id), capacity=r.capacity, is_lab=r.is_lab)
            for r in Room.objects.filter(school=school, is_active=True)
        ]

    @staticmethod
    def _build_timeslots(school):
        slots = list(TimeSlot.objects.filter(school=school, is_active=True))
        return slots, [s.slot_id for s in slots]

    @staticmethod
    def _build_teacher_max_periods(school, academic_term, requirements):
        """Return each eligible teacher's weekly workload reference."""
        teacher_ids = {
            str(teacher_id)
            for req in requirements
            for teacher_id in req.eligible_teacher_ids
            if teacher_id
        }
        capacities = {teacher_id: 25 for teacher_id in teacher_ids}
        if not teacher_ids:
            return capacities

        rows = TeacherWorkload.objects.filter(
            school=school,
            academic_term=academic_term,
            teacher_id__in=teacher_ids,
        ).only('teacher_id', 'max_periods')
        for row in rows:
            capacities[str(row.teacher_id)] = int(row.max_periods or 25)
        return capacities

    # ------------------------------------------------------------------
    # Phase 1: called synchronously from the view - just books a row so the
    # UI has something to show and poll immediately.
    # ------------------------------------------------------------------
    @staticmethod
    def create_pending(school, academic_term, generated_by=None) -> Timetable:
        return Timetable.objects.create(
            school=school,
            academic_term=academic_term,
            generated_by=generated_by,
            status='PENDING',
        )

    # ------------------------------------------------------------------
    # Phase 2: the actual GA run. Safe to call from a Celery task or
    # synchronously (e.g. management commands, tests) - it doesn't care.
    # ------------------------------------------------------------------
    @classmethod
    def run(
        cls,
        timetable: Timetable,
        population_size=40,
        generations=120,
        mutation_rate=0.10,
        random_seed=None,
    ) -> Timetable:
        school = timetable.school
        academic_term = timetable.academic_term

        timetable.status = 'RUNNING'
        timetable.save(update_fields=['status'])

        try:
            # The Simple Smart Timetabler deliberately does NOT block on the
            # old readiness total. Readiness reports configured demand, while
            # this generator converts that demand into a practical weekly lesson
            # budget. Missing teachers/rooms are still treated as real errors.
            lesson_requirements = cls._build_requirements(school, academic_term)
            if not lesson_requirements:
                raise TimetableGenerationError(
                    "No subject requirements configured. Add classes, subjects and "
                    "periods-per-week before generating a timetable."
                )

            rooms = cls._build_room_options(school)
            if not rooms:
                raise TimetableGenerationError("No rooms configured for this school yet.")

            timeslot_objs, timeslot_ids = cls._build_timeslots(school)
            if not timeslot_ids:
                raise TimetableGenerationError("No timeslots configured for this school yet.")

            teacher_max_periods = cls._build_teacher_max_periods(
                school, academic_term, lesson_requirements
            )

            solver = GeneticTimetableSolver(
                requirements=lesson_requirements,
                rooms=rooms,
                timeslot_ids=timeslot_ids,
                population_size=population_size,
                generations=min(int(generations or 40), 40),
                mutation_rate=mutation_rate,
                random_seed=random_seed,
                teacher_max_periods=teacher_max_periods,
            )
            best_chromosome = solver.run()

            if best_chromosome.hard_conflicts > 0:
                raise TimetableGenerationError(
                    f'Fast timetable construction could not produce a conflict-free timetable. '
                    f'{best_chromosome.hard_conflicts} hard conflict(s) remain after '
                    f'{solver.generations_run} improvement pass(es). No invalid timetable was saved.'
                )

            if len(best_chromosome.genes) != len(lesson_requirements):
                raise TimetableGenerationError(
                    f'The generator placed {len(best_chromosome.genes)} of '
                    f'{len(lesson_requirements)} required lessons. No partial timetable was saved.'
                )

            cls._persist(
                timetable=timetable,
                chromosome=best_chromosome,
                generations_run=solver.generations_run,
                timeslot_objs=timeslot_objs,
            )
            timetable.status = 'COMPLETE'
            timetable.save(update_fields=['status'])

        except TimetableGenerationError as exc:
            timetable.status = 'FAILED'
            timetable.error_message = str(exc)[:500]
            timetable.save(update_fields=['status', 'error_message'])
        except Exception as exc:
            timetable.status = 'FAILED'
            timetable.error_message = f"Unexpected error: {exc}"[:500]
            timetable.save(update_fields=['status', 'error_message'])

        return timetable

    @staticmethod
    @transaction.atomic
    def _persist(timetable, chromosome, generations_run, timeslot_objs):
        from staff.models import Teacher
        from academics.models import SchoolClass, Subject

        school = timetable.school
        timeslot_by_id = {slot.slot_id: slot for slot in timeslot_objs}

        classes = {str(c.id): c for c in SchoolClass.objects.filter(school=school)}
        subjects = {str(s.id): s for s in Subject.objects.filter(school=school)}
        teachers = {str(t.id): t for t in Teacher.objects.filter(school=school)}
        rooms = {str(r.id): r for r in Room.objects.filter(school=school)}

        entries = []
        skipped = 0
        for gene in chromosome.genes:
            teacher = teachers.get(gene.teacher_id)
            timeslot = timeslot_by_id.get(gene.timeslot_id)
            school_class = classes.get(gene.cohort_id)
            subject = subjects.get(gene.subject_id)
            room = rooms.get(gene.room_id)

            # A gene can be left unresolved if a subject has zero qualified
            # teachers - skip rather than write a broken entry.
            if not all([teacher, timeslot, school_class, subject, room]):
                skipped += 1
                continue

            entries.append(
                TimetableEntry(
                    timetable=timetable,
                    school_class=school_class,
                    subject=subject,
                    teacher=teacher,
                    room=room,
                    timeslot=timeslot,
                    is_lab=gene.is_lab_required,
                )
            )

        # Clear out any stale entries (re-run on the same pending row) before
        # writing the winning chromosome.
        TimetableEntry._base_manager.filter(timetable=timetable).delete()
        TimetableEntry._base_manager.bulk_create(entries, ignore_conflicts=False)

        timetable.fitness_score = chromosome.fitness
        timetable.hard_conflicts = chromosome.hard_conflicts
        timetable.soft_conflicts = chromosome.soft_conflicts
        timetable.generations_run = generations_run
        if skipped:
            raise TimetableGenerationError(
                f"{skipped} generated lesson(s) could not be resolved to database records."
            )

        saved_count = TimetableEntry._base_manager.filter(timetable=timetable).count()
        if saved_count != len(entries):
            raise TimetableGenerationError(
                f"The generator prepared {len(entries)} entries but only {saved_count} were saved."
            )

        timetable.error_message = ''
        timetable.save(update_fields=['fitness_score', 'hard_conflicts', 'soft_conflicts',
                                       'generations_run', 'error_message'])

    @staticmethod
    @transaction.atomic
    def publish(timetable: Timetable):
        Timetable.objects.filter(school=timetable.school, academic_term=timetable.academic_term).update(
            is_published=False
        )
        timetable.is_published = True
        timetable.save(update_fields=['is_published'])
        return timetable