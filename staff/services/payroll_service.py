# staff/services/payroll_service.py

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from staff.models import (
    StaffProfile,
    SalaryStructure,
    StaffAllowance,
    StaffDeduction,
    PayrollPeriod,
    PayrollRun,
    Payslip,
)


# ============================================================
# CONSTANTS
# ============================================================

MONEY_ZERO = Decimal("0.00")
MONEY_QUANTIZER = Decimal("0.01")

SSNIT_EMPLOYEE_RATE = Decimal("0.055")
SSNIT_EMPLOYER_RATE = Decimal("0.130")

DEFAULT_BASIC_SALARY = Decimal("1000.00")


# ============================================================
# PAYROLL PREPARATION ERROR
# ============================================================

class PayrollPreparationError(Exception):
    """
    Business-level payroll preparation exception.
    """
    pass


# ============================================================
# DECIMAL / MONEY HELPERS
# ============================================================

def money(value):
    """
    Safely convert a value to a 2-decimal Decimal.
    """

    if value is None:
        return MONEY_ZERO

    try:
        return Decimal(str(value)).quantize(
            MONEY_QUANTIZER,
            rounding=ROUND_HALF_UP,
        )
    except Exception:
        raise ValidationError(
            f"Invalid monetary value: {value}"
        )


def percentage(amount, rate):
    """
    Calculate a percentage safely.
    """

    return money(
        Decimal(str(amount)) * Decimal(str(rate))
    )


# ============================================================
# PAYE ENGINE
# ============================================================

class GhanaPAYECalculator:
    """
    Ghana monthly resident individual PAYE calculation.
    """

    MONTHLY_BANDS = (
        (Decimal("319.00"), Decimal("0.00")),
        (Decimal("100.00"), Decimal("0.05")),
        (Decimal("120.00"), Decimal("0.10")),
        (Decimal("3000.00"), Decimal("0.175")),
        (Decimal("16461.00"), Decimal("0.25")),
        (None, Decimal("0.30")),
    )

    @classmethod
    def calculate(cls, chargeable_income):

        income = money(chargeable_income)

        if income <= MONEY_ZERO:
            return MONEY_ZERO

        remaining = income
        tax = MONEY_ZERO

        for band_amount, rate in cls.MONTHLY_BANDS:

            if remaining <= MONEY_ZERO:
                break

            if band_amount is None:
                taxable = remaining
            else:
                taxable = min(
                    remaining,
                    band_amount,
                )

            tax += taxable * rate
            remaining -= taxable

        return money(tax)


# ============================================================
# SALARY STRUCTURE SERVICE
# ============================================================

