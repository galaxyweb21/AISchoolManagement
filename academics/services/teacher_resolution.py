"""Teacher resolution for timetable-ready class/subject combinations.

Priority:
1. Explicit subject-teacher assignment(s) that are not the class teacher.
2. An explicit assignment for the class teacher, if it is the only assignment.
3. The class teacher itself when single-class-teacher mode is enabled.

This lets KG/Primary classes use one class teacher for all subjects without
requiring a duplicate TeacherAssignment row for every ClassSubject. Existing
TeacherAssignment rows remain fully supported.
"""
from collections import defaultdict

from academics.models import TeacherAssignment


def build_teacher_assignments_by_key(school, class_ids=None):
    qs = TeacherAssignment.objects.filter(
        school=school,
        is_active=True,
        school_class__is_active=True,
        subject__is_active=True,
        teacher__is_active=True,
        teacher__user__is_active=True,
    ).select_related("school_class", "subject", "teacher", "teacher__user")
    if class_ids:
        qs = qs.filter(school_class_id__in=class_ids)

    grouped = defaultdict(list)
    for assignment in qs:
        grouped[(assignment.school_class_id, assignment.subject_id)].append(assignment)
    return grouped


def resolve_assignments_for_class_subject(class_subject, assignments_by_key=None):
    """Return the teacher assignment candidates for one ClassSubject.

    If a different teacher has explicitly been assigned to the subject, that
    specialist assignment takes precedence over the homeroom/class teacher.
    If no specialist exists and the class is in single-teacher mode, the
    homeroom teacher is used as a virtual assignment even when no database
    TeacherAssignment row exists yet.
    """
    key = (class_subject.school_class_id, class_subject.subject_id)
    group = list((assignments_by_key or {}).get(key, []))
    school_class = class_subject.school_class
    homeroom_id = school_class.homeroom_teacher_id

    if group:
        specialist = [a for a in group if homeroom_id and a.teacher_id != homeroom_id]
        if specialist:
            return specialist
        return group

    if (
        school_class.uses_single_class_teacher
        and school_class.homeroom_teacher_id
        and getattr(school_class.homeroom_teacher, "is_active", False)
        and getattr(getattr(school_class.homeroom_teacher, "user", None), "is_active", False)
    ):
        return [None]

    return []


def resolved_teacher_id(class_subject, assignments_by_key=None):
    candidates = resolve_assignments_for_class_subject(class_subject, assignments_by_key)
    if not candidates:
        return None
    if candidates[0] is None:
        return str(class_subject.school_class.homeroom_teacher_id)
    primary = next((a for a in candidates if a.is_primary), candidates[0])
    return str(primary.teacher_id)
