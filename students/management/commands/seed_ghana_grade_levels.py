# students/management/commands/seed_ghana_grade_levels.py
"""
Seeds a school with the official Ghana Education Service (GES) grade level
structure, as defined by the NaCCA Standards-Based Curriculum.

This command can be used manually, but grade levels are also automatically
seeded when a new school is created via signals.

Usage:
    # List all schools
    python manage.py seed_ghana_grade_levels --list-schools

    # Seed a specific school using subdomain
    python manage.py seed_ghana_grade_levels --subdomain <subdomain>

    # Seed a specific school using name
    python manage.py seed_ghana_grade_levels --name "School Name"

    # Use Class naming instead of Basic naming
    python manage.py seed_ghana_grade_levels --subdomain <subdomain> --use-class-naming

    # Seed all schools
    python manage.py seed_ghana_grade_levels --all
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from school.models import School
from students.models import GradeLevel


class Command(BaseCommand):
    help = "Seeds a school with the official Ghana Education Service (GES) grade level structure."

    def add_arguments(self, parser):
        parser.add_argument(
            '--subdomain',
            required=False,
            help="School subdomain to seed grade levels for."
        )
        parser.add_argument(
            '--name',
            required=False,
            help="School name (exact match) to seed grade levels for."
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help="Seed all schools in the system."
        )
        parser.add_argument(
            '--use-class-naming',
            action='store_true',
            help='Use "Class 1"-"Class 6" instead of "Basic 1"-"Basic 6" for the primary years.'
        )
        parser.add_argument(
            '--list-schools',
            action='store_true',
            help='List all available schools with their subdomains and exit.'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reseed even if grade levels already exist.'
        )

    def handle(self, *args, **options):
        # If list-schools flag is provided, list all schools and exit
        if options.get('list_schools'):
            self.list_schools()
            return

        # Get schools to seed
        schools = self.get_schools(options)

        if not schools:
            self.stdout.write(self.style.WARNING("No schools found to seed."))
            return

        # Seed each school
        for school in schools:
            self.seed_school(school, options)

    def list_schools(self):
        """List all available schools."""
        self.stdout.write(self.style.NOTICE("\n📚 Available Schools:"))
        self.stdout.write("-" * 70)

        schools = School.objects.all().order_by('name')
        if not schools.exists():
            self.stdout.write(self.style.WARNING("  No schools found in the system."))
            return

        for school in schools:
            status = "✓ Active" if school.is_active else "✗ Inactive"
            grade_count = GradeLevel.objects.filter(school=school).count()
            has_grade = f"{grade_count} grade levels" if grade_count > 0 else "No grades seeded"

            self.stdout.write(
                f"  • {school.name}"
            )
            self.stdout.write(f"    Subdomain: {school.subdomain}")
            self.stdout.write(f"    Status: {status} | {has_grade}")
            self.stdout.write("")

        self.stdout.write("-" * 70)
        self.stdout.write("\nTo seed grade levels, use:")
        self.stdout.write(f"  python manage.py seed_ghana_grade_levels --subdomain <subdomain>")
        self.stdout.write("\nOr seed all schools:")
        self.stdout.write(f"  python manage.py seed_ghana_grade_levels --all")

    def get_schools(self, options):
        """Get schools based on command options."""
        subdomain = options.get('subdomain')
        name = options.get('name')
        seed_all = options.get('all')
        force = options.get('force')

        if seed_all:
            schools = School.objects.all()
            if not force:
                # Only return schools that don't have grade levels
                schools_with_grades = GradeLevel.objects.values_list('school_id', flat=True).distinct()
                schools = schools.exclude(id__in=schools_with_grades)
            return schools

        if subdomain:
            try:
                return [School.objects.get(subdomain=subdomain)]
            except School.DoesNotExist:
                raise CommandError(f"No school found with subdomain '{subdomain}'.")

        if name:
            try:
                return [School.objects.get(name=name)]
            except School.DoesNotExist:
                raise CommandError(f"No school found with name '{name}'.")
            except School.MultipleObjectsReturned:
                raise CommandError(
                    f"Multiple schools matched '{name}' -- use --subdomain <subdomain> instead."
                )

        return []

    def seed_school(self, school, options):
        """Seed grade levels for a single school."""
        use_class_naming = options.get('use_class_naming')
        force = options.get('force')

        # Check if grade levels already exist
        existing_count = GradeLevel.objects.filter(school=school).count()
        if existing_count > 0 and not force:
            self.stdout.write(self.style.WARNING(
                f"⚠️  {school.name} already has {existing_count} grade levels. "
                f"Use --force to reseed."
            ))
            return

        structure = self.get_structure(use_class_naming)

        self.stdout.write(self.style.NOTICE(f"\n📚 Seeding grade levels for: {school.name}"))
        self.stdout.write(self.style.NOTICE(f"   Subdomain: {school.subdomain}"))
        self.stdout.write(self.style.NOTICE(f"   Naming: {'Class 1-6' if use_class_naming else 'Basic 1-6'}"))
        self.stdout.write("-" * 50)

        created, updated = 0, 0

        with transaction.atomic():
            # Remove existing if force is True
            if force:
                GradeLevel.objects.filter(school=school).delete()

            for grade_name, stage, order in structure:
                grade_level, was_created = GradeLevel.objects.update_or_create(
                    school=school,
                    name=grade_name,
                    defaults={'stage': stage, 'order': order},
                )
                if was_created:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created: {grade_name} ({stage})"))
                else:
                    updated += 1
                    self.stdout.write(self.style.NOTICE(f"  → Updated: {grade_name} ({stage})"))

        self.stdout.write("-" * 50)
        self.stdout.write(self.style.SUCCESS(
            f"✅ Done! Created: {created} | Updated: {updated}"
        ))

    def get_structure(self, use_class_naming=False):
        """Get the GES structure based on naming preference."""
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

        # GES Structure with Class naming
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

        return GES_STRUCTURE_CLASS if use_class_naming else GES_STRUCTURE_BASIC