class SalaryStructureService:
    """
    Provides the effective SalaryStructure for an active
    staff member.

    SalaryStructure.basic_salary is authoritative.
    """

    @classmethod
    def get_effective_structure(
        cls,
        staff,
        effective_date,
    ):

        if not staff:
            raise PayrollPreparationError(
                "A staff member is required."
            )

        if not effective_date:
            raise PayrollPreparationError(
                "An effective payroll date is required."
            )

        # ----------------------------------------------------
        # STAFF MUST BE ACTIVE
        # ----------------------------------------------------

        if not staff.is_active:
            raise PayrollPreparationError(
                f"{cls._staff_name(staff)} is inactive "
                "and cannot receive salary."
            )

        # ----------------------------------------------------
        # FIND ACTIVE EFFECTIVE SALARY STRUCTURE
        # ----------------------------------------------------

        structure = (
            SalaryStructure.objects
            .filter(
                school=staff.school,
                staff=staff,
                effective_date__lte=effective_date,
                is_active=True,
            )
            .filter(
                Q(effective_to__isnull=True)
                |
                Q(effective_to__gte=effective_date)
            )
            .order_by(
                "-effective_date",
                "-created_at",
            )
            .first()
        )

        # ----------------------------------------------------
        # AUTO-CREATE STRUCTURE IF MISSING
        # ----------------------------------------------------

        if not structure:

            salary_amount = DEFAULT_BASIC_SALARY

            if staff.staff_grade:

                grade_salary = getattr(
                    staff.staff_grade,
                    "base_salary",
                    None,
                )

                if grade_salary is not None:
                    grade_salary = money(
                        grade_salary
                    )

                    if grade_salary > MONEY_ZERO:
                        salary_amount = grade_salary

            # ------------------------------------------------
            # REUSE EXISTING STRUCTURE IF AVAILABLE
            # ------------------------------------------------

            existing_structure = (
                SalaryStructure.objects
                .filter(
                    school=staff.school,
                    staff=staff,
                )
                .order_by(
                    "-effective_date",
                    "-created_at",
                )
                .first()
            )

            try:

                if existing_structure:

                    existing_structure.is_active = True
                    existing_structure.basic_salary = (
                        salary_amount
                    )
                    existing_structure.effective_date = (
                        effective_date
                    )
                    existing_structure.effective_to = None

                    if hasattr(
                        existing_structure,
                        "staff_grade_id",
                    ):
                        existing_structure.staff_grade = (
                            staff.staff_grade
                        )

                    existing_structure.save()

                    structure = existing_structure

                else:

                    structure = (
                        SalaryStructure.objects.create(
                            school=staff.school,
                            staff=staff,
                            staff_grade=(
                                staff.staff_grade
                            ),
                            basic_salary=(
                                salary_amount
                            ),
                            frequency="MONTHLY",
                            effective_date=(
                                effective_date
                            ),
                            effective_to=None,
                            is_active=True,
                        )
                    )

            except Exception as exc:

                raise PayrollPreparationError(
                    f"Unable to create salary structure for "
                    f"{cls._staff_name(staff)}: {exc}"
                ) from exc

        # ----------------------------------------------------
        # VALIDATE BASIC SALARY
        # ----------------------------------------------------

        if structure.basic_salary is None:

            raise PayrollPreparationError(
                f"The SalaryStructure for "
                f"{cls._staff_name(staff)} "
                "does not contain a basic salary."
            )

        basic_salary = money(
            structure.basic_salary
        )

        if basic_salary < MONEY_ZERO:

            raise PayrollPreparationError(
                f"The basic salary for "
                f"{cls._staff_name(staff)} "
                "cannot be negative."
            )

        return structure

    @staticmethod
    def _staff_name(staff):

        user = getattr(
            staff,
            "user",
            None,
        )

        if user:

            name = (
                user.get_full_name()
                or getattr(
                    user,
                    "username",
                    "",
                )
            )

            if name:
                return name.strip()

        return str(staff)


# ============================================================
# ALLOWANCE SERVICE
# ============================================================

