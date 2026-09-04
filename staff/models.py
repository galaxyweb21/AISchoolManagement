# staff/models.py
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from school.models import School
from school.services import managers
import uuid
from django.utils.crypto import get_random_string
from datetime import timedelta, date

# ============================================================
# DEPARTMENT MODEL
# ============================================================

class Department(models.Model):
    """
    Department model for staff organization.
    e.g., Mathematics Department, English Department, Administration, etc.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='departments')

    name = models.CharField(max_length=100, help_text="Department name (e.g., Mathematics Department)")
    code = models.CharField(max_length=20, unique=True, help_text="Department code (e.g., MATH, ENG, ADMIN)")
    description = models.TextField(blank=True, null=True)

    # HOD (Head of Department) - optional
    hod = models.OneToOneField(
        'StaffProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='hod_department',
        help_text="Head of Department (must be a staff member)"
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['name']
        unique_together = ['school', 'code']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        if not self.code:
            words = self.name.split()
            if len(words) >= 2:
                code = ''.join(word[:2].upper() for word in words[:2])
            else:
                code = self.name[:4].upper()
            base_code = code
            counter = 1
            while Department.objects.filter(school=self.school, code=code).exclude(id=self.id).exists():
                code = f"{base_code}{counter}"
                counter += 1
            self.code = code
        super().save(*args, **kwargs)


# ============================================================
# STAFF GRADE MODEL
# ============================================================

# staff/models.py - Update the StaffGrade __str__ method

class StaffGrade(models.Model):
    """
    Staff grade / level used for salary structure, benefits and
    grade-based HR policies.

    Examples:
        Grade 1
        Grade 2
        Senior Teacher
        Head Teacher
        Administrative Officer

    IMPORTANT:
    The legacy annual_leave_days and sick_leave_days fields are
    intentionally retained for backward compatibility.

    New leave configuration should preferably use:
        StaffGradeLeavePolicy
    """

    GRADE_TYPES = (
        ('TEACHING', 'Teaching Staff'),
        ('NON_TEACHING', 'Non-Teaching Staff'),
        ('ADMINISTRATIVE', 'Administrative Staff'),
        ('SUPPORT', 'Support Staff'),
    )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='staff_grades'
    )

    name = models.CharField(
        max_length=50,
        help_text="Grade name (e.g., 'Grade 1', 'Senior Teacher')"
    )

    code = models.CharField(
        max_length=10,
        unique=True,
        help_text="Grade code (e.g., 'G1', 'ST')"
    )

    grade_type = models.CharField(
        max_length=20,
        choices=GRADE_TYPES,
        default='TEACHING'
    )

    level = models.PositiveIntegerField(
        help_text="Numeric level used for ordering"
    )

    # Salary
    base_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[
            MinValueValidator(Decimal('0.00'))
        ],
        help_text="Base monthly salary for this grade"
    )

    # Legacy leave fields - DO NOT REMOVE
    annual_leave_days = models.PositiveIntegerField(
        default=21,
        help_text="Legacy annual leave entitlement. New configurations should use StaffGradeLeavePolicy."
    )

    sick_leave_days = models.PositiveIntegerField(
        default=10,
        help_text="Legacy sick leave entitlement. New configurations should use StaffGradeLeavePolicy."
    )

    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['level']
        unique_together = ['school', 'code']

    def __str__(self):
        """
        Display grade with name, level, and code for better context.
        Example: "Senior Teacher (Level 5) - ST"
        """
        return f"{self.name} (Level {self.level}) - {self.code}"

    def save(self, *args, **kwargs):
        if not self.code:
            prefix = 'GT'
            count = StaffGrade.objects.filter(school=self.school).count() + 1
            self.code = f"{prefix}-{count:03d}"
        super().save(*args, **kwargs)

    def get_base_salary(self):
        return self.base_salary or Decimal('0.00')

    def get_annual_leave_days(self):
        return self.annual_leave_days or 0

    def get_sick_leave_days(self):
        return self.sick_leave_days or 0

    def get_display_name(self):
        """
        Helper method to get a formatted display name.
        """
        return f"{self.name} (Level {self.level})"

    def get_full_display(self):
        """
        Helper method to get the full formatted display.
        """
        return f"{self.name} (Level {self.level}) - {self.code}"

    def get_short_display(self):
        """
        Helper method to get a compact display.
        """
        return f"{self.name} (L{self.level})"


# ============================================================
# STAFF PROFILE MODEL
# ============================================================

class StaffProfile(models.Model):
    """
    Extended staff profile.

    StaffProfile represents the employee and connects the employee to:
        School, User account, Staff position, Department, Staff grade,
        Employment information, HR / Payroll, Leave management
    """

    STAFF_POSITION_CHOICES = (
        ('SCHOOL_ADMIN', 'School Administrator'),
        ('BURSAR', 'Bursar / Finance Officer'),
        ('REGISTRAR', 'Registrar / Admissions'),
        ('HOD', 'Head of Department'),
        ('SECRETARY', 'Administrative Secretary'),
        ('TEACHER', 'Teacher'),
        ('IT_SUPPORT', 'IT & Support Staff'),
        ('LIBRARIAN', 'Librarian'),
    )

    EMPLOYMENT_TYPE_CHOICES = (
        ('PERMANENT', 'Permanent'),
        ('CONTRACT', 'Contract'),
        ('TEMPORARY', 'Temporary'),
        ('PART_TIME', 'Part-Time'),
        ('INTERN', 'Intern'),
    )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    # School
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='staff_profiles'
    )

    # User Account
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={
            'role__in': [
                choice[0] for choice in STAFF_POSITION_CHOICES
            ] + ['SUPER_ADMIN', 'SCHOOL_ADMIN']
        },
        related_name='staff_profile',
    )

    # Position
    staff_position = models.CharField(
        max_length=30,
        choices=STAFF_POSITION_CHOICES,
        default='TEACHER'
    )

    # Staff Grade
    staff_grade = models.ForeignKey(
        StaffGrade,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_members',
        help_text="Staff grade determines the employee's salary structure and grade-based HR policies."
    )

    # Department
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_members',
        help_text="The department this staff member belongs to."
    )

    # Staff ID
    staff_id = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique identifier for the staff member"
    )

    # Employment
    employment_type = models.CharField(
        max_length=20,
        choices=EMPLOYMENT_TYPE_CHOICES,
        default='PERMANENT'
    )

    employment_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the staff member was employed"
    )

    termination_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the staff member left (if applicable)"
    )

    termination_reason = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Reason for termination (Resignation, Retirement, Dismissal, etc.)"
    )

    # Profile Picture
    profile_picture = models.ImageField(
        upload_to='staff_profiles/',
        blank=True,
        null=True,
        help_text="Upload a professional headshot (JPEG/PNG)."
    )

    # Password Change Tracking
    default_password = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="The default password assigned when account was created"
    )

    has_changed_password = models.BooleanField(
        default=False,
        help_text="Whether the staff member has changed their default password"
    )

    password_changed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the password was last changed"
    )

    # Dates / Status
    date_joined = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    objects = managers.TenantManager()

    # ==========================================================
    # DISPLAY
    # ==========================================================

    def get_staff_position_display(self):
        return dict(self.STAFF_POSITION_CHOICES).get(self.staff_position, self.staff_position)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.staff_id})"

    # ==========================================================
    # SALARY
    # ==========================================================

    def get_grade_salary(self):
        """
        LEGACY COMPATIBILITY METHOD.

        This method is intentionally retained so older parts of the
        application do not crash.

        IMPORTANT:
        ----------
        Payroll must NOT use this method.

        Payroll must use:
            get_effective_salary_structure()
        """

        if self.staff_grade_id:
            try:
                return self.staff_grade.base_salary or Decimal("0.00")
            except Exception:
                pass

        return Decimal("0.00")

    # ==========================================================
    # LEAVE POLICY
    # ==========================================================

    def get_leave_policy(self, leave_type):
        if not self.staff_grade_id or not leave_type:
            return None
        return StaffGradeLeavePolicy.objects.filter(
            school=self.school,
            staff_grade_id=self.staff_grade_id,
            leave_type=leave_type,
            is_active=True,
        ).select_related('staff_grade', 'leave_type').first()

    def get_leave_entitlement(self, leave_type):
        if not leave_type:
            return Decimal('0.0')

        # 1. Grade-specific policy
        policy = self.get_leave_policy(leave_type)
        if policy:
            return policy.get_entitlement()

        # 2. LeaveType default
        default_days = getattr(leave_type, 'default_days', None)
        if default_days is not None:
            return Decimal(str(default_days))

        # 3. Legacy StaffGrade values
        category = getattr(leave_type, 'category', None)
        if category == 'ANNUAL':
            return Decimal(str(self.get_annual_leave_days()))
        if category == 'SICK':
            return Decimal(str(self.get_sick_leave_days()))

        # 4. Nothing configured
        return Decimal('0.0')

    def get_annual_leave_days(self):
        if not self.staff_grade:
            return 21
        return self.staff_grade.annual_leave_days or 0

    def get_sick_leave_days(self):
        if not self.staff_grade:
            return 10
        return self.staff_grade.sick_leave_days or 0


# ============================================================
# HR / PAYROLL MODELS
# ============================================================

class SalaryStructure(models.Model):
    """
    Employee compensation record.

    IMPORTANT:
    ----------
    This model is the authoritative source for an employee's BASIC SALARY.

    StaffGrade describes the employee's HR classification.
    SalaryStructure describes what that specific employee is actually paid.

    StaffGrade.base_salary is intentionally NOT used by payroll anymore.
    It remains temporarily for backward compatibility and migration.
    """

    FREQUENCY_MONTHLY = "MONTHLY"
    FREQUENCY_WEEKLY = "WEEKLY"
    FREQUENCY_DAILY = "DAILY"
    FREQUENCY_ANNUAL = "ANNUAL"

    FREQUENCY_CHOICES = (
        (FREQUENCY_MONTHLY, "Monthly"),
        (FREQUENCY_WEEKLY, "Weekly"),
        (FREQUENCY_DAILY, "Daily"),
        (FREQUENCY_ANNUAL, "Annual"),
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="salary_structures",
    )

    # ---------------------------------------------------------
    # AUTHORITATIVE EMPLOYEE RELATIONSHIP
    # ---------------------------------------------------------
    staff = models.ForeignKey(
        "StaffProfile",
        on_delete=models.PROTECT,
        null=False,
        blank=False,
        related_name="salary_structures",
        help_text="The staff member whose actual salary this structure defines.",
    )

    # ---------------------------------------------------------
    # RETAINED FOR COMPATIBILITY / HR CLASSIFICATION
    # ---------------------------------------------------------
    staff_grade = models.ForeignKey(
        "StaffGrade",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="salary_structures",
        help_text=(
            "The staff grade associated with this salary record. "
            "This is classification information, not the payroll salary source."
        ),
    )

    basic_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default=FREQUENCY_MONTHLY,
    )

    # ---------------------------------------------------------
    # EFFECTIVE-DATED COMPENSATION
    # ---------------------------------------------------------
    #
    # effective_date is retained because the existing application
    # already uses this field.
    #
    # We treat effective_date as "effective from".
    #
    effective_date = models.DateField(
        help_text="Date from which this salary becomes effective.",
    )

    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Last date on which this salary is effective. "
            "Leave blank for an open-ended/current salary."
        ),
    )

    is_active = models.BooleanField(
        default=True,
    )

    # ---------------------------------------------------------
    # AUDIT
    # ---------------------------------------------------------
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-effective_date",
            "-created_at",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "staff",
                    "effective_date",
                ],
                name="unique_staff_salary_effective_date",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(basic_salary__gte=0)
                ),
                name="salary_structure_basic_salary_non_negative",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(effective_to__isnull=True)
                    |
                    models.Q(effective_to__gte=models.F("effective_date"))
                ),
                name="salary_structure_valid_date_range",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "school",
                    "staff",
                    "effective_date",
                ],
                name="salary_staff_effective_idx",
            ),
            models.Index(
                fields=[
                    "school",
                    "staff_grade",
                    "effective_date",
                ],
                name="salary_grade_effective_idx",
            ),
            models.Index(
                fields=[
                    "school",
                    "is_active",
                    "effective_date",
                ],
                name="salary_active_effective_idx",
            ),
        ]

    def __str__(self):
        staff_name = "Unassigned Staff"

        if self.staff_id:
            try:
                staff_name = str(self.staff)
            except Exception:
                staff_name = "Staff"

        return (
            f"{staff_name} - "
            f"{self.basic_salary} "
            f"({self.frequency}) "
            f"from {self.effective_date}"
        )

    @property
    def effective_from(self):
        """
        Compatibility-friendly alias.

        The database field remains effective_date so existing code
        does not immediately break.
        """
        return self.effective_date

    @property
    def salary(self):
        """
        Readable alias for the authoritative basic salary.
        """
        return self.basic_salary

    def clean(self):

        from django.core.exceptions import ValidationError

        super().clean()

        # ---------------------------------------------------------
        # BASIC SALARY
        # ---------------------------------------------------------

        if self.basic_salary is None:
            raise ValidationError({
                "basic_salary": (
                    "Basic salary is required."
                )
            })

        if self.basic_salary < Decimal("0.00"):
            raise ValidationError({
                "basic_salary": (
                    "Basic salary cannot be negative."
                )
            })

        # ---------------------------------------------------------
        # EFFECTIVE DATE RANGE
        # ---------------------------------------------------------

        if (
                self.effective_to
                and self.effective_to < self.effective_date
        ):
            raise ValidationError({
                "effective_to": (
                    "Effective-to date cannot be earlier "
                    "than the effective-from date."
                )
            })

        # ---------------------------------------------------------
        # STAFF IS REQUIRED FOR NEW PAYROLL RECORDS
        # ---------------------------------------------------------

        if not self.staff_id:
            raise ValidationError({
                "staff": (
                    "A staff member must be selected."
                )
            })

        # ---------------------------------------------------------
        # PREVENT OVERLAPPING SALARY PERIODS
        # ---------------------------------------------------------

        new_start = self.effective_date

        new_end = (
            self.effective_to
            if self.effective_to
            else date.max
        )

        overlap_query = (
            SalaryStructure.objects
                .filter(
                staff_id=self.staff_id,
                effective_date__lte=new_end,
            )
                .filter(
                models.Q(
                    effective_to__isnull=True
                )
                |
                models.Q(
                    effective_to__gte=new_start
                )
            )
        )

        if self.pk:
            overlap_query = (
                overlap_query
                    .exclude(
                    pk=self.pk
                )
            )

        if overlap_query.exists():
            raise ValidationError({
                "effective_date": (
                    "This staff member already has a salary "
                    "structure covering part of this effective period."
                )
            })

    def save(self, *args, **kwargs):
        """
        Validate salary structures before saving.

        Existing code that calls save() continues to work.
        """

        self.full_clean()
        return super().save(*args, **kwargs)


class Allowance(models.Model):
    ALLOWANCE_TYPE_CHOICES = (
        ('HOUSING', 'Housing Allowance'),
        ('TRANSPORT', 'Transport Allowance'),
        ('RESPONSIBILITY', 'Responsibility Allowance'),
        ('LEAVE', 'Leave Allowance'),
        ('SPECIAL', 'Special Allowance'),
        ('OTHER', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='allowances')

    name = models.CharField(max_length=100)
    allowance_type = models.CharField(max_length=20, choices=ALLOWANCE_TYPE_CHOICES, default='OTHER')
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    is_percentage = models.BooleanField(
        default=False,
        help_text="If True, amount is a percentage of basic salary"
    )
    taxable = models.BooleanField(default=True, help_text="Is this allowance taxable?")
    description = models.TextField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    def __str__(self):
        return f"{self.name} ({self.amount})"


class Deduction(models.Model):
    DEDUCTION_TYPE_CHOICES = (
        ('PAYE', 'Income Tax (PAYE)'),
        ('SSNIT', 'SSNIT Pension'),
        ('WELFARE', 'Staff Welfare'),
        ('LOAN', 'Loan Repayment'),
        ('UNION', 'Union Dues'),
        ('OTHER', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='deductions')

    name = models.CharField(max_length=100)
    deduction_type = models.CharField(max_length=20, choices=DEDUCTION_TYPE_CHOICES, default='OTHER')
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    is_percentage = models.BooleanField(
        default=False,
        help_text="If True, amount is a percentage of basic salary"
    )
    is_mandatory = models.BooleanField(
        default=True,
        help_text="Is this deduction mandatory for all staff?"
    )
    description = models.TextField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    def __str__(self):
        return f"{self.name} ({self.amount})"


class StaffAllowance(models.Model):
    """
    Assigns an Allowance to an individual staff member.

    The amount field is an optional staff-specific override.

    Example:

        Allowance:
            Transport Allowance = 500.00

        StaffAllowance:
            amount = None

        Result:
            Staff receives 500.00

    If:

        StaffAllowance:
            amount = 750.00

        Result:
            Staff receives 750.00
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="staff_allowances",
    )

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="allowances",
    )

    allowance = models.ForeignKey(
        Allowance,
        on_delete=models.CASCADE,
        related_name="staff_allowances",
    )

    # ---------------------------------------------------------
    # OPTIONAL STAFF-SPECIFIC OVERRIDE
    # ---------------------------------------------------------

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(
                Decimal("0.00")
            )
        ],
        help_text=(
            "Optional staff-specific amount. "
            "Leave blank to use the allowance default amount."
        ),
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    objects = managers.TenantManager()

    class Meta:
        ordering = [
            "staff__user__last_name",
            "staff__user__first_name",
            "allowance__name",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "staff",
                    "allowance",
                ],
                name="unique_staff_allowance",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "school",
                    "staff",
                    "is_active",
                ],
                name="staff_allowance_active_idx",
            ),
            models.Index(
                fields=[
                    "school",
                    "allowance",
                    "is_active",
                ],
                name="allowance_staff_active_idx",
            ),
        ]

    def clean(self):
        """
        Ensure the staff and allowance belong to the
        same school as this assignment.
        """

        errors = {}

        if self.staff_id:
            staff_school_id = getattr(
                self.staff,
                "school_id",
                None,
            )

            if (
                self.school_id
                and staff_school_id
                and staff_school_id != self.school_id
            ):
                errors["staff"] = (
                    "The selected staff member does not "
                    "belong to this school."
                )

        if self.allowance_id:
            allowance_school_id = getattr(
                self.allowance,
                "school_id",
                None,
            )

            if (
                self.school_id
                and allowance_school_id
                and allowance_school_id != self.school_id
            ):
                errors["allowance"] = (
                    "The selected allowance does not "
                    "belong to this school."
                )

        if self.amount is not None:
            if self.amount < Decimal("0.00"):
                errors["amount"] = (
                    "Staff allowance amount cannot be negative."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """
        Run model validation before saving.
        """

        self.full_clean()

        return super().save(
            *args,
            **kwargs,
        )

    def __str__(self):
        staff_name = (
            self.staff.user.get_full_name().strip()
            if self.staff_id and self.staff.user
            else str(self.staff_id)
        )

        allowance_name = (
            self.allowance.name
            if self.allowance_id
            else str(self.allowance_id)
        )

        return (
            f"{staff_name} - "
            f"{allowance_name}"
        )


class StaffDeduction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='staff_deductions')

    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='deductions')
    deduction = models.ForeignKey(Deduction, on_delete=models.CASCADE, related_name='staff_deductions')

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Custom amount for this staff member (overrides the default)"
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ['staff', 'deduction']

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.deduction.name}"


