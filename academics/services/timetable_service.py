# academics/services/timetable_service.py
from django.db import transaction

from school.services.scheduler_engine import (
    GeneticTimetableSolver,
    LessonRequirement,
    RoomOption,
)
from academics.models import (
    ClassSubjectRequirement,
    Room,
    TimeSlot,
    Timetable,
    TimetableEntry,
)


class TimetableGenerationError(Exception):
    """Raised when there isn't enough configured data to generate a timetable."""


class AITimetableService:
    """
    Turns a school's ClassSubjectRequirement / Room / TimeSlot / Teacher data
    into lesson requirements, runs the genetic algorithm, and persists the
    winning chromosome as Timetable + TimetableEntry rows.

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
        requirements = ClassSubjectRequirement.objects.filter(
            school=school, school_class__isnull=False
        ).select_related('school_class', 'subject').prefetch_related('subject__qualified_teachers')

        lesson_requirements = []
        for req in requirements:
            teacher_ids = tuple(
                str(t.id) for t in req.subject.qualified_teachers.filter(school=school, is_active=True)
            )
            for session_index in range(req.periods_per_week):
                lesson_requirements.append(
                    LessonRequirement(
                        cohort_id=str(req.school_class_id),
                        subject_id=str(req.subject_id),
                        session_index=session_index,
                        student_count=req.school_class.student_count,
                        is_lab_required=req.subject.requires_lab,
                        eligible_teacher_ids=teacher_ids,
                    )
                )
        return lesson_requirements

    @staticmethod
    def _build_room_options(school):
        return [
            RoomOption(room_id=str(r.id), capacity=r.capacity, is_lab=r.is_lab)
            for r in Room.objects.filter(school=school)
        ]

    @staticmethod
    def _build_timeslots(school):
        slots = list(TimeSlot.objects.filter(school=school))
        return slots, [s.slot_id for s in slots]

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
        population_size=80,
        generations=300,
        mutation_rate=0.15,
        random_seed=None,
    ) -> Timetable:
        school = timetable.school
        academic_term = timetable.academic_term

        timetable.status = 'RUNNING'
        timetable.save(update_fields=['status'])

        try:
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

            solver = GeneticTimetableSolver(
                requirements=lesson_requirements,
                rooms=rooms,
                timeslot_ids=timeslot_ids,
                population_size=population_size,
                generations=generations,
                mutation_rate=mutation_rate,
                random_seed=random_seed,
            )
            best_chromosome = solver.run()

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
                )
            )

        # Clear out any stale entries (re-run on the same pending row) before
        # writing the winning chromosome.
        TimetableEntry.objects.filter(timetable=timetable).delete()
        TimetableEntry.objects.bulk_create(entries, ignore_conflicts=True)

        timetable.fitness_score = chromosome.fitness
        timetable.hard_conflicts = chromosome.hard_conflicts
        timetable.soft_conflicts = chromosome.soft_conflicts
        timetable.generations_run = generations_run
        if skipped:
            timetable.error_message = (
                f"{skipped} lesson(s) could not be placed - likely a subject with no "
                f"qualified teacher assigned. Check Teacher subject qualifications."
            )
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