class PayrollAllowanceService:
    """
    Calculates all active allowances assigned to a staff member.

    IMPORTANT:

    The master Allowance contains the default amount.

    StaffAllowance.amount, when populated with a positive amount,
    overrides the master amount.

    If StaffAllowance.amount is NULL or zero, the master
    Allowance.amount is used.

    This prevents an accidentally empty/zero staff assignment
    from causing an otherwise configured allowance to disappear.
    """

    @classmethod
    def get_staff_allowances(cls, staff):

        if not staff:
            return StaffAllowance.objects.none()

        if not staff.is_active:
            return StaffAllowance.objects.none()

        return (
            StaffAllowance.objects
            .select_related(
                "allowance",
            )
            .filter(
                school=staff.school,
                staff=staff,
                is_active=True,
                allowance__school=staff.school,
                allowance__is_active=True,
            )
            .order_by(
                "allowance__name",
                "id",
            )
        )

    @classmethod
    def _resolve_amount(
        cls,
        staff_allowance,
        allowance,
    ):
        """
        Resolve the actual allowance amount.

        Priority:

        1. StaffAllowance.amount if it is greater than zero.
        2. Allowance.amount.
        3. Zero.
        """

        staff_amount = getattr(
            staff_allowance,
            "amount",
            None,
        )

        master_amount = getattr(
            allowance,
            "amount",
            None,
        )

        # ----------------------------------------------------
        # STAFF-SPECIFIC AMOUNT
        # ----------------------------------------------------

        if staff_amount is not None:

            staff_amount = money(
                staff_amount
            )

            if staff_amount > MONEY_ZERO:
                return staff_amount

        # ----------------------------------------------------
        # MASTER ALLOWANCE AMOUNT
        # ----------------------------------------------------

        if master_amount is not None:

            master_amount = money(
                master_amount
            )

            if master_amount > MONEY_ZERO:
                return master_amount

        return MONEY_ZERO

    @classmethod
    def calculate(
        cls,
        staff,
        basic_salary,
    ):

        basic_salary = money(
            basic_salary
        )

        if not staff:

            return {
                "items": [],
                "total": MONEY_ZERO,
                "taxable_total": MONEY_ZERO,
                "non_taxable_total": MONEY_ZERO,
            }

        if not staff.is_active:

            return {
                "items": [],
                "total": MONEY_ZERO,
                "taxable_total": MONEY_ZERO,
                "non_taxable_total": MONEY_ZERO,
            }

        items = []

        total = MONEY_ZERO
        taxable_total = MONEY_ZERO
        non_taxable_total = MONEY_ZERO

        allowances = (
            cls.get_staff_allowances(
                staff
            )
        )

        for staff_allowance in allowances:

            allowance = (
                staff_allowance.allowance
            )

            if not allowance:
                continue

            # ------------------------------------------------
            # RESOLVE CONFIGURED AMOUNT
            # ------------------------------------------------

            configured_amount = (
                cls._resolve_amount(
                    staff_allowance,
                    allowance,
                )
            )

            # ------------------------------------------------
            # CALCULATE ACTUAL AMOUNT
            # ------------------------------------------------

            is_percentage = bool(
                getattr(
                    allowance,
                    "is_percentage",
                    False,
                )
            )

            if is_percentage:

                calculated_amount = percentage(
                    basic_salary,
                    configured_amount
                    / Decimal("100.00"),
                )

            else:

                calculated_amount = money(
                    configured_amount
                )

            if calculated_amount < MONEY_ZERO:
                calculated_amount = MONEY_ZERO

            # ------------------------------------------------
            # ACCUMULATE
            # ------------------------------------------------

            total += calculated_amount

            taxable = bool(
                getattr(
                    allowance,
                    "taxable",
                    False,
                )
            )

            if taxable:
                taxable_total += calculated_amount
            else:
                non_taxable_total += calculated_amount

            # ------------------------------------------------
            # SNAPSHOT
            # ------------------------------------------------

            items.append(
                {
                    "id": str(
                        staff_allowance.id
                    ),
                    "name": (
                        getattr(
                            allowance,
                            "name",
                            "Allowance",
                        )
                    ),
                    "type": (
                        getattr(
                            allowance,
                            "allowance_type",
                            "OTHER",
                        )
                    ),
                    "amount": money(
                        calculated_amount
                    ),
                    "taxable": taxable,
                    "is_percentage": (
                        is_percentage
                    ),
                    "configured_amount": str(
                        configured_amount
                    ),
                }
            )

        return {
            "items": items,
            "total": money(total),
            "taxable_total": money(
                taxable_total
            ),
            "non_taxable_total": money(
                non_taxable_total
            ),
        }


# ============================================================
# DEDUCTION SERVICE
# ============================================================