class PayrollPeriod(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('OPEN', 'Open'),
        ('PROCESSING', 'Processing'),
        ('CLOSED', 'Closed'),
        ('APPROVED', 'Approved'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='payroll_periods')

    name = models.CharField(max_length=100, help_text="e.g., 'January 2025 Payroll'")
    period_start = models.DateField()
    period_end = models.DateField()
    payment_date = models.DateField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_payroll_periods'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_payroll_periods'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-period_end']
        unique_together = ['school', 'period_start', 'period_end']

    def __str__(self):
        return f"{self.name} ({self.period_start} - {self.period_end})"


class PayrollRun(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('CALCULATED', 'Calculated'),
        ('REVIEWED', 'Reviewed'),
        ('APPROVED', 'Approved'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='payroll_runs')

    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='payroll_runs')
    payroll_period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name='payroll_runs')

    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_allowances = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    gross_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    days_worked = models.PositiveIntegerField(default=0)
    days_absent = models.PositiveIntegerField(default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_payroll'
    )
    processed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        unique_together = ['staff', 'payroll_period']

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.payroll_period.name}"


class Payslip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='payslips')

    payroll_run = models.OneToOneField(PayrollRun, on_delete=models.CASCADE, related_name='payslip')

    earnings = models.JSONField(
        default=dict,
        help_text="Breakdown of earnings: {'allowance_name': amount, ...}"
    )

    deductions = models.JSONField(
        default=dict,
        help_text="Breakdown of deductions: {'deduction_name': amount, ...}"
    )

    payment_method = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="e.g., Bank Transfer, Cash, Cheque"
    )
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)

    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='generated_payslips'
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    pdf_file = models.FileField(
        upload_to='payslips/',
        blank=True,
        null=True
    )

    is_printed = models.BooleanField(default=False)
    printed_at = models.DateTimeField(null=True, blank=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"Payslip - {self.payroll_run.staff.user.get_full_name()} ({self.payroll_run.payroll_period.name})"


# ============================================================
# STAFF LEAVE MODELS
# ============================================================

class LeaveType(models.Model):
    """
    Defines different types of leave available in the organization.
    """
    LEAVE_CATEGORIES = (
        ('ANNUAL', 'Annual Leave'),
        ('SICK', 'Sick Leave'),
        ('MATERNITY', 'Maternity Leave'),
        ('PATERNITY', 'Paternity Leave'),
        ('CASUAL', 'Casual Leave'),
        ('STUDY', 'Study Leave'),
        ('COMPASSIONATE', 'Compassionate Leave'),
        ('UNPAID', 'Unpaid Leave'),
        ('OTHER', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='leave_types')

    name = models.CharField(max_length=50, help_text="Leave type name (e.g., Annual Leave)")
    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        help_text="Leave type code (e.g., AL, SL) - auto-generated if left blank"
    )
    category = models.CharField(max_length=20, choices=LEAVE_CATEGORIES, default='ANNUAL')

    # Default entitlement
    default_days = models.PositiveIntegerField(
        default=21,
        help_text="Default number of days entitled per year"
    )

    # Carry over settings
    allow_carryover = models.BooleanField(
        default=True,
        help_text="Can unused days be carried over to the next year?"
    )
    max_carryover_days = models.PositiveIntegerField(
        default=30,
        help_text="Maximum days that can be carried over"
    )

    # Approval settings
    requires_approval = models.BooleanField(
        default=True,
        help_text="Does this leave type require approval?"
    )
    requires_documentation = models.BooleanField(
        default=False,
        help_text="Does this leave type require supporting documentation?"
    )

    # Description and status
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['category', 'name']
        unique_together = ['school', 'code']

    def save(self, *args, **kwargs):
        if not self.code:
            words = self.name.split()
            if len(words) >= 2:
                code = ''.join(word[:2].upper() for word in words[:2])
            else:
                code = self.name[:4].upper()
            base_code = code
            counter = 1
            while LeaveType.objects.filter(school=self.school, code=code).exclude(id=self.id).exists():
                code = f"{base_code}{counter}"
                counter += 1
            self.code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


# ============================================================
# STAFF GRADE LEAVE POLICY
# ============================================================

class StaffGradeLeavePolicy(models.Model):
    """
    Defines leave entitlement for a specific StaffGrade and LeaveType.

    Example:
        Teacher Grade 1 + Annual Leave = 21 days
        Teacher Grade 1 + Sick Leave = 10 days
        Senior Teacher + Annual Leave = 30 days

    This model is the preferred source of truth for grade-based
    leave entitlement.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='staff_grade_leave_policies'
    )

    staff_grade = models.ForeignKey(
        StaffGrade,
        on_delete=models.CASCADE,
        related_name='leave_policies'
    )

    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name='grade_policies'
    )

    # Entitlement
    entitlement_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal('0.0'),
        validators=[
            MinValueValidator(Decimal('0.0'))
        ],
        help_text="Number of leave days this staff grade is entitled to"
    )

    # Payment
    is_paid = models.BooleanField(
        default=True,
        help_text="Whether this leave is paid"
    )

    # Carryover
    allow_carryover = models.BooleanField(
        default=False,
        help_text="Whether unused leave may be carried forward"
    )
    max_carryover_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal('0.0'),
        validators=[
            MinValueValidator(Decimal('0.0'))
        ],
        help_text="Maximum number of days that can be carried forward"
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['staff_grade__level', 'leave_type__name']
        constraints = [
            models.UniqueConstraint(
                fields=['staff_grade', 'leave_type'],
                name='unique_staff_grade_leave_type'
            )
        ]

    def __str__(self):
        return f"{self.staff_grade.name} - {self.leave_type.name}: {self.entitlement_days} days"

    def get_entitlement(self):
        return self.entitlement_days or Decimal('0.0')

    def get_carryover_days(self):
        if not self.allow_carryover:
            return Decimal('0.0')
        return self.max_carryover_days or Decimal('0.0')

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}

        if self.max_carryover_days and not self.allow_carryover:
            errors['max_carryover_days'] = (
                "Maximum carryover days cannot be greater than zero when carryover is disabled."
            )

        if self.allow_carryover and self.max_carryover_days > self.entitlement_days:
            errors['max_carryover_days'] = (
                "Maximum carryover days cannot exceed the leave entitlement."
            )

        if self.staff_grade_id and self.school_id and self.staff_grade.school_id != self.school_id:
            errors['staff_grade'] = "The selected staff grade must belong to the selected school."

        if self.leave_type_id and self.school_id and self.leave_type.school_id != self.school_id:
            errors['leave_type'] = "The selected leave type must belong to the selected school."

        if errors:
            raise ValidationError(errors)


class StaffLeaveBalance(models.Model):
    """
    Tracks leave entitlement and usage for a staff member within a leave period.
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="staff_leave_balances",
    )

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name="leave_balances",
    )

    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.CASCADE,
        related_name="staff_balances",
    )

    period_start = models.DateField()
    period_end = models.DateField()

    total_entitled = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    carried_over = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    used = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    pending = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    remaining = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("0.0"),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ["staff__user__last_name", "leave_type__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "leave_type", "period_start", "period_end"],
                name="unique_staff_leave_balance_period"
            )
        ]

    def calculate_remaining(self):
        entitlement = Decimal(self.total_entitled or 0)
        carry = Decimal(self.carried_over or 0)
        used = Decimal(self.used or 0)
        pending = Decimal(self.pending or 0)

        remaining = entitlement + carry - used - pending
        self.remaining = max(Decimal("0.0"), remaining)
        return self.remaining

    @property
    def available_days(self):
        return self.remaining

    @property
    def consumed_days(self):
        return Decimal(self.used or 0) + Decimal(self.pending or 0)

    def __str__(self):
        return f"{self.staff} - {self.leave_type.name} - {self.period_start.year}"


