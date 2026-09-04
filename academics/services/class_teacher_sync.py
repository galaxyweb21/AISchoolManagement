# academics/services/class_teacher_sync.py
"""
Supports the "one class teacher teaches every subject" pattern common in
Ghanaian Nursery/KG and lower Primary classes -- as opposed to the
subject-teacher-per-class pattern typical from JHS upward.

The underlying data model (TeacherAssignment: teacher + school_class +
subject) doesn't change -- the timetabler and workload reports still read
from it exactly as before. What changes is the WORKFLOW: assigning one
class teacher via assign_class_teacher() auto-populates a TeacherAssignment
row for every subject already on the class (ClassSubject), so nobody has
to manually create one assignment per subject for a KG class that has, say,
six subjects.
"""
from ..models import ClassSubject, TeacherAssignment


def sync_class_teacher_assignments(school_class):
    """
    Ensure the class's homeroom_teacher has a TeacherAssignment row for
    every subject already on the class (ClassSubject), when the class is
    in single-class-teacher mode. No-op if that mode is off, or if no
    homeroom teacher is set yet.

    Auto-created rows are marked is_primary=True -- see assign_class_teacher()
    for why that matters when a class teacher is later replaced.

    Returns the list of newly created TeacherAssignment rows (existing ones
    are left untouched via get_or_create).
    """
    if not school_class.uses_single_class_teacher or not school_class.homeroom_teacher_id:
        return []

    created = []
    for class_subject in ClassSubject.objects.filter(school_class=school_class, is_active=True):
        assignment, was_created = TeacherAssignment.objects.get_or_create(
            teacher=school_class.homeroom_teacher,
            school_class=school_class,
            subject=class_subject.subject,
            defaults={
                'school': school_class.school,
                'periods_per_week': class_subject.periods_per_week,
                'is_primary': True,
            },
        )
        if was_created:
            created.append(assignment)
    return created


def assign_class_teacher(school_class, teacher, uses_single_class_teacher=None, assigned_by=None):
    """
    Set (or replace) the class/homeroom teacher for a class.

    If the class is in single-class-teacher mode, this also:
      - deactivates the OUTGOING teacher's auto-generated TeacherAssignment
        rows for this class (scoped to is_primary=True, which is exactly
        what sync_class_teacher_assignments() sets -- a specialist teacher
        an admin separately added for one subject, as a non-primary
        assignment, is left alone rather than removed by this)
      - creates the incoming teacher's TeacherAssignment rows via
        sync_class_teacher_assignments()

    `uses_single_class_teacher`, if not None, updates that flag on the class
    at the same time (e.g. from a form checkbox) -- pass None to leave
    whatever the class is already set to unchanged.

    Returns {'created': [...], 'deactivated': <count>}.
    """
    previous_teacher_id = school_class.homeroom_teacher_id

    update_fields = ['homeroom_teacher', 'updated_at']
    school_class.homeroom_teacher = teacher
    if uses_single_class_teacher is not None:
        school_class.uses_single_class_teacher = uses_single_class_teacher
        update_fields.append('uses_single_class_teacher')

    school_class.save(update_fields=update_fields)

    if not school_class.uses_single_class_teacher:
        return {'created': [], 'deactivated': 0}

    deactivated = 0
    new_teacher_id = teacher.id if teacher else None
    if previous_teacher_id and previous_teacher_id != new_teacher_id:
        deactivated = TeacherAssignment.objects.filter(
            school_class=school_class, teacher_id=previous_teacher_id, is_primary=True,
        ).update(is_active=False)

    created = sync_class_teacher_assignments(school_class)
    return {'created': created, 'deactivated': deactivated}
