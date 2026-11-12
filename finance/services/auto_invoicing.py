# finance/services/auto_invoicing.py
"""Idempotent enterprise student-term fee and invoice automation."""
import logging
from decimal import Decimal

from django.db import IntegrityError, transaction

from school.models import AcademicTerm
from ..models import Invoice, InvoiceLineItem, StudentFee, StudentFeeEnrollment
from .fee_preparation import auto_prepare_student_fees, create_student_fee_ledger_entry
from .ledger import create_invoice_ledger_entries

logger = logging.getLogger(__name__)
ZERO = Decimal("0.00")


def get_current_term(school):
    """Return the latest active term in the school's active academic year."""
    if not school:
        return None
    return (
        AcademicTerm.objects
        .filter(
            academic_year__school=school,
            academic_year__is_active=True,
            is_active=True,
        )
        .order_by("-start_date", "-id")
        .first()
    )


@transaction.atomic
def ensure_student_term_invoice(student, created_by=None, academic_term=None, due_date=None):
    """
    Ensure one official invoice exists for a student and term.

    The operation is idempotent and safe to call from both the student
    creation view and the Student post-save signal. Existing invoices are
    never replaced or rebuilt.
    """
    if not student or not student.school:
        return None

    term = academic_term or get_current_term(student.school)
    if not term:
        logger.warning("No active academic term; invoice skipped for student %s.", student)
        return None

    # Never accept a term belonging to another school. This protects both
    # normal calls and future integrations/imports.
    if term.academic_year.school_id != student.school_id:
        raise ValueError("Academic term does not belong to the student's school.")

    # Hard stop against duplicate invoices. The database unique constraint is
    # the final guard; this lock also serializes normal concurrent requests.
    existing = (
        Invoice.objects
        .select_for_update()
        .filter(school=student.school, student=student, academic_term=term)
        .first()
    )
    if existing:
        return existing

    enrollment = (
        StudentFeeEnrollment.objects
        .filter(student=student, academic_term=term)
        .select_related("enrollment_type", "package_used")
        .first()
    )

    student_fee = (
        StudentFee.objects
        .select_for_update()
        .filter(school=student.school, student=student, academic_term=term)
        .prefetch_related("items__fee_category")
        .first()
    )

    if not student_fee:
        # The fee preparation service is the only place allowed to build
        # student charges. It respects auto_prepare_fees and raises the real
        # configuration error instead of silently manufacturing a bill.
        student_fee = auto_prepare_student_fees(
            student, created_by=created_by, raise_errors=True
        )
        if not student_fee:
            return None
        enrollment = (
            StudentFeeEnrollment.objects
            .filter(student=student, academic_term=term)
            .select_related("enrollment_type", "package_used")
            .first()
        )
    else:
        # A fee may already exist in DRAFT/PREPARED state because another
        # workflow prepared it before invoice automation ran. Complete the
        # same lifecycle here instead of leaving the student without a bill.
        if not enrollment:
            enrollment = (
                StudentFeeEnrollment.objects
                .filter(student=student, academic_term=term)
                .select_related("enrollment_type", "package_used")
                .first()
            )

        if student_fee.status not in ("APPROVED", "INVOICED", "CANCELLED"):
            rebuilt = auto_prepare_student_fees(
                student, created_by=created_by, raise_errors=True
            )
            if rebuilt:
                student_fee = rebuilt
                enrollment = (
                    StudentFeeEnrollment.objects
                    .filter(student=student, academic_term=term)
                    .select_related("enrollment_type", "package_used")
                    .first()
                )

        if (
            student_fee.status == "PREPARED"
            and enrollment
            and enrollment.enrollment_type
            and enrollment.enrollment_type.auto_approve_fees
        ):
            student_fee.status = "APPROVED"
            student_fee.approved_by = created_by
            student_fee.save(update_fields=["status", "approved_by", "updated_at"])
            create_student_fee_ledger_entry(student_fee, created_by=created_by)

    if not student_fee:
        return None

    if student_fee.status not in ("APPROVED", "INVOICED"):
        logger.info(
            "Invoice not created for %s: fee status is %s.",
            student, student_fee.status
        )
        return None

    # Invoice lines are always sourced from the actual prepared fee items.
    # StudentFee.final_amount is a summary field and must not be used as the
    # invoice total because class add-ons live in StudentFeeItem rows.
    billable_items = [
        item for item in student_fee.items.all()
        if (item.final_amount or ZERO) > ZERO
    ]
    if not billable_items:
        logger.warning("No billable fee items found for %s; invoice skipped.", student)
        return None

    try:
        invoice = Invoice.objects.create(
            school=student.school,
            student=student,
            academic_term=term,
            due_date=due_date or term.end_date,
            status="UNPAID",
        )
    except IntegrityError:
        # A concurrent worker may have created it after our initial lookup.
        return Invoice.objects.filter(
            school=student.school, student=student, academic_term=term
        ).first()

    InvoiceLineItem.objects.bulk_create([
        InvoiceLineItem(
            invoice=invoice,
            fee_category=item.fee_category,
            description=item.description or item.fee_category.name,
            amount=item.final_amount,
        )
        for item in billable_items
    ])

    # Ledger creation is part of the same transaction. An invoice without
    # its corresponding ledger entry creates a financial inconsistency, so
    # let an error roll back the invoice rather than leaving partial data.
    create_invoice_ledger_entries(invoice, created_by=created_by)

    # Replace any provisional StudentFee ledger debit with the official
    # invoice ledger. Keeping both would double the student's balance.
    from ..models import StudentFinancialLedger
    StudentFinancialLedger.objects.filter(
        school=student_fee.school,
        student=student_fee.student,
        academic_term=student_fee.academic_term,
        entry_type="INVOICE",
        reference=f"FEE-{student_fee.id}",
    ).delete()

    if student_fee.status != "INVOICED":
        student_fee.status = "INVOICED"
        student_fee.save(update_fields=["status", "updated_at"])

    logger.info(
        "Created automatic invoice %s for student %s, term %s (total %s).",
        invoice.invoice_number, student, term.name, invoice.total_amount
    )
    return invoice
