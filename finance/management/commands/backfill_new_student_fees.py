# finance/management/commands/backfill_new_student_fees.py
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from students.models import Student
from school.models import AcademicTerm
from finance.services.fee_preparation import auto_prepare_student_fees


class Command(BaseCommand):
    help = 'Backfill fees for students who should have add-ons but don\'t'

    def add_arguments(self, parser):
        parser.add_argument(
            '--student-id',
            type=str,
            help='Backfill only for a specific student ID'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def handle(self, *args, **options):
        school = options.get('school')
        student_id = options.get('student_id')
        dry_run = options.get('dry_run')

        if student_id:
            students = Student.objects.filter(id=student_id)
        else:
            students = Student.objects.filter(is_new_student=True)

        total = students.count()
        updated = 0
        errors = []

        self.stdout.write(f"Found {total} students to process")

        for student in students:
            try:
                if dry_run:
                    self.stdout.write(f"Would process: {student}")
                    continue

                with transaction.atomic():
                    result = auto_prepare_student_fees(student)
                    if result:
                        updated += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Updated fees for {student}: "
                                f"Total = {result.final_amount}"
                            )
                        )
                    else:
                        errors.append(f"Failed to prepare fees for {student}")

            except Exception as e:
                errors.append(f"Error processing {student}: {e}")

        self.stdout.write(f"\nCompleted: {updated} updated, {len(errors)} errors")

        if errors:
            for error in errors[:10]:
                self.stdout.write(self.style.ERROR(error))