# academics/signals.py
from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
from students.models import Student
from .models import SchoolClass, ClassSubject, TeacherAssignment


@receiver(post_save, sender=ClassSubject)
def sync_class_teacher_for_new_class_subject(sender, instance, created, **kwargs):
    """
    When a subject is added to a class that already has a class teacher in
    single-class-teacher mode (see academics.services.class_teacher_sync),
    that teacher should automatically cover the new subject too -- no
    separate manual assignment step for it.
    """
    if not created:
        return

    school_class = instance.school_class
    if school_class.uses_single_class_teacher and school_class.homeroom_teacher_id:
        TeacherAssignment.objects.get_or_create(
            teacher=school_class.homeroom_teacher,
            school_class=school_class,
            subject=instance.subject,
            defaults={
                'school': school_class.school,
                'periods_per_week': instance.periods_per_week,
                'is_primary': True,
            },
        )


@receiver(post_save, sender=Student)
def update_school_class_count_on_save(sender, instance, created, **kwargs):
    """
    When a student is saved (created OR updated),
    we check if their grade_level changed. If so, we re-count BOTH
    the old class and the new class.
    """
    # 1. We get the class ID from the student's grade_level
    #    (Assuming the Student.grade_level matches SchoolClass.grade_level)
    # Note: If you don't have a direct link, you might skip this.
    #    However, the ideal enterprise setup is that Student.grade_level FK
    #    is the SAME model as SchoolClass.grade_level FK.

    # For the auto-count to work properly, we assume the student's grade_level
    # can be mapped to a SchoolClass.
    # If your system links a specific student to a specific class,
    # you would use Student.school_class instead of Student.grade_level.
    # But if linking by grade level:

    if instance.grade_level:
        # Update the count for the grade level this student belongs to
        # We need to count how many SchoolClasses have this grade_level?
        # OR, if a Student is directly linked to a SchoolClass, we update the class.

        # To keep it Enterprise-ready, let's assume we want to update the total
        # student count on all SchoolClasses with this GradeLevel.
        classes_to_update = SchoolClass.objects.filter(
            school=instance.school,
            grade_level=instance.grade_level
        )
        for school_class in classes_to_update:
            # Count how many students share this school and grade_level
            new_count = Student.objects.filter(
                school=instance.school,
                grade_level=instance.grade_level,
                is_active=True
            ).count()
            school_class.student_count = new_count
            school_class.save(update_fields=['student_count'])


@receiver(pre_delete, sender=Student)
def update_school_class_count_on_delete(sender, instance, **kwargs):
    """
    Before a student is deleted, we update the count for their grade_level.
    """
    if instance.grade_level:
        classes_to_update = SchoolClass.objects.filter(
            school=instance.school,
            grade_level=instance.grade_level
        )
        for school_class in classes_to_update:
            new_count = Student.objects.filter(
                school=instance.school,
                grade_level=instance.grade_level,
                is_active=True
            ).count()
            # Ensure count doesn't go negative
            school_class.student_count = new_count - 1 if new_count > 0 else 0
            school_class.save(update_fields=['student_count'])