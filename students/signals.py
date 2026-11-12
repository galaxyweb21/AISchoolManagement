# students/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.management import call_command
from django.db import transaction
import logging

from school.models import School
from students.models import GradeLevel
from academics.models import SchoolClass
from students.models import Student, StudentEnrollmentType

logger = logging.getLogger(__name__)


@receiver(post_save, sender=School)
def seed_grade_levels_and_classes_on_school_creation(sender, instance, created, **kwargs):
    """
    Automatically seed Ghana Education Service (GES) grade levels
    AND create default SchoolClasses when a new school is created.
    """
    if not created:
        # Only run on new school creation
        return

    try:
        with transaction.atomic():
            # Step 1: Seed GES grade levels
            grade_levels_created = seed_ges_grade_levels(school=instance, use_class_naming=False)

            # Step 2: Create default SchoolClass for each grade level
            classes_created = create_default_school_classes(school=instance)

            # Step 3: Seed the enrollment lifecycle required by automatic
            # fee preparation/invoicing. This makes a brand-new school
            # usable immediately without a manual management command.
            enrollment_types_created = seed_default_enrollment_types(school=instance)

            logger.info(
                f"Successfully seeded {grade_levels_created} grade levels, "
                f"created {classes_created} school classes and "
                f"seeded {enrollment_types_created} enrollment types for {instance.name} "
                f"(subdomain: {instance.subdomain})"
            )

    except Exception as e:
        logger.error(f"Failed to seed grade levels/classes for {instance.name}: {str(e)}")


def seed_ges_grade_levels(school, use_class_naming=False):
    """
    Seed Ghana Education Service grade levels for a school.

    Returns:
        int: Number of grade levels created
    """
    # GES Structure with Basic naming (official)
    GES_STRUCTURE_BASIC = [
        ("KG 1", "KG", 1),
        ("KG 2", "KG", 2),
        ("Basic 1", "PRIMARY", 3),
        ("Basic 2", "PRIMARY", 4),
        ("Basic 3", "PRIMARY", 5),
        ("Basic 4", "PRIMARY", 6),
        ("Basic 5", "PRIMARY", 7),
        ("Basic 6", "PRIMARY", 8),
        ("JHS 1", "JHS", 9),
        ("JHS 2", "JHS", 10),
        ("JHS 3", "JHS", 11),
        ("SHS 1", "SHS", 12),
        ("SHS 2", "SHS", 13),
        ("SHS 3", "SHS", 14),
    ]

    # GES Structure with Class naming (common in Ghanaian schools)
    GES_STRUCTURE_CLASS = [
        ("KG 1", "KG", 1),
        ("KG 2", "KG", 2),
        ("Class 1", "PRIMARY", 3),
        ("Class 2", "PRIMARY", 4),
        ("Class 3", "PRIMARY", 5),
        ("Class 4", "PRIMARY", 6),
        ("Class 5", "PRIMARY", 7),
        ("Class 6", "PRIMARY", 8),
        ("JHS 1", "JHS", 9),
        ("JHS 2", "JHS", 10),
        ("JHS 3", "JHS", 11),
        ("SHS 1", "SHS", 12),
        ("SHS 2", "SHS", 13),
        ("SHS 3", "SHS", 14),
    ]

    structure = GES_STRUCTURE_CLASS if use_class_naming else GES_STRUCTURE_BASIC

    created_count = 0
    for name, stage, order in structure:
        grade_level, created = GradeLevel.objects.get_or_create(
            school=school,
            name=name,
            defaults={
                'stage': stage,
                'order': order,
            }
        )
        if created:
            created_count += 1

    return created_count


def create_default_school_classes(school):
    """
    Create a default SchoolClass for each grade level in the school.
    The SchoolClass name matches the grade level name.

    Returns:
        int: Number of school classes created
    """
    created_count = 0

    # Get all grade levels for this school, ordered by order
    grade_levels = GradeLevel.objects.filter(school=school).order_by('order')

    for grade_level in grade_levels:
        # Create a SchoolClass with the same name as the grade level
        # Skip if a class with this name already exists for this grade level
        school_class, created = SchoolClass.objects.get_or_create(
            school=school,
            name=grade_level.name,
            grade_level=grade_level,
            defaults={
                'student_count': 0,  # Start with zero students
                'homeroom_teacher': None,
            }
        )
        if created:
            created_count += 1
            logger.info(f"Created default SchoolClass: {grade_level.name} for {school.name}")

    return created_count

def seed_default_enrollment_types(school):
    """Create the three standard enrollment types required by fee automation."""
    defaults = [
        {
            "code": "NEW",
            "name": "New Student",
            "order": 1,
            "description": "First-time enrollment. Applies configured new-student fees/add-ons.",
        },
        {
            "code": "RETURNING",
            "name": "Returning Student",
            "order": 2,
            "description": "Student returning from a previous term.",
        },
        {
            "code": "TRANSFER",
            "name": "Transfer Student",
            "order": 3,
            "description": "Student transferring from another school.",
        },
    ]
    created_count = 0
    for data in defaults:
        _, created = StudentEnrollmentType.objects.get_or_create(
            school=school,
            code=data["code"],
            defaults={
                "name": data["name"],
                "order": data["order"],
                "description": data["description"],
                "is_active": True,
                "auto_prepare_fees": True,
                "auto_approve_fees": True,
            },
        )
        created_count += int(created)
    return created_count


@receiver(post_save, sender=Student)
def auto_prepare_and_invoice_new_student(sender, instance, created, **kwargs):
    """
    Enterprise financial automation for every newly created student.

    Runs after the database transaction commits, so student creation is not
    rolled back merely because a financial automation step has an issue.
    """
    if not created or not instance.school:
        return

    def _run():
        try:
            from finance.services.auto_invoicing import ensure_student_term_invoice
            invoice = ensure_student_term_invoice(
                instance,
                created_by=None,
            )
            if invoice:
                logger.info(
                    "Automatic invoice %s created/reused for new student %s.",
                    invoice.invoice_number,
                    instance,
                )
        except Exception:
            logger.exception(
                "Automatic fee/invoice processing failed for new student %s.",
                instance,
            )

    transaction.on_commit(_run)
