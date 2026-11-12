# finance/models.py
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from school.models import School, AcademicTerm
from school.services.managers import TenantManager
from students.models import Student, GradeLevel
from academics.models import SchoolClass
from decimal import Decimal


# ============================================================
# FEE DEFINITION LAYER
# ============================================================

class FeeCategory(models.Model):
    """A kind of charge (Tuition, Transport, Books, ...)."""
    TYPE_CHOICES = [
        ('TUITION', 'Tuition'),
        ('TRANSPORT', 'Transportation'),
        ('BOARDING', 'Boarding / Hostel'),
        ('BOOKS', 'Books & Stationery'),
        ('UNIFORM', 'Uniform'),
        ('EXAM', 'Examination Fee'),
        ('LIBRARY', 'Library Fee / Fine'),
        ('ACTIVITY', 'PTA / Sports / Activity'),
        ('ADMISSION', 'Admission / Registration'),
        ('ARREARS', 'Balance Brought Forward'),
        ('OTHER', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='fee_categories')
    name = models.CharField(max_length=150, help_text="e.g., Tuition Fee, Lab Fee, Transport")
    category_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='OTHER')
    is_recurring = models.BooleanField(
        default=True,
        help_text="True if billed every term (tuition). False for one-off charges (admission fee)."
    )
    is_optional = models.BooleanField(
        default=False,
        help_text="True if only charged when a student opts in (e.g. transport, boarding)."
    )
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    objects = TenantManager()

    class Meta:
        verbose_name_plural = 'Fee Categories'
        ordering = ['category_type', 'name']
        unique_together = ['school', 'name']

    def __str__(self):
        return self.name


class FeeStructure(models.Model):
    """
    The published 'price list' for one school class in one term.
    Invoices are generated FROM this, never priced ad hoc.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='fee_structures')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name='fee_structures', null=True)

    # FIXED: Use SchoolClass instead of GradeLevel
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name='fee_structures', null=True
    )

    is_published = models.BooleanField(
        default=False,
        help_text="Lock once invoices have been generated from it, to protect historical accuracy."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-academic_term__start_date', 'school_class__grade_level__order']
        # FIXED: Unique together uses school_class instead of grade_level
        unique_together = ['academic_term', 'school_class']

    @property
    def grade_level(self):
        """Convenience property to access the grade level from the class"""
        return self.school_class.grade_level

    @property
    def total_termly_amount(self):
        return self.items.aggregate(t=Sum('amount'))['t'] or 0

    def __str__(self):
        return f"{self.school_class.name} — {self.academic_term.name}"


class FeeStructureItem(models.Model):
    """One priced line within a FeeStructure, e.g. 'Tuition — GHS 1,200'."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fee_structure = models.ForeignKey(FeeStructure, on_delete=models.CASCADE, related_name='items')
    fee_category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name='structure_items')
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ['fee_category__category_type']
        unique_together = ['fee_structure', 'fee_category']

    def __str__(self):
        return f"{self.fee_category.name}: {self.amount}"


# ============================================================
# DISCOUNTS / SCHOLARSHIPS
# ============================================================

class FeeWaiver(models.Model):
    """Sibling discount, scholarship, bursary, staff-child waiver, etc."""
    TYPE_CHOICES = [('PERCENTAGE', 'Percentage'), ('FIXED', 'Fixed Amount')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='fee_waivers')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='fee_waivers')
    fee_category = models.ForeignKey(
        FeeCategory, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Leave blank to apply this waiver to the whole invoice rather than one category."
    )
    academic_term = models.ForeignKey(
        AcademicTerm, on_delete=models.CASCADE, null=True, blank=True, related_name='fee_waivers',
        help_text="Leave blank for a standing waiver that applies every term."
    )
    waiver_type = models.CharField(max_length=12, choices=TYPE_CHOICES, default='PERCENTAGE')
    value = models.DecimalField(max_digits=10, decimal_places=2,
                                help_text="15.00 means 15% or GHS 15, depending on type.")
    reason = models.CharField(max_length=200, help_text="e.g., 'Sibling discount', 'Headmaster's scholarship'")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']

    def amount_for(self, base_amount):
        if self.waiver_type == 'PERCENTAGE':
            return (base_amount * self.value) / 100
        return min(self.value, base_amount)

    def __str__(self):
        return f"{self.student} — {self.reason}"


