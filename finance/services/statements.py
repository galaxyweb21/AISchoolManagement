# finance/services/statements.py
"""
Full itemized fee statements for an approved Invoice -- every line item
(base tuition/fees + any class add-ons that were billed on the invoice),
each item's amount, the invoice total, what's been paid so far, and the
balance due.

This is a document-level view of an Invoice, as opposed to
finance/services/receipts.py which documents a single Payment.

- build_invoice_statement_context(invoice)      -> dict used by both the
                                                     HTML page and the PDF
- generate_invoice_statement_pdf(invoice)        -> PDF bytes (xhtml2pdf),
                                                     or None on failure
- send_invoice_statement_email(invoice)          -> emails the PDF to the
                                                     parent, using the
                                                     existing
                                                     communication.NotificationService
- generate_bulk_statements_zip(invoices)         -> zip bytes containing one
                                                     PDF per invoice
- send_bulk_invoice_statements(invoices)         -> emails each invoice's
                                                     statement, returns a
                                                     per-invoice summary

Everything here is best-effort, same philosophy as receipts.py: a missing
parent, a missing email, or a PDF/email failure for one invoice is logged
and reflected in the result -- it never raises and never stops the rest of
a bulk run.
"""
import io
import logging
import zipfile

from django.db.models import Sum
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def build_invoice_statement_context(invoice):
    """Everything the statement template needs, derived from an Invoice."""
    student = invoice.student
    school = invoice.school

    line_items = list(invoice.line_items.select_related('fee_category').all())
    total_amount = invoice.line_items.aggregate(total=Sum('amount'))['total'] or 0
    amount_paid = invoice.payments.filter(status='CONFIRMED').aggregate(
        total=Sum('amount')
    )['total'] or 0
    balance_due = total_amount - amount_paid

    payments = list(invoice.payments.filter(status='CONFIRMED').order_by('-paid_at'))

    return {
        'invoice': invoice,
        'student': student,
        'school': school,
        'parent': student.parent,
        'line_items': line_items,
        'total_amount': total_amount,
        'amount_paid': amount_paid,
        'balance_due': balance_due,
        'payments': payments,
    }


def generate_invoice_statement_pdf(invoice):
    """Render the invoice as a full itemized fee-statement PDF. Returns bytes, or None on failure."""
    try:
        from xhtml2pdf import pisa
    except ImportError:
        logger.error("xhtml2pdf is not installed; cannot generate PDF statements.")
        return None

    from .receipts import _link_callback

    context = build_invoice_statement_context(invoice)
    context['is_pdf'] = True

    try:
        html = render_to_string('finance/invoice_statement.html', context)
    except Exception as exc:
        logger.error(f"Statement PDF: failed to render template for invoice {invoice.id}: {exc}")
        return None

    buffer = io.BytesIO()
    try:
        result = pisa.CreatePDF(html, dest=buffer, encoding='UTF-8', link_callback=_link_callback)
    except Exception as exc:
        logger.error(f"Statement PDF: pisa raised for invoice {invoice.id}: {exc}")
        return None

    if result.err:
        logger.error(f"Statement PDF: {result.err} error(s) generating PDF for invoice {invoice.id}")
        return None

    return buffer.getvalue()