class LeaveRequest(models.Model):
    """
    Staff leave request with full approval workflow.

    Lifecycle:
        DRAFT → PENDING → APPROVED → TAKEN
                     ├── REJECTED
                     └── CANCELLED

    Balance changes are delegated to leave_service.py.
    Attendance changes are delegated to leave_service.sync_attendance().
    """

    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
        ('TAKEN', 'Taken'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='leave_requests')
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='leave_requests')

    # Dates
    start_date = models.DateField()
    end_date = models.DateField()
    requested_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=0,
        help_text="Number of working days requested"
    )

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    # Reason and details
    reason = models.TextField(help_text="Reason for leave")
    notes = models.TextField(blank=True, null=True, help_text="Additional notes")

    # Supporting documents
    supporting_document = models.FileField(
        upload_to='leave_documents/',
        blank=True,
        null=True,
        help_text="Supporting documentation if required"
    )

    # Contact information
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    emergency_contact = models.CharField(max_length=100, blank=True, null=True)
    emergency_phone = models.CharField(max_length=20, blank=True, null=True)

    # Replacement/Backup
    replacement_staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replacements',
        help_text="Staff member who will cover during leave"
    )

    # Approval workflow
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_leave_requests'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.TextField(blank=True, null=True)

    # Rejection
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='rejected_leave_requests'
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)

    # Cancellation
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_leave_requests'
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, null=True)

    # Attendance sync
    attendance_synced = models.BooleanField(
        default=False,
        help_text="Whether attendance has been updated for this leave"
    )
    attendance_synced_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['staff', 'status']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.leave_type.name} ({self.get_status_display()})"

    def calculate_working_days(self):
        """Calculate Monday-Friday working days between start and end dates."""
        if not self.start_date or not self.end_date:
            return Decimal("0.0")
        if self.end_date < self.start_date:
            return Decimal("0.0")

        current = self.start_date
        count = 0
        while current <= self.end_date:
            if current.weekday() < 5:
                count += 1
            current += timedelta(days=1)
        return Decimal(str(count))

    def save(self, *args, **kwargs):
        """Calculate requested days for draft/pending requests."""
        if self.status in ["DRAFT", "PENDING"] and self.start_date and self.end_date:
            self.requested_days = self.calculate_working_days()
        super().save(*args, **kwargs)

    # ============================================================
    # LIFECYCLE METHODS
    # ============================================================

    # ============================================================
    # LIFECYCLE METHODS
    # ============================================================

    def submit(self, user=None):
        """
        Submit a draft leave request for approval.
        """
        from staff.services.leave_lifecycle import LeaveLifecycleService

        return LeaveLifecycleService.submit(
            self,
            user,
        )

    def approve(self, user, note=None):
        """
        Approve a pending leave request.
        """
        from staff.services.leave_lifecycle import LeaveLifecycleService

        return LeaveLifecycleService.approve(
            self,
            user,
            note,
        )

    def reject(self, user, reason=None):
        """
        Reject a pending leave request.
        """
        from staff.services.leave_lifecycle import LeaveLifecycleService

        return LeaveLifecycleService.reject(
            self,
            user,
            reason,
        )

    def cancel(self, user, reason=None):
        """
        Cancel a pending or approved leave request.
        """
        from staff.services.leave_lifecycle import LeaveLifecycleService

        return LeaveLifecycleService.cancel(
            self,
            user,
            reason,
        )

    def mark_taken(self, user=None):
        """
        Mark approved leave as taken.
        """
        from staff.services.leave_lifecycle import LeaveLifecycleService

        return LeaveLifecycleService.mark_taken(
            self,
            user,
        )

    def sync_attendance(self):
        """
        Synchronize approved leave with teacher attendance.
        """
        from staff.services.leave_service import sync_attendance

        return sync_attendance(self)

    def unsync_attendance(self):
        """
        Remove attendance records for this leave.
        """
        from staff.services.leave_service import unsync_attendance

        return unsync_attendance(self)

    # ============================================================
    # ATTENDANCE HELPERS
    # ============================================================

    def _get_teacher_for_leave(self):
        """Get the teacher record associated with this staff."""
        if not self.staff_id:
            return None

        try:
            from staff.models import Teacher
            return Teacher.objects.filter(
                school=self.school,
                user=self.staff.user,
                is_active=True
            ).first()
        except Exception:
            return None

    def _get_teacher_absence_reason(self):
        """Map leave type to TeacherAbsence reason."""
        leave_type = getattr(self, "leave_type", None)
        if not leave_type:
            return "OTHER"

        category = (getattr(leave_type, "category", "") or "").upper()
        mapping = {
            "SICK": "SICK",
            "CASUAL": "PERSONAL",
            "COMPASSIONATE": "PERSONAL",
            "MATERNITY": "PERSONAL",
            "PATERNITY": "PERSONAL",
            "STUDY": "PROFESSIONAL_DEVELOPMENT",
            "ANNUAL": "OTHER",
            "UNPAID": "OTHER",
            "OTHER": "OTHER",
        }
        return mapping.get(category, "OTHER")

    def _attendance_sync_marker(self):
        """Unique marker for attendance synchronization."""
        return f"[LEAVE_REQUEST:{self.pk}]"