class PayrollDeductionService:

    @classmethod
    def get_staff_deductions(cls, staff):

        if not staff:
            return StaffDeduction.objects.none()

        if not staff.is_active:
            return StaffDeduction.objects.none()

        return (
            StaffDeduction.objects
            .select_related(
                "deduction",
            )
            .filter(
                school=staff.school,
                staff=staff,
                is_active=True,
                deduction__school=staff.school,
                deduction__is_active=True,
            )
            .order_by(
                "deduction__name",
                "id",
            )
        )

    @classmethod
    def calculate(
        cls,
        staff,
        basic_salary,
    ):

        basic_salary = money(
            basic_salary
        )

        if not staff or not staff.is_active:

            return {
                "items": [],
                "total": MONEY_ZERO,
            }

        items = []

        total = MONEY_ZERO

        deductions = (
            cls.get_staff_deductions(
                staff
            )
        )

        for staff_deduction in deductions:

            deduction = (
                staff_deduction.deduction
            )

            if not deduction:
                continue

            deduction_type = getattr(
                deduction,
                "deduction_type",
                "",
            )

            # ------------------------------------------------
            # STATUTORY DEDUCTIONS ARE CALCULATED SEPARATELY
            # ------------------------------------------------

            if deduction_type in (
                "PAYE",
                "SSNIT",
            ):
                continue

            # ------------------------------------------------
            # RESOLVE AMOUNT
            # ------------------------------------------------

            staff_amount = getattr(
                staff_deduction,
                "amount",
                None,
            )

            master_amount = getattr(
                deduction,
                "amount",
                None,
            )

            if staff_amount is not None:

                configured_amount = money(
                    staff_amount
                )

                if configured_amount <= MONEY_ZERO:

                    configured_amount = money(
                        master_amount
                    )

            else:

                configured_amount = money(
                    master_amount
                )

            # ------------------------------------------------
            # CALCULATE
            # ------------------------------------------------

            is_percentage = bool(
                getattr(
                    deduction,
                    "is_percentage",
                    False,
                )
            )

            if is_percentage:

                calculated_amount = percentage(
                    basic_salary,
                    configured_amount
                    / Decimal("100.00"),
                )

            else:

                calculated_amount = (
                    configured_amount
                )

            if calculated_amount < MONEY_ZERO:
                calculated_amount = MONEY_ZERO

            total += calculated_amount

            items.append(
                {
                    "id": str(
                        staff_deduction.id
                    ),
                    "name": getattr(
                        deduction,
                        "name",
                        "Deduction",
                    ),
                    "type": deduction_type,
                    "amount": money(
                        calculated_amount
                    ),
                    "mandatory": bool(
                        getattr(
                            deduction,
                            "is_mandatory",
                            False,
                        )
                    ),
                    "is_percentage": (
                        is_percentage
                    ),
                }
            )

        return {
            "items": items,
            "total": money(total),
        }


# ============================================================
# STATUTORY PAYROLL SERVICE
# ============================================================

class GhanaStatutoryPayrollService:

    @classmethod
    def calculate(
        cls,
        basic_salary,
        taxable_allowances,
    ):

        basic_salary = money(
            basic_salary
        )

        taxable_allowances = money(
            taxable_allowances
        )

        # ----------------------------------------------------
        # EMPLOYEE SSNIT
        # ----------------------------------------------------

        employee_ssnit = percentage(
            basic_salary,
            SSNIT_EMPLOYEE_RATE,
        )

        # ----------------------------------------------------
        # EMPLOYER SSNIT
        # ----------------------------------------------------

        employer_ssnit = percentage(
            basic_salary,
            SSNIT_EMPLOYER_RATE,
        )

        # ----------------------------------------------------
        # TAXABLE INCOME
        # ----------------------------------------------------

        taxable_income = money(
            basic_salary
            + taxable_allowances
        )

        # ----------------------------------------------------
        # CHARGEABLE INCOME
        # ----------------------------------------------------

        chargeable_income = money(
            taxable_income
            - employee_ssnit
        )

        if chargeable_income < MONEY_ZERO:
            chargeable_income = MONEY_ZERO

        # ----------------------------------------------------
        # PAYE
        # ----------------------------------------------------

        paye = (
            GhanaPAYECalculator
            .calculate(
                chargeable_income
            )
        )

        return {
            "employee_ssnit": money(
                employee_ssnit
            ),
            "employer_ssnit": money(
                employer_ssnit
            ),
            "taxable_income": money(
                taxable_income
            ),
            "chargeable_income": money(
                chargeable_income
            ),
            "paye": money(
                paye
            ),
        }


# ============================================================
# PAYROLL CALCULATION RESULT
# ============================================================

