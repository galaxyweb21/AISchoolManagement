"""
Enterprise Employee Salary Service
===================================

Single source of truth for actual employee basic salary.

RULE:
-----
Payroll must obtain basic salary from SalaryStructure.

StaffGrade.base_salary is NOT used by payroll.

SalaryStructure is effective-dated and employee-specific.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from staff.models import (
    StaffProfile,
    SalaryStructure,
)


class SalaryStructureError(Exception):
    """Base exception for salary structure errors."""


class SalaryStructureNotFoundError(SalaryStructureError):
    """Raised when no salary structure exists for an employee."""


class SalaryStructureConfigurationError(SalaryStructureError):
    """Raised when salary data is invalid or ambiguous."""


def get_effective_salary_structure(
    staff,
    payroll_date=None,
):
    """
    Return the ONE salary structure applicable to an employee
    on the supplied payroll date.

    There is deliberately NO fallback to StaffGrade.base_salary.

    Parameters
    ----------
    staff:
        StaffProfile instance.

    payroll_date:
        Date on which salary should be evaluated.

    Returns
    -------
    SalaryStructure

    Raises
    ------
    SalaryStructureNotFoundError
        No employee salary exists for the requested date.

    SalaryStructureConfigurationError
        More than one salary structure applies.
    """

    if not staff:
        raise SalaryStructureNotFoundError(
            "No staff member was supplied."
        )

    if payroll_date is None:
        payroll_date = date.today()

    if not isinstance(payroll_date, date):
        raise SalaryStructureConfigurationError(
            "payroll_date must be a date."
        )

    queryset = SalaryStructure.objects.filter(
        school=staff.school,
        staff=staff,
        is_active=True,
        effective_date__lte=payroll_date,
    )

    # Apply the end-date condition separately because the queryset above
    # intentionally remains readable.
    from django.db.models import Q

    queryset = queryset.filter(
        Q(effective_to__isnull=True)
        |
        Q(effective_to__gte=payroll_date)
    ).order_by(
        "-effective_date",
        "-created_at",
    )

    structures = list(queryset[:2])

    if not structures:
        raise SalaryStructureNotFoundError(
            "No active SalaryStructure exists for "
            f"{staff} on {payroll_date:%Y-%m-%d}. "
            "Payroll cannot continue without an employee salary structure."
        )

    if len(structures) > 1:
        raise SalaryStructureConfigurationError(
            "Multiple SalaryStructures apply to "
            f"{staff} on {payroll_date:%Y-%m-%d}. "
            "Resolve the overlapping salary records before payroll."
        )

    structure = structures[0]

    if structure.basic_salary is None:
        raise SalaryStructureConfigurationError(
            f"SalaryStructure {structure.pk} has no basic salary."
        )

    if structure.basic_salary < Decimal("0.00"):
        raise SalaryStructureConfigurationError(
            f"SalaryStructure {structure.pk} has an invalid "
            "negative basic salary."
        )

    return structure


def get_effective_basic_salary(
    staff,
    payroll_date=None,
):
    """
    Return the authoritative basic salary for payroll.
    """

    structure = get_effective_salary_structure(
        staff=staff,
        payroll_date=payroll_date,
    )

    return structure.basic_salary


def validate_staff_salary_configuration(
    staff,
    payroll_date=None,
):
    """
    Validate that a staff member is ready for payroll.

    Returns a dictionary suitable for payroll validation screens/APIs.
    """

    if payroll_date is None:
        payroll_date = date.today()

    try:
        structure = get_effective_salary_structure(
            staff=staff,
            payroll_date=payroll_date,
        )

        return {
            "valid": True,
            "staff_id": str(staff.pk),
            "salary_structure_id": str(structure.pk),
            "basic_salary": structure.basic_salary,
            "frequency": structure.frequency,
            "effective_date": structure.effective_date,
            "effective_to": structure.effective_to,
            "error": None,
        }

    except SalaryStructureError as exc:
        return {
            "valid": False,
            "staff_id": str(staff.pk),
            "salary_structure_id": None,
            "basic_salary": Decimal("0.00"),
            "frequency": None,
            "effective_date": None,
            "effective_to": None,
            "error": str(exc),
        }


@transaction.atomic
def create_salary_structure(
    *,
    staff,
    basic_salary,
    effective_date,
    effective_to=None,
    frequency=SalaryStructure.FREQUENCY_MONTHLY,
    staff_grade=None,
    is_active=True,
):
    """
    Create an employee salary structure.

    This is the preferred service for new salary records.
    """

    if not isinstance(staff, StaffProfile):
        raise ValidationError(
            "staff must be a StaffProfile instance."
        )

    if staff_grade is None:
        staff_grade = getattr(
            staff,
            "staff_grade",
            None,
        )

    structure = SalaryStructure(
        school=staff.school,
        staff=staff,
        staff_grade=staff_grade,
        basic_salary=basic_salary,
        frequency=frequency,
        effective_date=effective_date,
        effective_to=effective_to,
        is_active=is_active,
    )

    structure.full_clean()
    structure.save()

    return structure


@transaction.atomic
def update_salary_structure(
    structure,
    *,
    basic_salary=None,
    effective_date=None,
    effective_to=None,
    frequency=None,
    staff_grade=None,
    is_active=None,
):
    """
    Safely update an existing salary structure.
    """

    if basic_salary is not None:
        structure.basic_salary = basic_salary

    if effective_date is not None:
        structure.effective_date = effective_date

    if effective_to is not None:
        structure.effective_to = effective_to

    if frequency is not None:
        structure.frequency = frequency

    if staff_grade is not None:
        structure.staff_grade = staff_grade

    if is_active is not None:
        structure.is_active = is_active

    structure.full_clean()
    structure.save()

    return structure