# ============================================================
# LEAVE LEDGER (Audit Trail)
# ============================================================

class LeaveLedger(models.Model):
    """
    Audit trail for all leave balance changes.
    Records every modification to leave balances for complete auditability.
    """

    ACTION_CHOICES = (
        ('RESERVE', 'Reserved'),
        ('RELEASE', 'Released'),
        ('APPROVE', 'Approved'),
        ('REVERSE', 'Reversed'),
        ('ADJUST', 'Adjusted'),
        ('CARRY_OVER', 'Carried Over'),
        ('EXPIRE', 'Expired'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='leave_ledger_entries')

    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='leave_ledger')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='leave_ledger')
    leave_request = models.ForeignKey(
        LeaveRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries'
    )

    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    days = models.DecimalField(max_digits=6, decimal_places=1, default=0)

    balance_before = models.JSONField(default=dict, help_text="Balance before the action")
    balance_after = models.JSONField(default=dict, help_text="Balance after the action")

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leave_ledger_entries'
    )
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['staff', 'created_at']),
            models.Index(fields=['leave_request']),
        ]

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.action} - {self.days} days"


# ============================================================
# TEACHER & ABSENCE MODELS
# ============================================================

class Teacher(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='teachers')
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'TEACHER'},
        related_name='teacher_profile',
    )
    staff_number = models.CharField(max_length=50, unique=True)
    department = models.CharField(max_length=100, blank=True, null=True)
    subjects = models.ManyToManyField(
        'academics.Subject',
        blank=True,
        related_name='qualified_teachers',
        help_text="Subjects this teacher is qualified to teach.",
    )
    max_periods_per_week = models.PositiveIntegerField(
        default=25,
        help_text="Soft cap used by the AI timetabler to avoid overloading a teacher.",
    )
    is_active = models.BooleanField(default=True)
    objects = managers.TenantManager()

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.staff_number})"


