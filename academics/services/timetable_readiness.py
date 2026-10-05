from collections import defaultdict

from staff.models import Teacher

from academics.models import (
    ClassSubject,
    ClassSubjectRequirement,
    Room,
    TeacherAssignment,
    TimeSlot,
)
from academics.services.timetable_configuration import (
    get_or_create_configuration,
    get_timeslot_configuration_status,
)
from academics.timetable_schedule_block_model import TimetableScheduleBlock


def _resolve_teacher_group(school_class, group):
    if group:
        return group
    if (
        school_class.uses_single_class_teacher
        and school_class.homeroom_teacher_id
        and getattr(school_class.homeroom_teacher, "is_active", False)
        and getattr(school_class.homeroom_teacher.user, "is_active", False)
    ):
        return [school_class.homeroom_teacher]
    return []


class TimetableReadiness:
    """Non-destructive preflight checks for AI timetable generation."""

    def __init__(self, school, academic_term=None):
        self.school = school
        self.academic_term = academic_term

    def _effective_periods(self, school_class_id, subject_id, assignment=None, overrides=None):
        overrides = overrides or {}
        key = (school_class_id, subject_id)
        if key in overrides:
            return overrides[key], "advanced override"

        class_subject = (
            ClassSubject.objects
            .filter(
                school=self.school,
                school_class_id=school_class_id,
                subject_id=subject_id,
                is_active=True,
            )
            .first()
        )
        if class_subject:
            return class_subject.periods_per_week, "class subject"

        return (assignment.periods_per_week if assignment else 0), "teacher assignment"

    def run(self):
        issues = []
        warnings = []

        classes = list(
            self.school.classes.filter(is_active=True)
            .select_related("homeroom_teacher__user", "grade_level")
            .order_by("name")
        )
        slots = list(
            TimeSlot.objects.filter(school=self.school, is_active=True)
        )
        rooms = list(
            Room.objects.filter(school=self.school, is_active=True)
        )
        assignments = list(
            TeacherAssignment.objects.filter(
                school=self.school,
                is_active=True,
                school_class__is_active=True,
                subject__is_active=True,
                teacher__is_active=True,
                teacher__user__is_active=True,
            ).select_related("school_class", "subject", "teacher__user")
        )
        class_subjects = list(
            ClassSubject.objects.filter(
                school=self.school,
                is_active=True,
                school_class__is_active=True,
                subject__is_active=True,
            ).select_related("school_class", "subject")
        )
        overrides = {
            (r.school_class_id, r.subject_id): r.periods_per_week
            for r in ClassSubjectRequirement.objects.filter(school=self.school)
        }

        if not self.academic_term:
            issues.append("No active academic term is configured.")
        if not classes:
            issues.append("No active classes are configured.")
        if not slots:
            issues.append("No active timetable periods are configured.")
        if not rooms:
            issues.append("No active rooms are configured.")

        assignments_by_key = defaultdict(list)
        for assignment in assignments:
            assignments_by_key[(assignment.school_class_id, assignment.subject_id)].append(assignment)

        duplicate_assignment_details = []
        for key, group in assignments_by_key.items():
            if len(group) <= 1:
                continue
            primary = next((a for a in group if a.is_primary), group[0])
            duplicate = {
                "class_name": primary.school_class.name,
                "subject_name": primary.subject.name,
                "teachers": [a.teacher.user.get_full_name() or str(a.teacher) for a in group],
                "count": len(group),
            }
            duplicate_assignment_details.append(duplicate)
            issues.append(
                f"{primary.school_class.name} — {primary.subject.name}: {len(group)} active teacher assignments found. Keep one primary active assignment before generating."
            )

        # ClassSubject is the normal academic definition of what a class studies.
        # TeacherAssignment supplies the teacher. This catches missing teachers
        # before the genetic algorithm starts.
        requirements = []
        for class_subject in class_subjects:
            key = (class_subject.school_class_id, class_subject.subject_id)
            group = _resolve_teacher_group(class_subject.school_class, assignments_by_key.get(key, []))
            if not group:
                issues.append(
                    f"{class_subject.school_class.name} — {class_subject.subject.name}: no active teacher assigned."
                )
                continue

            primary = next((a for a in group if getattr(a, "is_primary", False)), group[0])
            periods, _ = self._effective_periods(
                class_subject.school_class_id,
                class_subject.subject_id,
                assignment=primary if isinstance(primary, TeacherAssignment) else None,
                overrides=overrides,
            )
            if periods <= 0:
                issues.append(
                    f"{class_subject.school_class.name} — {class_subject.subject.name}: periods per week must be at least 1."
                )
                continue
            requirements.append((class_subject, primary, periods))

        # Keep backwards compatibility for schools that have teacher assignments
        # but have not yet created ClassSubject rows.
        class_subject_keys = {(cs.school_class_id, cs.subject_id) for cs in class_subjects}
        for key, group in assignments_by_key.items():
            if key in class_subject_keys:
                continue
            primary = next((a for a in group if a.is_primary), group[0])
            periods, _ = self._effective_periods(*key, assignment=primary, overrides=overrides)
            if periods > 0:
                requirements.append((None, primary, periods))

        weekly_slots = len(slots)
        class_subject_counts = defaultdict(int)
        for class_subject in class_subjects:
            class_subject_counts[class_subject.school_class_id] += 1

        # Every active class must have at least one active subject definition.
        # Otherwise the generator would silently omit that class from the
        # timetable, which is much harder to diagnose after generation.
        for school_class in classes:
            if class_subject_counts.get(school_class.id, 0) == 0:
                assignment_subject_count = sum(
                    1 for key in assignments_by_key
                    if key[0] == school_class.id
                )
                if assignment_subject_count == 0:
                    issues.append(
                        f"{school_class.name}: no active subjects are configured for this class."
                    )
                else:
                    warnings.append(
                        f"{school_class.name}: no active ClassSubject records exist; the generator will rely on legacy teacher assignments."
                    )

        required_by_class = defaultdict(int)
        for class_subject, assignment, periods in requirements:
            school_class = class_subject.school_class if class_subject is not None else assignment.school_class
            subject = class_subject.subject if class_subject is not None else assignment.subject
            required_by_class[school_class.id] += periods
            suitable_rooms = [
                room for room in rooms
                if room.capacity >= school_class.student_count
                and (not subject.requires_lab or room.is_lab)
            ]
            if not suitable_rooms:
                if subject.requires_lab:
                    issues.append(
                        f"{school_class.name} — {subject.name}: no active lab room has enough capacity for {school_class.student_count} students."
                    )
                else:
                    issues.append(
                        f"{school_class.name} — {subject.name}: no active room has enough capacity for {school_class.student_count} students."
                    )

        for school_class in classes:
            required = required_by_class.get(school_class.id, 0)
            if required > weekly_slots:
                issues.append(
                    f"{school_class.name}: requires {required} periods per week but only {weekly_slots} active periods are available."
                )

        # Detailed capacity/coverage data is returned for the readiness UI.
        # It uses the same effective teacher and period resolution as the hard checks
        # above, so the dashboard cannot show a different picture from generation.
        class_details = []
        for school_class in classes:
            required = required_by_class.get(school_class.id, 0)
            class_items = [
                (cs, teacher, periods)
                for cs, teacher, periods in requirements
                if cs is not None and cs.school_class_id == school_class.id
            ]
            missing_count = 0
            for cs in class_subjects:
                if cs.school_class_id != school_class.id:
                    continue
                key = (cs.school_class_id, cs.subject_id)
                if not _resolve_teacher_group(cs.school_class, assignments_by_key.get(key, [])):
                    missing_count += 1
            class_details.append({
                "name": school_class.name,
                "subject_count": class_subject_counts.get(school_class.id, 0),
                "no_subjects": class_subject_counts.get(school_class.id, 0) == 0,
                "required": required,
                "available": weekly_slots,
                "difference": weekly_slots - required,
                "overage": max(required - weekly_slots, 0),
                "missing": missing_count,
                "status": "ready" if required <= weekly_slots and missing_count == 0 else "action",
            })

        # Build teacher workload first because the teacher-capacity cards and the
        # detailed allocation audit both depend on this exact effective requirement set.
        teacher_periods = defaultdict(int)
        teacher_objects = {}
        for _, assignment, periods in requirements:
            if isinstance(assignment, TeacherAssignment):
                teacher_id = assignment.teacher_id
                teacher = assignment.teacher
            else:
                teacher_id = assignment.id
                teacher = assignment
            if not teacher_id or not teacher:
                continue
            teacher_periods[teacher_id] += periods
            teacher_objects[teacher_id] = teacher

        # Build a transparent allocation audit from the same effective requirements
        # used above. Each class/subject contributes once: the primary explicit
        # subject teacher wins, otherwise the effective class-teacher fallback is used.
        teacher_audit = defaultdict(list)
        for class_subject, assignment, periods in requirements:
            school_class = class_subject.school_class if class_subject is not None else assignment.school_class
            subject = class_subject.subject if class_subject is not None else assignment.subject
            if isinstance(assignment, TeacherAssignment):
                teacher_id = assignment.teacher_id
                teacher = assignment.teacher
                source = "Subject Teacher"
            else:
                teacher_id = assignment.id
                teacher = assignment
                source = "Class Teacher fallback"
            if not teacher_id or not teacher:
                continue
            teacher_audit[teacher_id].append({
                "class_name": school_class.name,
                "subject_name": subject.name,
                "periods": periods,
                "source": source,
            })

        # Include active teachers with zero current assignments as available capacity.
        teacher_qs = Teacher.objects.filter(
            school=self.school, is_active=True, user__is_active=True
        ).select_related("user").order_by("user__last_name", "user__first_name")
        teacher_details = []
        for teacher in teacher_qs:
            total = teacher_periods.get(teacher.id, 0)
            reference = getattr(teacher, "max_periods_per_week", 25) or 25
            teacher_details.append({
                "id": teacher.id,
                "name": teacher.user.get_full_name() or str(teacher),
                "assigned": total,
                "capacity": weekly_slots,
                "remaining": weekly_slots - total,
                "overage": max(total - weekly_slots, 0),
                "reference": reference,
                "reference_over": total > reference,
                "hard_over": bool(weekly_slots and total > weekly_slots),
                "audit": sorted(teacher_audit.get(teacher.id, []), key=lambda x: (x["class_name"].lower(), x["subject_name"].lower())),
            })

        class_details.sort(key=lambda x: x["name"].lower())
        teacher_details.sort(key=lambda x: (-x["assigned"], x["name"].lower()))
        missing_teacher_count = sum(item["missing"] for item in class_details)
        teacher_capacity_over = sum(1 for item in teacher_details if item["hard_over"])

        # A lab subject cannot be generated in a normal room. Flag the condition
        # explicitly instead of allowing the solver to search an impossible space.
        lab_subjects = {
            class_subject.subject_id if class_subject is not None else assignment.subject_id
            for class_subject, assignment, _ in requirements
            if (class_subject.subject.requires_lab if class_subject is not None else assignment.subject.requires_lab)
        }
        if lab_subjects and not any(room.is_lab for room in rooms):
            warnings.append("At least one subject requires a laboratory, but no active lab room is configured.")

        # Teacher capacity has two levels:
        # 1) the teacher's configurable workload reference is a warning;
        # 2) the actual number of teaching periods in the configured school week
        #    is a hard physical capacity and must block generation when exceeded.
        for teacher_id, total in teacher_periods.items():
            teacher = teacher_objects.get(teacher_id)
            if not teacher:
                continue
            name = teacher.user.get_full_name() or str(teacher)
            if weekly_slots and total > weekly_slots:
                issues.append(
                    f"{name}: assigned {total} teaching periods/week but only {weekly_slots} timetable periods/week are available."
                )
            reference = getattr(teacher, "max_periods_per_week", 25) or 25
            if total > reference:
                warnings.append(
                    f"{name}: approximately {total} assigned periods/week exceeds the {reference}-period workload reference."
                )

        # The saved configuration is a user-facing blueprint while TimeSlot is
        # the actual scheduler input. A mismatch should not silently block a
        # school that intentionally manages TimeSlots manually, but it must be
        # visible before generation.
        configuration_status = None
        try:
            config = get_or_create_configuration(self.school)
            configuration_status = get_timeslot_configuration_status(self.school, config)
            if not configuration_status["matches"]:
                warnings.append(
                    "The saved timetable configuration differs from the active TimeSlots. "
                    "Generation will use the active TimeSlots; review Schedule Configuration if this is unexpected."
                )

            active_blocks = list(
                TimetableScheduleBlock.objects.filter(
                    configuration=config, is_active=True
                )
            )
            invalid_blocks = [
                block for block in active_blocks
                if block.after_period >= max(1, config.periods_per_day)
                or block.minutes <= 0
                or block.day not in (None, '', *list(config.days or []))
            ]
            if invalid_blocks:
                issues.append(
                    f"{len(invalid_blocks)} active timetable schedule block(s) are invalid for the current configuration."
                )
        except Exception as exc:
            # Readiness itself must remain safe even if an older installation
            # has incomplete configuration data. The scheduler still uses the
            # actual TimeSlots below.
            warnings.append(f"Timetable configuration could not be fully inspected: {exc}")

        return {
            "ready": not issues,
            "issues": issues,
            "warnings": warnings,
            "stats": {
                "classes": len(classes),
                "class_subjects": len(class_subjects),
                "assignments": len(assignments),
                "rooms": len(rooms),
                "timeslots": len(slots),
                "required_periods": sum(periods for _, _, periods in requirements),
                "active_teachers": len(teacher_details),
                "teacher_capacity": len(teacher_details) * weekly_slots,
                "teacher_assigned_periods": sum(item["assigned"] for item in teacher_details),
                "missing_teachers": missing_teacher_count,
                "teacher_capacity_over": teacher_capacity_over,
                "duplicate_assignments": len(duplicate_assignment_details),
                "classes_without_subjects": sum(1 for item in class_details if item["no_subjects"]),
                "issue_count": len(issues),
                "warning_count": len(warnings),
            },
            "configuration": configuration_status,
            "class_details": class_details,
            "teacher_details": teacher_details,
            "duplicate_assignments": duplicate_assignment_details,
        }
