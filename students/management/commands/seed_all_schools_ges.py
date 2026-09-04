# students/management/commands/seed_all_schools_ges.py
"""
Seed all existing schools with GES grade levels and default classes.

This is useful for schools that were created before the auto-seeding system
was implemented.

Usage:
    python manage.py seed_all_schools_ges
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from school.models import School
from students.models import GradeLevel
from academics.models import SchoolClass
from students.signals import seed_ges_grade_levels, create_default_school_classes


class Command(BaseCommand):
    help = "Seed all existing schools with GES grade levels and default classes."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually doing it.'
        )
        parser.add_argument(
            '--school',
            type=str,
            help='Seed only a specific school by subdomain.'
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        school_subdomain = options.get('school')

        if school_subdomain:
            try:
                schools = [School.objects.get(subdomain=school_subdomain)]
            except School.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"School with subdomain '{school_subdomain}' not found."))
                return
        else:
            schools = School.objects.all().order_by('name')

        if not schools:
            self.stdout.write(self.style.WARNING("No schools found."))
            return

        self.stdout.write(self.style.NOTICE(f"\n{'=' * 60}"))
        self.stdout.write(f"Seeding GES structure for {len(schools)} school(s)")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        self.stdout.write(f"{'=' * 60}\n")

        total_grade_levels = 0
        total_classes = 0

        for school in schools:
            self.stdout.write(f"\n📚 Processing: {school.name} (subdomain: {school.subdomain})")
            self.stdout.write("-" * 50)

            # Check existing grade levels
            existing_grades = GradeLevel.objects.filter(school=school).count()
            existing_classes = SchoolClass.objects.filter(school=school).count()

            self.stdout.write(f"  Existing grade levels: {existing_grades}")
            self.stdout.write(f"  Existing school classes: {existing_classes}")

            if not dry_run:
                with transaction.atomic():
                    # Seed grade levels
                    grade_count = seed_ges_grade_levels(school=school, use_class_naming=False)
                    total_grade_levels += grade_count

                    # Create default classes
                    class_count = create_default_school_classes(school=school)
                    total_classes += class_count

                    self.stdout.write(self.style.SUCCESS(f"  ✅ Created {grade_count} new grade levels"))
                    self.stdout.write(self.style.SUCCESS(f"  ✅ Created {class_count} new school classes"))
            else:
                # Dry run - calculate what would be created
                grades_to_create = 14 - existing_grades
                classes_to_create = 14 - existing_classes

                if grades_to_create > 0:
                    self.stdout.write(f"  Would create {grades_to_create} grade levels")
                if classes_to_create > 0:
                    self.stdout.write(f"  Would create {classes_to_create} school classes")
                if grades_to_create <= 0 and classes_to_create <= 0:
                    self.stdout.write(self.style.SUCCESS("  ✅ Already fully seeded!"))

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ Done! Created {total_grade_levels} new grade levels and {total_classes} new school classes."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"\n⚠️  Dry run complete. No changes were made."
            ))