class PayrollCalculationResult:

    def __init__(
        self,
        staff,
        salary_structure,
        basic_salary,
        allowances,
        deductions,
        statutory,
    ):

        self.staff = staff

        self.salary_structure = (
            salary_structure
        )

        self.basic_salary = money(
            basic_salary
        )

        self.allowances = allowances

        self.deductions = deductions

        self.statutory = statutory

        # ----------------------------------------------------
        # GROSS PAY
        # ----------------------------------------------------

        self.gross_pay = money(
            self.basic_salary
            + money(
                allowances.get(
                    "total",
                    MONEY_ZERO,
                )
            )
        )

        # ----------------------------------------------------
        # TOTAL DEDUCTIONS
        # ----------------------------------------------------

        self.total_deductions = money(
            money(
                deductions.get(
                    "total",
                    MONEY_ZERO,
                )
            )
            + money(
                statutory.get(
                    "employee_ssnit",
                    MONEY_ZERO,
                )
            )
            + money(
                statutory.get(
                    "paye",
                    MONEY_ZERO,
                )
            )
        )

        # ----------------------------------------------------
        # NET PAY
        # ----------------------------------------------------

        self.net_pay = money(
            self.gross_pay
            - self.total_deductions
        )

        if self.net_pay < MONEY_ZERO:
            self.net_pay = MONEY_ZERO

    # ========================================================
    # EARNINGS SNAPSHOT
    # ========================================================

    def earnings_snapshot(self):

        earnings = {
            "Basic Salary": str(
                self.basic_salary
            ),
        }

        for item in self.allowances.get(
            "items",
            [],
        ):

            earnings[
                item["name"]
            ] = str(
                money(
                    item["amount"]
                )
            )

        # Add useful totals for the payslip
        earnings["Total Allowances"] = str(
            money(
                self.allowances.get(
                    "total",
                    MONEY_ZERO,
                )
            )
        )

        earnings["Gross Pay"] = str(
            self.gross_pay
        )

        return earnings

    # ========================================================
    # DEDUCTIONS SNAPSHOT
    # ========================================================

    def deductions_snapshot(self):

        deductions = {
            "SSNIT": str(
                money(
                    self.statutory.get(
                        "employee_ssnit",
                        MONEY_ZERO,
                    )
                )
            ),
            "PAYE": str(
                money(
                    self.statutory.get(
                        "paye",
                        MONEY_ZERO,
                    )
                )
            ),
        }

        for item in self.deductions.get(
            "items",
            [],
        ):

            deductions[
                item["name"]
            ] = str(
                money(
                    item["amount"]
                )
            )

        deductions["Total Deductions"] = str(
            self.total_deductions
        )

        return deductions

    # ========================================================
    # DICTIONARY
    # ========================================================

    def to_dict(self):

        return {
            "staff_id": str(
                self.staff.id
            ),

            "salary_structure_id": str(
                self.salary_structure.id
            ),

            "basic_salary": str(
                self.basic_salary
            ),

            "allowances": self.allowances,

            "deductions": self.deductions,

            "employee_ssnit": str(
                self.statutory[
                    "employee_ssnit"
                ]
            ),

            "employer_ssnit": str(
                self.statutory[
                    "employer_ssnit"
                ]
            ),

            "taxable_income": str(
                self.statutory[
                    "taxable_income"
                ]
            ),

            "chargeable_income": str(
                self.statutory[
                    "chargeable_income"
                ]
            ),

            "paye": str(
                self.statutory[
                    "paye"
                ]
            ),

            "gross_pay": str(
                self.gross_pay
            ),

            "total_deductions": str(
                self.total_deductions
            ),

            "net_pay": str(
                self.net_pay
            ),
        }


# ============================================================
# MAIN PAYROLL ENGINE
# ============================================================

class PayrollEngine:

    @classmethod
    def calculate_staff_payroll(
        cls,
        staff,
        payroll_date,
    ):

        if not staff:

            raise PayrollPreparationError(
                "Staff member is required."
            )

        # ====================================================
        # ONLY ACTIVE STAFF CAN RECEIVE SALARY
        # ====================================================

        if not staff.is_active:

            raise PayrollPreparationError(
                f"{SalaryStructureService._staff_name(staff)} "
                "is inactive and cannot be processed."
            )

        if not payroll_date:

            raise PayrollPreparationError(
                "Payroll date is required."
            )

        # ====================================================
        # SALARY
        # ====================================================

        salary_structure = (
            SalaryStructureService
            .get_effective_structure(
                staff=staff,
                effective_date=payroll_date,
            )
        )

        basic_salary = money(
            salary_structure.basic_salary
        )

        # ====================================================
        # ALLOWANCES
        # ====================================================

        allowances = (
            PayrollAllowanceService
            .calculate(
                staff=staff,
                basic_salary=basic_salary,
            )
        )

        # ====================================================
        # STATUTORY
        # ====================================================

        statutory = (
            GhanaStatutoryPayrollService
            .calculate(
                basic_salary=basic_salary,
                taxable_allowances=(
                    allowances[
                        "taxable_total"
                    ]
                ),
            )
        )

        # ====================================================
        # OTHER DEDUCTIONS
        # ====================================================

        deductions = (
            PayrollDeductionService
            .calculate(
                staff=staff,
                basic_salary=basic_salary,
            )
        )

        # ====================================================
        # FINAL RESULT
        # ====================================================

        return PayrollCalculationResult(
            staff=staff,
            salary_structure=salary_structure,
            basic_salary=basic_salary,
            allowances=allowances,
            deductions=deductions,
            statutory=statutory,
        )


