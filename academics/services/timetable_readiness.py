from collections import defaultdict

from academics.models import (
    ClassSubject,
    ClassSubjectRequirement,
    Room,
    TeacherAssignment,
    TimeSlot,
)


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
            self.school.classes.filter(is_active=True).order_by("name")
        )
        subjects = list(
            self.school.subjects.filter(is_active=True).order_by("name")
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

        if not assignments and class_subjects:
            issues.append("No active subject-teacher assignments are configured for the listed class subjects.")
        elif not assignments and not class_subjects:
            issues.append("No active subject-teacher assignments are configured.")

        assignments_by_key = defaultdict(list)
        for assignment in assignments:
            assignments_by_key[(assignment.school_class_id, assignment.subject_id)].append(assignment)

        # ClassSubject is the normal academic definition of what a class studies.
        # TeacherAssignment supplies the teacher. This catches missing teachers
        # before the genetic algorithm starts.
        requirements = []
        for class_subject in class_subjects:
            key = (class_subject.school_class_id, class_subject.subject_id)
            group = assignments_by_key.get(key, [])
            if not group:
                issues.append(
                    f"{class_subject.school_class.name} — {class_subject.subject.name}: no active teacher assigned."
                )
                continue

            primary = next((a for a in group if a.is_primary), group[0])
            periods, _ = self._effective_periods(
                class_subject.school_class_id,
                class_subject.subject_id,
                assignment=primary,
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
        required_by_class = defaultdict(int)
        for class_subject, assignment, periods in requirements:
            required_by_class[assignment.school_class_id] += periods

            subject = assignment.subject
            school_class = assignment.school_class
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

        # A lab subject cannot be generated in a normal room. Flag the condition
        # explicitly instead of allowing the solver to search an impossible space.
        lab_subjects = {
            assignment.subject_id
            for _, assignment, _ in requirements
            if assignment.subject.requires_lab
        }
        if lab_subjects and not any(room.is_lab for room in rooms):
            warnings.append("At least one subject requires a laboratory, but no active lab room is configured.")

        # Workload is a warning, not a blocker. The solver may legitimately use
        # co-teachers, and workload records are informational in this phase.
        teacher_periods = defaultdict(int)
        for _, assignment, periods in requirements:
            teacher_periods[assignment.teacher_id] += periods
        for assignment in assignments:
            if assignment.teacher_id not in teacher_periods:
                continue
            total = teacher_periods[assignment.teacher_id]
            if total > 25:
                name = assignment.teacher.user.get_full_name() or str(assignment.teacher)
                warnings.append(f"{name}: approximately {total} assigned periods/week exceeds the default 25-period workload reference.")
                teacher_periods.pop(assignment.teacher_id, None)

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
            },
        }