# ============================================================
# TRANSPORT
# ============================================================

class TransportRoute(models.Model):
    """A zone/route with its own termly fee, e.g. 'Route A — Dansoman'."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='transport_routes')
    name = models.CharField(max_length=150)
    fee_per_term = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    objects = TenantManager()

    class Meta:
        ordering = ['name']
        unique_together = ['school', 'name']

    def __str__(self):
        return f"{self.name} ({self.fee_per_term}/term)"


class StudentTransportSubscription(models.Model):
    """Whether a student uses school transport, and which route."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='transport')
    route = models.ForeignKey(TransportRoute, on_delete=models.PROTECT, related_name='subscribers')
    is_active = models.BooleanField(default=True)
    started_at = models.DateField(default=timezone.localdate)

    def __str__(self):
        return f"{self.student} → {self.route.name}"


# ============================================================
# BILLING LAYER
# ============================================================

class Invoice(models.Model):
    STATUS_CHOICES = (
        ('UNPAID', 'Unpaid'),
        ('PARTIAL', 'Partially Paid'),
        ('PAID', 'Paid'),
        ('VOID', 'Void'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='invoices')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='invoices')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name='invoices', null=True)
    invoice_number = models.CharField(max_length=30, unique=True, editable=False, null=True)
    due_date = models.DateField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='UNPAID')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']
        unique_together = ['student', 'academic_term']
        indexes = [models.Index(fields=['status'])]

    @classmethod
    def generate_invoice_number(cls, school, year=None):
        year = year or timezone.localdate().year
        prefix = f"INV-{school.subdomain[:4].upper()}-{year}-"
        sequence = cls.objects.filter(invoice_number__startswith=prefix).count() + 1
        candidate = f"{prefix}{sequence:05d}"
        while cls.objects.filter(invoice_number=candidate).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:05d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self.generate_invoice_number(self.school)
        super().save(*args, **kwargs)

    @property
    def total_amount(self):
        return self.line_items.aggregate(t=Sum('amount'))['t'] or 0

    @property
    def amount_paid(self):
        return self.payments.filter(status='CONFIRMED').aggregate(t=Sum('amount'))['t'] or 0

    @property
    def balance_due(self):
        return self.total_amount - self.amount_paid

    def refresh_status(self):
        paid, total = self.amount_paid, self.total_amount
        if total <= 0:
            self.status = 'VOID'
        elif paid <= 0:
            self.status = 'UNPAID'
        elif paid < total:
            self.status = 'PARTIAL'
        else:
            self.status = 'PAID'
        self.save(update_fields=['status'])

    def __str__(self):
        return f"{self.invoice_number} — {self.student}"