# ============================================================
# SINGLE STAFF PAYROLL RUN
# ============================================================

class PayrollRunService:

    @classmethod
    @transaction.atomic
    def calculate_run(
        cls,
        payroll_period,
        staff,
        processed_by=None,
    ):

        if not payroll_period:

            raise PayrollPreparationError(
                "Payroll period is required."
            )

        if not staff:

            raise PayrollPreparationError(
                "Staff member is required."
            )

        # ====================================================
        # ACTIVE STAFF ONLY
        # ====================================================

        if not staff.is_active:

            raise PayrollPreparationError(
                f"{SalaryStructureService._staff_name(staff)} "
                "is inactive and cannot be processed."
            )

        # ====================================================
        # PERIOD STATUS
        # ====================================================

        if payroll_period.status in (
            "CLOSED",
            "APPROVED",
        ):

            raise PayrollPreparationError(
                "This payroll period is locked "
                "and cannot be recalculated."
            )

        # ====================================================
        # SCHOOL VALIDATION
        # ====================================================

        if payroll_period.school_id != staff.school_id:

            raise PayrollPreparationError(
                "Staff member does not belong "
                "to this school."
            )

        # ====================================================
        # CALCULATE
        # ====================================================

        result = (
            PayrollEngine
            .calculate_staff_payroll(
                staff=staff,
                payroll_date=(
                    payroll_period.payment_date
                ),
            )
        )

        # ====================================================
        # SAVE PAYROLL RUN
        # ====================================================

        payroll_run, created = (
            PayrollRun.objects
            .update_or_create(
                school=payroll_period.school,
                staff=staff,
                payroll_period=payroll_period,
                defaults={
                    "basic_salary": (
                        result.basic_salary
                    ),

                    "total_allowances": (
                        result.allowances[
                            "total"
                        ]
                    ),

                    "total_deductions": (
                        result.total_deductions
                    ),

                    "gross_pay": (
                        result.gross_pay
                    ),

                    "net_pay": (
                        result.net_pay
                    ),

                    "status": "CALCULATED",

                    "processed_by": (
                        processed_by
                    ),

                    "processed_at": (
                        timezone.now()
                    ),
                },
            )
        )

        return payroll_run, result


# ============================================================
# BACKWARD-COMPATIBLE CALCULATE FUNCTION
# ============================================================

def calculate_staff_payroll(
    staff,
    payroll_period=None,
    payroll_date=None,
):
    """
    Backward-compatible helper.

    Supports both:

        calculate_staff_payroll(
            staff=staff,
            payroll_period=period,
        )

    and:

        calculate_staff_payroll(
            staff=staff,
            payroll_date=date,
        )
    """

    if payroll_date is None:

        if payroll_period is None:

            raise PayrollPreparationError(
                "Payroll period or payroll date is required."
            )

        payroll_date = (
            payroll_period.payment_date
        )

    return (
        PayrollEngine
        .calculate_staff_payroll(
            staff=staff,
            payroll_date=payroll_date,
        )
    )


# ============================================================
# PREPARE COMPLETE PAYROLL
# ============================================================

