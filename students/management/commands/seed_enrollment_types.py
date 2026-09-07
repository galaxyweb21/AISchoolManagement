# students/management/commands/seed_enrollment_types.py
from django.core.management.base import BaseCommand
from django.db import transaction
from students.models import StudentEnrollmentType
from school.models import School


class Command(BaseCommand):
    help = 'Seed enrollment types for all schools'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reseed even if data exists',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        schools = School.objects.all()

        if not schools.exists():
            self.stdout.write(self.style.ERROR('❌ No schools found!'))
            return

        enrollment_types = [
            {
                'code': 'NEW',
                'name': 'New Student',
                'order': 1,
                'description': 'First-time enrollment at the school. Auto-applies registration fees and new student add-ons.'
            },
            {
                'code': 'RETURNING',
                'name': 'Returning Student',
                'order': 2,
                'description': 'Student returning from previous term. Base fees only.'
            },
            {
                'code': 'TRANSFER',
                'name': 'Transfer Student',
                'order': 3,
                'description': 'Student transferring from another school. Base fees with optional add-ons.'
            },
        ]

        total_created = 0
        total_skipped = 0

        for school in schools:
            self.stdout.write(f'\n📚 Processing school: {school.name}')

            for data in enrollment_types:
                with transaction.atomic():
                    obj, created = StudentEnrollmentType.objects.get_or_create(
                        school=school,
                        code=data['code'],
                        defaults={
                            'name': data['name'],
                            'order': data['order'],
                            'description': data.get('description', ''),
                            'is_active': True,
                        }
                    )

                    if force and not created:
                        # Update existing if force flag is used
                        obj.name = data['name']
                        obj.order = data['order']
                        obj.description = data.get('description', '')
                        obj.is_active = True
                        obj.save()
                        self.stdout.write(
                            self.style.WARNING(f'  ↻ Updated: {data["name"]}')
                        )
                        total_created += 1
                    elif created:
                        self.stdout.write(
                            self.style.SUCCESS(f'  ✓ Created: {data["name"]}')
                        )
                        total_created += 1
                    else:
                        self.stdout.write(f'  ○ Exists: {data["name"]}')
                        total_skipped += 1

        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(
            self.style.SUCCESS(f'✅ Done! Created: {total_created}, Skipped: {total_skipped}')
        )