class InvoiceLineItem(models.Model):
    """One itemized charge on an invoice."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='line_items')
    fee_category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name='line_items')
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.description}: {self.amount}"


# ============================================================
# PAYMENTS
# ============================================================

class Payment(models.Model):
    METHOD_CHOICES = [
        ('CASH', 'Cash'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('MOBILE_MONEY', 'Mobile Money'),
        ('CARD', 'Card'),
        ('CHEQUE', 'Cheque'),
        ('ONLINE_GATEWAY', 'Online Gateway'),
    ]
    STATUS_CHOICES = [
        ('CONFIRMED', 'Confirmed'),
        ('PENDING', 'Pending'),
        ('REVERSED', 'Reversed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    reference_number = models.CharField(max_length=100, blank=True)
    receipt_number = models.CharField(max_length=30, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='CONFIRMED')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    related_name='payments_recorded')
    paid_at = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-paid_at']
        indexes = [models.Index(fields=['status']), models.Index(fields=['method'])]

    @classmethod
    def generate_receipt_number(cls, school, year=None):
        year = year or timezone.localdate().year
        prefix = f"RCT-{school.subdomain[:4].upper()}-{year}-"
        sequence = cls.objects.filter(receipt_number__startswith=prefix).count() + 1
        candidate = f"{prefix}{sequence:05d}"
        while cls.objects.filter(receipt_number=candidate).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:05d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = self.generate_receipt_number(
                self.invoice.school
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.receipt_number} — {self.amount} ({self.get_method_display()})"


# ============================================================
# STUDENT FINANCIAL LEDGER
# ============================================================

class StudentFinancialLedger(models.Model):
    """
    Immutable-style financial transaction history for a student.

    Positive debit:
        Money/charges owed by the student.

    Positive credit:
        Money received or amounts credited to the student.

    The running balance is calculated as:

        total debits - total credits
    """

    ENTRY_TYPE_CHOICES = [
        ('OPENING_BALANCE', 'Opening Balance'),
        ('ARREARS', 'Arrears / Balance Brought Forward'),
        ('INVOICE', 'Invoice Charge'),
        ('PAYMENT', 'Payment'),
        ('WAIVER', 'Discount / Waiver'),
        ('CREDIT', 'Credit'),
        ('ADJUSTMENT', 'Adjustment'),
        ('REFUND', 'Refund'),
        ('REVERSAL', 'Payment Reversal'),
    ]

    SIDE_CHOICES = [
        ('DEBIT', 'Debit'),
        ('CREDIT', 'Credit'),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='financial_ledger_entries'
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='financial_ledger_entries'
    )

    academic_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='financial_ledger_entries'
    )

    entry_type = models.CharField(
        max_length=30,
        choices=ENTRY_TYPE_CHOICES
    )

    side = models.CharField(
        max_length=10,
        choices=SIDE_CHOICES
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    description = models.CharField(
        max_length=255
    )

    reference = models.CharField(
        max_length=100,
        blank=True
    )

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries'
    )

    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ledger_entries'
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='financial_ledger_entries_created'
    )

    transaction_date = models.DateTimeField(
        default=timezone.now
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    objects = TenantManager()

    class Meta:
        ordering = ['transaction_date', 'created_at']
        indexes = [
            models.Index(
                fields=['school', 'student']
            ),
            models.Index(
                fields=['student', 'academic_term']
            ),
            models.Index(
                fields=['entry_type']
            ),
            models.Index(
                fields=['transaction_date']
            ),
        ]

    @classmethod
    def student_balance(cls, student, academic_term=None):
        """
        Return the student's outstanding balance.

        Positive result = student owes school.
        Negative result = student has credit.
        """

        queryset = cls.objects.filter(
            student=student,
            school=student.school
        )

        if academic_term is not None:
            queryset = queryset.filter(
                academic_term=academic_term
            )

        totals = queryset.aggregate(
            debits=Sum(
                'amount',
                filter=models.Q(side='DEBIT')
            ),
            credits=Sum(
                'amount',
                filter=models.Q(side='CREDIT')
            )
        )

        debits = totals['debits'] or 0
        credits = totals['credits'] or 0

        return debits - credits

    @classmethod
    def student_debits(cls, student, academic_term=None):
        queryset = cls.objects.filter(
            student=student,
            school=student.school,
            side='DEBIT'
        )

        if academic_term is not None:
            queryset = queryset.filter(
                academic_term=academic_term
            )

        return queryset.aggregate(
            total=Sum('amount')
        )['total'] or 0

    @classmethod
    def student_credits(cls, student, academic_term=None):
        queryset = cls.objects.filter(
            student=student,
            school=student.school,
            side='CREDIT'
        )

        if academic_term is not None:
            queryset = queryset.filter(
                academic_term=academic_term
            )

        return queryset.aggregate(
            total=Sum('amount')
        )['total'] or 0

    def __str__(self):
        return (
            f"{self.student} — "
            f"{self.get_entry_type_display()} — "
            f"{self.amount}"
        )

    @property
    def debit_amount(self):
        if self.side == 'DEBIT':
            return self.amount
        return 0

    @property
    def credit_amount(self):
        if self.side == 'CREDIT':
            return self.amount
        return 0


# ============================================================
# LOGISTICS / PHYSICAL-ITEM BILLING
# ============================================================

class LogisticItem(models.Model):
    """Catalog of billable physical items."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='logistic_items')
    name = models.CharField(max_length=150)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_in_stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = TenantManager()

    class Meta:
        ordering = ['name']
        unique_together = ['school', 'name']

    def __str__(self):
        return f"{self.name} ({self.unit_price})"


