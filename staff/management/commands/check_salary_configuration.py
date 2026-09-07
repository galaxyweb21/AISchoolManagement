from django.core.management.base import BaseCommand

from staff.models import (
    StaffProfile,
    SalaryStructure,
)


class Command(BaseCommand):
    help = (
        "Check employee salary configuration before "
        "switching payroll to SalaryStructure."
    )

    def handle(self, *args, **options):

        staff_members = (
            StaffProfile.objects
            .filter(
                is_active=True,
            )
            .select_related(
                "school",
                "staff_grade",
            )
            .order_by(
                "school_id",
                "id",
            )
        )

        total = 0
        configured = 0
        missing = 0

        for staff in staff_members:

            total += 1

            salary_exists = SalaryStructure.objects.filter(
                school=staff.school,
                staff=staff,
                is_active=True,
            ).exists()

            if salary_exists:
                configured += 1
                continue

            missing += 1

            grade_name = (
                staff.staff_grade.name
                if staff.staff_grade
                else "No grade"
            )

            self.stdout.write(
                self.style.WARNING(
                    "MISSING SALARY | "
                    f"Staff ID: {staff.pk} | "
                    f"Grade: {grade_name}"
                )
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Active staff: {total}"
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Configured: {configured}"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Missing: {missing}"
            )
        )

        if missing:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Payroll should not be finalized until "
                    "missing employee salary structures "
                    "are configured."
                )
            )
        else:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    "All active staff have salary structures."
                )
            )