class TeacherAbsence(models.Model):
    REASON_CHOICES = (
        ('SICK', 'Sick Leave'),
        ('PERSONAL', 'Personal / Emergency'),
        ('PROFESSIONAL_DEVELOPMENT', 'Professional Development'),
        ('OTHER', 'Other')
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='teacher_absences')
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='absences')
    date = models.DateField()
    reason = models.CharField(max_length=30, choices=REASON_CHOICES, default='OTHER')
    notes = models.TextField(blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reported_absences'
    )
    reported_at = models.DateTimeField(auto_now_add=True)
    objects = managers.TenantManager()

    class Meta:
        unique_together = ('teacher', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.teacher.user.get_full_name()} absent {self.date} ({self.get_reason_display()})"


# ============================================================
# LEAVE CALENDAR EVENT (Phase D - User Experience)
# ============================================================

class LeaveCalendarEvent(models.Model):
    """
    Calendar events for staff leave.
    Used for the Leave Calendar view.
    """

    EVENT_TYPES = (
        ('REQUESTED', 'Requested'),
        ('APPROVED', 'Approved'),
        ('TAKEN', 'Taken'),
        ('HOLIDAY', 'Holiday'),
        ('TEACHER_ABSENT', 'Teacher Absent'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='leave_calendar_events')

    leave_request = models.ForeignKey(
        LeaveRequest,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='calendar_events'
    )
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name='calendar_events')

    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default='APPROVED')
    title = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()

    color = models.CharField(max_length=20, default='#4f46e5')
    description = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['start_date']

    def __str__(self):
        return f"{self.staff.user.get_full_name()} - {self.title}"