class LogisticIssuance(models.Model):
    """One student was issued N of an item."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='issuances')
    item = models.ForeignKey(LogisticItem, on_delete=models.PROTECT, related_name='issuances')
    quantity = models.PositiveIntegerField(default=1)
    invoice_line_item = models.OneToOneField(
        InvoiceLineItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='logistic_issuance'
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-issued_at']

    @property
    def total_cost(self):
        return self.item.unit_price * self.quantity

    def __str__(self):
        return f"{self.student} — {self.quantity}x {self.item.name}"


# ============================================================
# STUDENT FEE PREPARATION
# ============================================================

class StudentFee(models.Model):
    """
    Student-specific fee preparation for an academic term.

    This sits between the school's FeeStructure and the Invoice.

    FeeStructure = standard class pricing
    StudentFee   = what this particular student should actually pay
    Invoice      = official bill generated after approval
    """

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('PREPARED', 'Prepared'),
        ('APPROVED', 'Approved'),
        ('INVOICED', 'Invoiced'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='student_fees'
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='student_fees'
    )

    fee_structure = models.ForeignKey(
        FeeStructure,
        on_delete=models.PROTECT,
        related_name='student_fees'
    )

    academic_term = models.ForeignKey(
        AcademicTerm,
        on_delete=models.PROTECT,
        related_name='student_fees'
    )

    # --------------------------------------------------------
    # FINANCIAL SUMMARY
    # --------------------------------------------------------

    base_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    adjustment_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    arrears_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    final_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    # --------------------------------------------------------
    # WORKFLOW
    # --------------------------------------------------------

    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default='DRAFT'
    )

    notes = models.TextField(
        blank=True
    )

    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_fees_prepared'
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_fees_approved'
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    objects = TenantManager()

    class Meta:
        ordering = [
            'student__user__last_name',
            'student__user__first_name'
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    'student',
                    'academic_term'
                ],
                name='unique_student_fee_term'
            )
        ]

        indexes = [
            models.Index(
                fields=['school', 'academic_term']
            ),
            models.Index(
                fields=['student', 'academic_term']
            ),
            models.Index(
                fields=['status']
            ),
        ]

    @property
    def calculated_amount(self):
        return (
            self.base_amount
            - self.discount_amount
            + self.adjustment_amount
            + self.arrears_amount
        )

    @property
    def total_item_amount(self):
        """Sum of final_amount across this fee's individual line items."""
        return sum(
            item.final_amount
            for item in self.items.all()
        )

    def save(self, *args, **kwargs):
        """Persist a fee summary that agrees with its actual line items.

        ``StudentFee.final_amount`` is a summary field. Class add-ons are
        stored as separate ``StudentFeeItem`` rows, so once the fee exists we
        calculate the final amount from those rows and add informational
        arrears. This keeps the fee screen, invoice and ledger consistent.
        During the initial INSERT there are no child items yet, so the normal
        summary calculation is used.
        """
        calculated = max(self.calculated_amount, Decimal('0.00'))

        if self.pk:
            try:
                item_total = self.items.aggregate(
                    total=Sum('final_amount')
                )['total'] or Decimal('0.00')
                if item_total > Decimal('0.00'):
                    calculated = max(
                        item_total + (self.arrears_amount or Decimal('0.00')),
                        Decimal('0.00')
                    )
            except Exception:
                # Child rows may not be available during unusual model
                # lifecycle operations; retain the standard calculation.
                pass

        self.final_amount = calculated
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.student} — "
            f"{self.academic_term} — "
            f"{self.final_amount}"
        )


