# students/management/commands/seed_class_addons.py
from django.core.management.base import BaseCommand
from django.db import transaction
from finance.models import ClassAddOnStructure, ClassAddOnItem
from students.models import GradeLevel
from academics.models import SchoolClass
from finance.models import FeeCategory
from school.models import School


class Command(BaseCommand):
    help = 'Seed class-based add-ons'

    def handle(self, *args, **options):
        school = School.objects.first()
        if not school:
            self.stdout.write(self.style.ERROR('No school found!'))
            return

        # Get fee categories
        admission_category, _ = FeeCategory.objects.get_or_create(
            school=school,
            name='Admission Fee',
            defaults={'category_type': 'ADMISSION', 'is_recurring': False}
        )

        uniform_category, _ = FeeCategory.objects.get_or_create(
            school=school,
            name='Uniform',
            defaults={'category_type': 'UNIFORM', 'is_recurring': False}
        )

        # Create add-ons
        addons_data = [
            {
                'name': 'New Student Admission Fee',
                'fee_category': admission_category,
                'term_type': 'ALL',
                'apply_to_new_students_only': True,
                'is_required': True,
                'items': [
                    {'grade_name': 'KG 1', 'amount': 600},
                    {'grade_name': 'KG 2', 'amount': 700},
                    {'grade_name': 'Basic 1', 'amount': 800},
                    {'grade_name': 'Basic 2', 'amount': 800},
                    {'grade_name': 'Basic 3', 'amount': 800},
                    {'grade_name': 'Basic 4', 'amount': 900},
                    {'grade_name': 'Basic 5', 'amount': 900},
                    {'grade_name': 'Basic 6', 'amount': 900},
                    {'grade_name': 'JHS 1', 'amount': 1000},
                    {'grade_name': 'JHS 2', 'amount': 1000},
                    {'grade_name': 'JHS 3', 'amount': 1000},
                    {'grade_name': 'SHS 1', 'amount': 1200},
                    {'grade_name': 'SHS 2', 'amount': 1200},
                    {'grade_name': 'SHS 3', 'amount': 1200},
                ]
            },
            {
                'name': 'New Student Uniform Package',
                'fee_category': uniform_category,
                'term_type': 'ALL',
                'apply_to_new_students_only': True,
                'is_required': True,
                'items': [
                    {'grade_name': 'KG 1', 'amount': 200},
                    {'grade_name': 'KG 2', 'amount': 200},
                    {'grade_name': 'Basic 1', 'amount': 250},
                    {'grade_name': 'Basic 2', 'amount': 250},
                    {'grade_name': 'Basic 3', 'amount': 250},
                    {'grade_name': 'Basic 4', 'amount': 300},
                    {'grade_name': 'Basic 5', 'amount': 300},
                    {'grade_name': 'Basic 6', 'amount': 300},
                    {'grade_name': 'JHS 1', 'amount': 350},
                    {'grade_name': 'JHS 2', 'amount': 350},
                    {'grade_name': 'JHS 3', 'amount': 350},
                    {'grade_name': 'SHS 1', 'amount': 400},
                    {'grade_name': 'SHS 2', 'amount': 400},
                    {'grade_name': 'SHS 3', 'amount': 400},
                ]
            }
        ]

        for addon_data in addons_data:
            with transaction.atomic():
                addon, created = ClassAddOnStructure.objects.get_or_create(
                    school=school,
                    name=addon_data['name'],
                    defaults={
                        'fee_category': addon_data['fee_category'],
                        'term_type': addon_data['term_type'],
                        'apply_to_new_students_only': addon_data['apply_to_new_students_only'],
                        'is_required': addon_data['is_required'],
                    }
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f'Created add-on: {addon.name}'))

                    # Add items
                    for item_data in addon_data['items']:
                        grade = GradeLevel.objects.filter(
                            school=school,
                            name=item_data['grade_name']
                        ).first()

                        if grade:
                            ClassAddOnItem.objects.create(
                                addon_structure=addon,
                                grade_level=grade,
                                amount=item_data['amount'],
                            )
                            self.stdout.write(f'  - Added item for {grade.name}: GHS {item_data["amount"]}')
                else:
                    self.stdout.write(f'Add-on already exists: {addon.name}')