def send_invoice_statement_email(invoice):
    """
    Email the full itemized fee-statement PDF to the student's
    parent/guardian. Best-effort -- logs and returns a status dict rather
    than raising.
    """
    from communication.services import NotificationService
    from communication.models import NotificationCategory, NotificationChannel

    result = {'email_sent': False, 'reason': None}

    student = invoice.student
    parent = student.parent

    if not parent:
        result['reason'] = 'No parent/guardian is linked to this student, so no statement could be sent.'
        logger.info(f"Statement: no parent linked to student {student.id} -- skipping notification.")
        return result

    context = build_invoice_statement_context(invoice)
    parent_name = parent.get_full_name() or 'Parent/Guardian'
    student_name = student.user.get_full_name()

    recipient_email = NotificationService.get_recipient_email(parent)
    if not recipient_email:
        result['reason'] = 'The parent/guardian on file has no email address to send a statement to.'
        logger.info(f"Statement: parent of student {student.id} has no email on file -- skipping statement email.")
        return result

    subject = f"Fee Statement - {invoice.invoice_number}"
    message = (
        f"Dear {parent_name},\n\n"
        f"Please find attached the detailed fee statement for {student_name} "
        f"({student.admission_number}) for {invoice.academic_term.name if invoice.academic_term else 'the term'}.\n\n"
        f"Invoice No: {invoice.invoice_number}\n"
        f"Total Billed: GH\u00a2 {context['total_amount']:.2f}\n"
        f"Amount Paid: GH\u00a2 {context['amount_paid']:.2f}\n"
        f"Balance Due: GH\u00a2 {context['balance_due']:.2f}\n"
        f"Due Date: {invoice.due_date.strftime('%d %b %Y')}\n\n"
        f"Thank you.\n{invoice.school.name}"
    )

    try:
        pdf_bytes = generate_invoice_statement_pdf(invoice)
        attachments = None
        if pdf_bytes:
            attachments = [(f"Fee-Statement-{invoice.invoice_number}.pdf", pdf_bytes, 'application/pdf')]
        else:
            logger.warning(f"Statement: PDF generation failed for invoice {invoice.id}; emailing without attachment.")

        html_message = render_to_string('finance/invoice_statement_email.html', {
            **context, 'parent_name': parent_name, 'student_name': student_name,
        })

        result['email_sent'] = bool(NotificationService.send_email(
            recipient_email, subject, message,
            html_message=html_message,
            attachments=attachments,
        ))
        if not result['email_sent']:
            result['reason'] = 'The email provider did not confirm delivery.'
    except Exception as exc:
        logger.error(f"Statement: email failed for invoice {invoice.id}: {exc}")
        result['reason'] = 'An error occurred while sending the email.'

    # Log it centrally too (shows up in the in-app notification center),
    # independent of whether the email above actually went out.
    try:
        NotificationService.trigger(
            recipient=parent,
            category=NotificationCategory.PAYMENT_RECEIPT,
            subject=subject,
            message=message,
            channel=NotificationChannel.IN_APP,
            reference_id=str(invoice.id),
            reference_type='Invoice',
            school=invoice.school,
        )
    except Exception as exc:
        logger.error(f"Statement: could not log in-app notification for invoice {invoice.id}: {exc}")

    return result


def generate_bulk_statements_zip(invoices):
    """
    Build one PDF per invoice and package them into a single zip archive.
    Returns (zip_bytes, summary) where summary reports how many succeeded
    and which invoices (by invoice_number) failed to render.
    """
    buffer = io.BytesIO()
    succeeded, failed = [], []

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for invoice in invoices:
            pdf_bytes = generate_invoice_statement_pdf(invoice)
            if pdf_bytes:
                filename = f"Fee-Statement-{invoice.invoice_number}.pdf"
                zf.writestr(filename, pdf_bytes)
                succeeded.append(invoice.invoice_number)
            else:
                failed.append(invoice.invoice_number)

    summary = {'total': len(invoices), 'succeeded': len(succeeded), 'failed': failed}
    return buffer.getvalue(), summary


def send_bulk_invoice_statements(invoices):
    """
    Email the fee statement for each invoice to its student's parent.
    Best-effort per invoice -- one failure never stops the rest. Returns a
    summary dict plus a per-invoice breakdown for reporting back to the user.
    """
    results = []
    sent, failed = 0, 0

    for invoice in invoices:
        outcome = send_invoice_statement_email(invoice)
        entry = {
            'invoice_number': invoice.invoice_number,
            'student_name': invoice.student.user.get_full_name(),
            'email_sent': outcome['email_sent'],
            'reason': outcome.get('reason'),
        }
        results.append(entry)
        if outcome['email_sent']:
            sent += 1
        else:
            failed += 1

    return {
        'total': len(invoices),
        'sent': sent,
        'failed': failed,
        'results': results,
    }