class StudentFeeItem(models.Model):
    """
    Individual prepared fee line for a student.

    Example:

        Tuition       2,500
        Books           400
        Transport       600
        Examination     150
        -------------------
        Total          3,650
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    student_fee = models.ForeignKey(
        StudentFee,
        on_delete=models.CASCADE,
        related_name='items'
    )

    fee_category = models.ForeignKey(
        FeeCategory,
        on_delete=models.PROTECT,
        related_name='student_fee_items'
    )

    description = models.CharField(
        max_length=200
    )

    # Original amount from FeeStructure
    standard_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    # Discount/waiver applied to this specific item
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    # Manual adjustment can be positive or negative
    adjustment_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    # Final amount charged for this item
    final_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    is_optional = models.BooleanField(
        default=False
    )

    is_waived = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['fee_category__category_type', 'created_at']

    @property
    def calculated_amount(self):
        return max(
            self.standard_amount
            - self.discount_amount
            + self.adjustment_amount,
            0
        )

    def save(self, *args, **kwargs):
        self.final_amount = self.calculated_amount
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.student_fee.student} — "
            f"{self.description} — "
            f"{self.final_amount}"
        )


# ============================================================
# FEE ADD-ON STRUCTURES
# ============================================================

class FeeAddOnStructure(models.Model):
    """
    Additional fee items that can be applied to specific students.
    These are separate from the main fee structure and can be
    applied on a per-student basis.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='fee_addon_structures')
    name = models.CharField(max_length=150, help_text="e.g., New Student Uniform Package")
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name='fee_addon_structures')
    is_active = models.BooleanField(default=True)
    apply_to_new_students_only = models.BooleanField(
        default=True,
        help_text="If checked, only applies to students enrolled after the term started"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']
        unique_together = ['school', 'name', 'academic_term']

    def __str__(self):
        return f"{self.name} - {self.academic_term.name}"


class FeeAddOnItem(models.Model):
    """Individual item within a FeeAddOnStructure."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    addon_structure = models.ForeignKey(FeeAddOnStructure, on_delete=models.CASCADE, related_name='items')
    fee_category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name='addon_items')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['fee_category__category_type']

    def __str__(self):
        return f"{self.fee_category.name}: {self.amount}"


class StudentFeeAdjustment(models.Model):
    """
    Manual adjustments to a student's fee.
    Can be positive (extra charge) or negative (discount/refund).
    """
    ADJUSTMENT_TYPE_CHOICES = [
        ('EXTRA_CHARGE', 'Extra Charge'),
        ('DISCOUNT', 'Discount'),
        ('REFUND', 'Refund'),
        ('CORRECTION', 'Correction'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='fee_adjustments')
    student_fee = models.ForeignKey(StudentFee, on_delete=models.CASCADE, related_name='adjustments')
    fee_category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name='adjustments')
    adjustment_type = models.CharField(max_length=20, choices=ADJUSTMENT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student_fee.student} - {self.description} ({self.amount})"


# finance/models.py - Add these new models

# ============================================================
# ENROLLMENT FEE PACKAGES
# ============================================================

class EnrollmentFeePackage(models.Model):
    """
    Fee package that applies to a specific enrollment type.
    This determines what fees and add-ons a student gets.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='enrollment_packages')
    enrollment_type = models.ForeignKey(
        'students.StudentEnrollmentType',
        on_delete=models.PROTECT,
        related_name='fee_packages'
    )
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name='enrollment_packages')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)

    # Fee structure for this package (if null, use class default)
    fee_structure = models.ForeignKey(
        FeeStructure,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enrollment_packages'
    )

    # Auto-applied add-ons
    auto_addons = models.ManyToManyField(
        FeeAddOnStructure,
        blank=True,
        related_name='enrollment_packages'
    )

    # Discount percentage for this enrollment type
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Percentage discount for this enrollment type"
    )

    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False,
        help_text="Default package for this enrollment type"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']
        unique_together = ['school', 'enrollment_type', 'academic_term']

    def __str__(self):
        return f"{self.enrollment_type.get_name_display()} - {self.academic_term.name}"