# ============================================================
# LEAVE ANALYTICS (Phase E - Intelligence)
# ============================================================

class LeaveAnalytics(models.Model):
    """
    Pre-computed leave analytics for reporting and AI insights.
    """

    PERIOD_CHOICES = (
        ('MONTH', 'Monthly'),
        ('QUARTER', 'Quarterly'),
        ('YEAR', 'Yearly'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='leave_analytics')

    period = models.CharField(max_length=10, choices=PERIOD_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()

    total_requests = models.PositiveIntegerField(default=0)
    total_approved = models.PositiveIntegerField(default=0)
    total_rejected = models.PositiveIntegerField(default=0)
    total_cancelled = models.PositiveIntegerField(default=0)

    total_days_requested = models.DecimalField(max_digits=10, decimal_places=1, default=0)
    total_days_approved = models.DecimalField(max_digits=10, decimal_places=1, default=0)

    by_leave_type = models.JSONField(default=dict, blank=True)
    by_department = models.JSONField(default=dict, blank=True)
    by_grade = models.JSONField(default=dict, blank=True)

    trend_data = models.JSONField(default=dict, blank=True)

    generated_at = models.DateTimeField(auto_now_add=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-period_end']
        indexes = [
            models.Index(fields=['school', 'period']),
            models.Index(fields=['period_start', 'period_end']),
        ]

    def __str__(self):
        return f"Analytics - {self.period} {self.period_start.year}"