def prepare_payroll(
    period=None,
    payroll_period=None,
    processed_by=None,
):

    if payroll_period is None:
        payroll_period = period

    if payroll_period is None:

        raise PayrollPreparationError(
            "Payroll period is required."
        )

    if not isinstance(
        payroll_period,
        PayrollPeriod,
    ):

        raise PayrollPreparationError(
            "Invalid payroll period supplied."
        )

    # ========================================================
    # PERIOD STATUS
    # ========================================================

    if payroll_period.status in (
        "CLOSED",
        "APPROVED",
    ):

        raise PayrollPreparationError(
            "This payroll period is locked and "
            "cannot be processed."
        )

    if not payroll_period.payment_date:

        raise PayrollPreparationError(
            f"{payroll_period.name} does not have "
            "a payment date."
        )

    # ========================================================
    # ACTIVE STAFF ONLY
    # ========================================================

    staff_queryset = (
        StaffProfile.objects
        .filter(
            school=payroll_period.school,
            is_active=True,
        )
        .select_related(
            "user",
            "staff_grade",
            "department",
        )
        .order_by(
            "user__last_name",
            "user__first_name",
        )
    )

    staff_members = list(
        staff_queryset
    )

    if not staff_members:

        raise PayrollPreparationError(
            "No active staff members were found "
            f"for {payroll_period.school}."
        )

    prepared = []
    skipped = []
    failed = []

    # ========================================================
    # PROCESS EVERYTHING IN ONE TRANSACTION
    # ========================================================

    try:

        with transaction.atomic():

            payroll_period.status = "PROCESSING"

            payroll_period.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            for staff in staff_members:

                try:

                    payroll_run, result = (
                        PayrollRunService
                        .calculate_run(
                            payroll_period=(
                                payroll_period
                            ),
                            staff=staff,
                            processed_by=(
                                processed_by
                            ),
                        )
                    )

                    staff_name = (
                        staff.user
                        .get_full_name()
                        .strip()
                        or staff.user.username
                    )

                    prepared.append(
                        {
                            "staff_id": str(
                                staff.id
                            ),

                            "staff_number": (
                                staff.staff_id
                                or ""
                            ),

                            "staff_name": staff_name,

                            "payroll_run_id": str(
                                payroll_run.id
                            ),

                            "created": bool(
                                payroll_run
                            ),

                            "basic_salary": str(
                                result.basic_salary
                            ),

                            # IMPORTANT:
                            # Return allowance total here too.
                            "total_allowances": str(
                                result.allowances[
                                    "total"
                                ]
                            ),

                            "allowances": (
                                result.allowances
                            ),

                            "gross_pay": str(
                                result.gross_pay
                            ),

                            "total_deductions": str(
                                result.total_deductions
                            ),

                            "net_pay": str(
                                result.net_pay
                            ),
                        }
                    )

                except PayrollPreparationError as exc:

                    failed.append(
                        {
                            "staff_id": str(
                                staff.id
                            ),

                            "staff_number": (
                                staff.staff_id
                                or ""
                            ),

                            "staff_name": (
                                staff.user
                                .get_full_name()
                                .strip()
                                or staff.user.username
                            ),

                            "error": str(exc),
                        }
                    )

                except ValidationError as exc:

                    failed.append(
                        {
                            "staff_id": str(
                                staff.id
                            ),

                            "staff_number": (
                                staff.staff_id
                                or ""
                            ),

                            "staff_name": (
                                staff.user
                                .get_full_name()
                                .strip()
                                or staff.user.username
                            ),

                            "error": str(exc),
                        }
                    )

                except Exception as exc:

                    failed.append(
                        {
                            "staff_id": str(
                                staff.id
                            ),

                            "staff_number": (
                                staff.staff_id
                                or ""
                            ),

                            "staff_name": (
                                staff.user
                                .get_full_name()
                                .strip()
                                or staff.user.username
                            ),

                            "error": (
                                "Unexpected payroll "
                                "calculation error: "
                                f"{exc}"
                            ),
                        }
                    )

            # =================================================
            # DO NOT COMMIT PARTIAL PAYROLL
            # =================================================

            if failed:

                raise PayrollPreparationError(
                    _build_preparation_failure_message(
                        payroll_period,
                        failed,
                    )
                )

            # =================================================
            # SUCCESS
            # =================================================

            payroll_period.status = "OPEN"

            payroll_period.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

    except PayrollPreparationError:

        raise

    except Exception as exc:

        raise PayrollPreparationError(
            "Payroll preparation failed: "
            f"{exc}"
        ) from exc

    # ========================================================
    # SUMMARY
    # ========================================================

    total_basic = MONEY_ZERO
    total_allowances = MONEY_ZERO
    total_gross = MONEY_ZERO
    total_deductions = MONEY_ZERO
    total_net = MONEY_ZERO

    for item in prepared:

        total_basic += money(
            item["basic_salary"]
        )

        total_allowances += money(
            item["total_allowances"]
        )

        total_gross += money(
            item["gross_pay"]
        )

        total_deductions += money(
            item["total_deductions"]
        )

        total_net += money(
            item["net_pay"]
        )

    return {
        "success": True,

        "period_id": str(
            payroll_period.id
        ),

        "period_name": (
            payroll_period.name
        ),

        "status": (
            payroll_period.status
        ),

        "payment_date": (
            payroll_period.payment_date.isoformat()
            if payroll_period.payment_date
            else None
        ),

        "staff_count": len(
            prepared
        ),

        "prepared_count": len(
            prepared
        ),

        "skipped_count": len(
            skipped
        ),

        "failed_count": len(
            failed
        ),

        "prepared": prepared,

        "skipped": skipped,

        "failed": failed,

        "summary": {
            "basic_salary": str(
                money(total_basic)
            ),

            "total_allowances": str(
                money(total_allowances)
            ),

            "gross_pay": str(
                money(total_gross)
            ),

            "total_deductions": str(
                money(total_deductions)
            ),

            "net_pay": str(
                money(total_net)
            ),
        },
    }


