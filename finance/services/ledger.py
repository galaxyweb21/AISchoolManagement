# finance/services/ledger.py
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from ..models import (
    Invoice,
    Payment,
    StudentFinancialLedger,
)


def create_invoice_ledger_entries(invoice, created_by=None):
    """Create debit ledger entries for an invoice."""
    if not invoice:
        return 0

    with transaction.atomic():
        # Delete existing entries for this invoice to avoid duplicates
        StudentFinancialLedger.objects.filter(
            invoice=invoice,
            entry_type='INVOICE'
        ).delete()

        line_items = invoice.line_items.select_related('fee_category').all()
        created_count = 0

        for item in line_items:
            if item.amount <= 0:
                continue

            # Use bulk_create for better performance and to avoid recursion issues
            StudentFinancialLedger.objects.create(
                school=invoice.school,
                student=invoice.student,
                academic_term=invoice.academic_term,
                entry_type='INVOICE',
                side='DEBIT',
                amount=item.amount,
                description=item.description,
                reference=invoice.invoice_number,
                invoice=invoice,
                created_by=created_by,
                transaction_date=invoice.created_at,  # Use invoice creation date
            )
            created_count += 1

        return created_count


def create_payment_ledger_entry(payment, created_by=None):
    """Create a credit ledger entry for a confirmed payment."""
    if not payment:
        return None

    if payment.status != 'CONFIRMED':
        return None

    # Check if entry already exists to avoid duplicates
    existing = StudentFinancialLedger.objects.filter(
        payment=payment,
        entry_type='PAYMENT'
    ).first()

    if existing:
        return existing

    invoice = payment.invoice

    return StudentFinancialLedger.objects.create(
        school=invoice.school,
        student=invoice.student,
        academic_term=invoice.academic_term,
        entry_type='PAYMENT',
        side='CREDIT',
        amount=payment.amount,
        description=f"Payment - {payment.get_method_display()}",
        reference=payment.receipt_number or payment.reference_number,
        invoice=invoice,
        payment=payment,
        created_by=created_by or payment.recorded_by,
        transaction_date=payment.paid_at,
    )


def get_student_balance(student, academic_term=None):
    """Calculate the student's financial balance."""
    queryset = StudentFinancialLedger.objects.filter(
        school=student.school,
        student=student,
    )

    if academic_term is not None:
        queryset = queryset.filter(academic_term=academic_term)

    totals = queryset.aggregate(
        debits=Sum('amount', filter=Q(side='DEBIT')),
        credits=Sum('amount', filter=Q(side='CREDIT')),
    )

    debits = totals['debits'] or Decimal('0.00')
    credits = totals['credits'] or Decimal('0.00')

    return debits - credits


def get_student_previous_balance(student, current_term):
    """Calculate the student's outstanding balance from previous terms."""
    previous_term_ids = list(
        current_term.__class__.objects
        .filter(
            academic_year__school=student.school,
            start_date__lt=current_term.start_date,
        )
        .values_list('id', flat=True)
    )

    if not previous_term_ids:
        return Decimal('0.00')

    queryset = StudentFinancialLedger.objects.filter(
        school=student.school,
        student=student,
        academic_term_id__in=previous_term_ids,
    )

    totals = queryset.aggregate(
        debits=Sum('amount', filter=Q(side='DEBIT')),
        credits=Sum('amount', filter=Q(side='CREDIT')),
    )

    debits = totals['debits'] or Decimal('0.00')
    credits = totals['credits'] or Decimal('0.00')

    return debits - credits


def create_arrears_entry(student, current_term, amount, created_by=None):
    """Carry a previous outstanding balance into the current term."""
    amount = Decimal(str(amount))

    if amount <= 0:
        return None

    existing = StudentFinancialLedger.objects.filter(
        school=student.school,
        student=student,
        academic_term=current_term,
        entry_type='ARREARS',
    ).first()

    if existing:
        return existing

    return StudentFinancialLedger.objects.create(
        school=student.school,
        student=student,
        academic_term=current_term,
        entry_type='ARREARS',
        side='DEBIT',
        amount=amount,
        description='Balance brought forward from previous term',
        reference=f'ARREARS-{current_term.pk}',
        created_by=created_by,
        transaction_date=current_term.start_date,
    )