class StudentFeeEnrollment(models.Model):
    """
    Tracks which enrollment package a student used for a specific term.
    This allows us to know if a student was charged as new or returning.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='student_fee_enrollments')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='fee_enrollments')
    academic_term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name='student_fee_enrollments')
    enrollment_type = models.ForeignKey('students.StudentEnrollmentType', on_delete=models.PROTECT)
    package_used = models.ForeignKey(EnrollmentFeePackage, on_delete=models.PROTECT, null=True, blank=True)

    # Was this automatically applied or manually overridden?
    is_automatic = models.BooleanField(default=True)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        ordering = ['-created_at']
        unique_together = ['student', 'academic_term']

    def __str__(self):
        return f"{self.student} - {self.academic_term} ({self.enrollment_type.get_name_display()})"


# finance/models.py - Add these new models

# ============================================================
# CLASS-BASED ADD-ON STRUCTURES
# ============================================================

# finance/models.py - Add these models after ClassAddOnStructure

class ClassAddOnStructure(models.Model):
    """
    Fee add-ons that are specific to a class/grade level.
    This allows different add-on amounts for different classes.
    """
    TERM_CHOICES = [
        ('ALL', 'All Terms'),
        ('FIRST', 'First Term Only'),
        ('SECOND', 'Second Term Only'),
        ('THIRD', 'Third Term Only'),
        ('CUSTOM', 'Custom Terms'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='class_addons')
    name = models.CharField(max_length=150, help_text="e.g., New Student Uniform, Admission Fee")
    fee_category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name='class_addons')
    description = models.TextField(blank=True, null=True)

    # Which terms this add-on applies to
    term_type = models.CharField(max_length=20, choices=TERM_CHOICES, default='ALL')
    custom_terms = models.JSONField(
        default=list,
        blank=True,
        help_text="List of term IDs for CUSTOM term_type"
    )

    # Auto-apply settings
    apply_to_new_students_only = models.BooleanField(
        default=False,
        help_text="If checked, only applies to new students"
    )
    is_required = models.BooleanField(
        default=False,
        help_text="If checked, this add-on is mandatory for applicable students"
    )
    is_optional = models.BooleanField(
        default=False,
        help_text="If checked, this add-on can be opted in/out by parent"
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        ordering = ['name']
        unique_together = ['school', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_term_type_display()})"


# finance/models.py - Update ClassAddOnItem

class ClassAddOnItem(models.Model):
    """
    Class-specific pricing for an add-on.
    Different classes can have different amounts.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    addon_structure = models.ForeignKey(ClassAddOnStructure, on_delete=models.CASCADE, related_name='items')

    # School field to fix TenantManager issue
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='class_addon_items',
        null=True,
        blank=True,
        help_text="School this item belongs to (auto-populated from addon_structure)"
    )

    # Which class/grade level this applies to
    grade_level = models.ForeignKey(
        'students.GradeLevel',
        on_delete=models.CASCADE,
        related_name='addon_items',
        null=True,
        blank=True,
        help_text="Specific grade level (e.g., KG 1, JHS 1)"
    )
    school_class = models.ForeignKey(
        'academics.SchoolClass',
        on_delete=models.CASCADE,
        related_name='addon_items',
        null=True,
        blank=True,
        help_text="Specific class (e.g., KG 1A, JHS 1A)"
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    # Per-term overrides (optional)
    first_term_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    second_term_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    third_term_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()

    class Meta:
        ordering = ['addon_structure__name']
        # REMOVE unique_together - it causes duplicate errors when multiple items
        # are created under the same addon_structure with NULL values
        # unique_together = ['addon_structure', 'grade_level', 'school_class']

    def save(self, *args, **kwargs):
        # Auto-populate school from addon_structure
        if not self.school and self.addon_structure:
            self.school = self.addon_structure.school
        super().save(*args, **kwargs)

    def get_amount_for_term(self, term_number):
        """
        Get the amount for a specific term (1, 2, or 3).
        Returns the term-specific amount if set, otherwise the base amount.
        """
        if term_number == 1 and self.first_term_amount is not None:
            return self.first_term_amount
        elif term_number == 2 and self.second_term_amount is not None:
            return self.second_term_amount
        elif term_number == 3 and self.third_term_amount is not None:
            return self.third_term_amount
        return self.amount

    def __str__(self):
        grade = self.grade_level.name if self.grade_level else "All Grades"
        cls = self.school_class.name if self.school_class else "All Classes"
        return f"{self.addon_structure.name} - {grade} ({cls}): GHS {self.amount}"

# finance/models.py - Add this model

class PaymentReceipt(models.Model):
    """Payment receipt generated for a payment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(
        Payment,
        on_delete=models.CASCADE,
        related_name='receipt'
    )
    receipt_number = models.CharField(max_length=50, unique=True, editable=False)
    pdf_file = models.FileField(
        upload_to='receipts/%Y/%m/',
        blank=True,
        null=True
    )
    sent_to_email = models.BooleanField(default=False)
    sent_to_sms = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    sms_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def generate_receipt_number(cls, school, year=None):
        year = year or timezone.localdate().year
        prefix = f"RCP-{school.subdomain[:4].upper()}-{year}-"
        sequence = cls.objects.filter(receipt_number__startswith=prefix).count() + 1
        candidate = f"{prefix}{sequence:06d}"
        while cls.objects.filter(receipt_number=candidate).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:06d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = self.generate_receipt_number(self.payment.invoice.school)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Receipt {self.receipt_number} - {self.payment.invoice.student}"