# ============================================================
# PREPARATION FAILURE MESSAGE
# ============================================================

def _build_preparation_failure_message(
    payroll_period,
    failures,
):

    lines = [
        f"Payroll preparation failed for "
        f"{payroll_period.name}.",
        "",
        "The following staff members could not be "
        "processed:",
        "",
    ]

    for failure in failures:

        name = (
            failure.get(
                "staff_name"
            )
            or "Unknown staff"
        )

        staff_number = (
            failure.get(
                "staff_number"
            )
            or "-"
        )

        error = (
            failure.get(
                "error"
            )
            or "Unknown payroll error."
        )

        lines.append(
            f"- {name} ({staff_number}): {error}"
        )

    lines.extend(
        [
            "",
            "No payroll changes were committed.",
            "Please correct the affected staff "
            "salary structure(s) and run payroll again.",
        ]
    )

    return "\n".join(lines)


# ============================================================
# PAYSLIP SERVICE
# ============================================================

class PayslipService:

    @classmethod
    @transaction.atomic
    def generate(
        cls,
        payroll_run,
        generated_by=None,
    ):

        if not payroll_run:

            raise ValidationError(
                "Payroll run is required."
            )

        # ====================================================
        # ACTIVE STAFF ONLY
        # ====================================================

        if not payroll_run.staff.is_active:

            raise ValidationError(
                f"{SalaryStructureService._staff_name(payroll_run.staff)} "
                "is inactive and cannot have a payslip generated."
            )

        # ====================================================
        # PAYROLL STATUS
        # ====================================================

        if payroll_run.status not in (
            "CALCULATED",
            "REVIEWED",
            "APPROVED",
            "PAID",
        ):

            raise ValidationError(
                "Payroll must be calculated before "
                "generating a payslip."
            )

        # ====================================================
        # RECALCULATE FROM THE SAME PAYROLL ENGINE
        # ====================================================

        result = (
            PayrollEngine
            .calculate_staff_payroll(
                staff=payroll_run.staff,
                payroll_date=(
                    payroll_run
                    .payroll_period
                    .payment_date
                ),
            )
        )

        # ====================================================
        # UPDATE PAYROLL RUN
        # ====================================================

        payroll_run.basic_salary = (
            result.basic_salary
        )

        payroll_run.total_allowances = (
            result.allowances[
                "total"
            ]
        )

        payroll_run.total_deductions = (
            result.total_deductions
        )

        payroll_run.gross_pay = (
            result.gross_pay
        )

        payroll_run.net_pay = (
            result.net_pay
        )

        payroll_run.save(
            update_fields=[
                "basic_salary",
                "total_allowances",
                "total_deductions",
                "gross_pay",
                "net_pay",
            ]
        )

        # ====================================================
        # CREATE / UPDATE PAYSLIP
        # ====================================================

        payslip, created = (
            Payslip.objects
            .update_or_create(
                payroll_run=payroll_run,
                defaults={
                    "school": (
                        payroll_run.school
                    ),

                    "earnings": (
                        result
                        .earnings_snapshot()
                    ),

                    "deductions": (
                        result
                        .deductions_snapshot()
                    ),

                    "generated_by": (
                        generated_by
                    ),
                },
            )
        )

        return payslip