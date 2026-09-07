# finance/services/receipts.py
"""
Payment receipt generation and delivery.

- generate_receipt_pdf(payment)      -> PDF bytes (xhtml2pdf), or None on failure
- build_receipt_context(payment)     -> dict used by both the HTML page and the PDF
- send_receipt_notifications(payment) -> emails the PDF to the parent and texts
                                          a confirmation, using the existing
                                          communication.NotificationService
- send_receipt_notifications_async(payment) -> same, fired on a background
                                                thread so it never slows down
                                                the payment API response

Everything here is best-effort: a missing parent, a missing email/phone, or
an SMS/email provider failure is logged and returned in the result dict --
it never raises, so it can never turn a *saved* payment into an apparent
failure for the person recording it.
"""
import io
import logging
import os
import threading
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _link_callback(uri, rel):
    """
    xhtml2pdf can't resolve /static/ or /media/ URLs on its own -- it needs
    an absolute filesystem path to embed an image (e.g. the school logo).
    This resolves what it can and falls back to the original URI for
    anything else, so a missing/unresolvable image never crashes the PDF --
    xhtml2pdf just skips it.
    """
    try:
        if uri.startswith(settings.MEDIA_URL):
            path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, '', 1))
            return path if os.path.isfile(path) else uri

        if uri.startswith(settings.STATIC_URL):
            rel_path = uri.replace(settings.STATIC_URL, '', 1)
            candidates = []
            static_root = getattr(settings, 'STATIC_ROOT', None)
            if static_root:
                candidates.append(os.path.join(static_root, rel_path))
            for static_dir in getattr(settings, 'STATICFILES_DIRS', []):
                candidates.append(os.path.join(static_dir, rel_path))
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate
            return uri
    except Exception as exc:
        logger.warning(f"Receipt PDF: could not resolve asset '{uri}': {exc}")

    return uri


def build_receipt_context(payment):
    """Everything the receipt template needs, derived from a Payment."""
    invoice = payment.invoice
    student = invoice.student
    school = invoice.school

    total_amount = invoice.line_items.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    amount_paid_total = invoice.payments.filter(status='CONFIRMED').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    balance_due = total_amount - amount_paid_total
    amount_paid_before_this = amount_paid_total - payment.amount

    return {
        'payment': payment,
        'invoice': invoice,
        'student': student,
        'school': school,
        'parent': student.parent,
        'total_amount': total_amount,
        'amount_paid_before': amount_paid_before_this,
        'amount_paid_total': amount_paid_total,
        'balance_due': balance_due,
    }


def generate_receipt_pdf(payment):
    """Render the payment as a PDF receipt. Returns bytes, or None on failure."""
    try:
        from xhtml2pdf import pisa
    except ImportError:
        logger.error("xhtml2pdf is not installed; cannot generate PDF receipts.")
        return None

    context = build_receipt_context(payment)
    context['is_pdf'] = True

    try:
        html = render_to_string('finance/receipt.html', context)
    except Exception as exc:
        logger.error(f"Receipt PDF: failed to render template for payment {payment.id}: {exc}")
        return None

    buffer = io.BytesIO()
    try:
        result = pisa.CreatePDF(html, dest=buffer, encoding='UTF-8', link_callback=_link_callback)
    except Exception as exc:
        logger.error(f"Receipt PDF: pisa raised for payment {payment.id}: {exc}")
        return None

    if result.err:
        logger.error(f"Receipt PDF: {result.err} error(s) generating PDF for payment {payment.id}")
        return None

    return buffer.getvalue()


def send_receipt_notifications(payment, send_email=True, send_sms=True):
    """
    Email the PDF receipt and/or text a confirmation to the student's
    parent/guardian. Best-effort -- logs and returns a status dict rather
    than raising, so it never affects the payment that already happened.

    send_email / send_sms let a caller ask for just one channel (e.g. an
    "Email Receipt" button that should never also fire an SMS). Both
    default to True, which is the original combined "resend" behaviour.
    """
    from communication.services import NotificationService
    from communication.models import NotificationCategory, NotificationChannel

    result = {'email_sent': False, 'sms_sent': False, 'reason': None}

    invoice = payment.invoice
    student = invoice.student
    parent = student.parent

    if not parent:
        result['reason'] = 'No parent/guardian is linked to this student, so no receipt could be sent.'
        logger.info(f"Receipt: no parent linked to student {student.id} -- skipping notification.")
        return result

    context = build_receipt_context(payment)
    parent_name = parent.get_full_name() or 'Parent/Guardian'
    student_name = student.user.get_full_name()

    subject = f"Payment Receipt - {payment.receipt_number}"
    message = (
        f"Dear {parent_name},\n\n"
        f"We confirm receipt of GH\u00a2 {payment.amount:.2f} for {student_name} "
        f"({student.admission_number}), paid via {payment.get_method_display()} on "
        f"{payment.paid_at.strftime('%d %b %Y')}.\n\n"
        f"Receipt No: {payment.receipt_number}\n"
        f"Invoice: {invoice.invoice_number}\n"
        f"Balance remaining: GH\u00a2 {context['balance_due']:.2f}\n\n"
        f"Thank you.\n{invoice.school.name}"
    )

    recipient_email = NotificationService.get_recipient_email(parent) if send_email else None
    recipient_phone = NotificationService.get_recipient_phone(parent) if send_sms else None

    # ---- Email, with the PDF attached ----
    if send_email:
        if recipient_email:
            try:
                pdf_bytes = generate_receipt_pdf(payment)
                attachments = None
                if pdf_bytes:
                    attachments = [(f"Receipt-{payment.receipt_number}.pdf", pdf_bytes, 'application/pdf')]
                else:
                    logger.warning(f"Receipt: PDF generation failed for payment {payment.id}; emailing without attachment.")

                html_message = render_to_string('finance/receipt_email.html', {
                    **context, 'parent_name': parent_name, 'student_name': student_name,
                })

                result['email_sent'] = bool(NotificationService.send_email(
                    recipient_email, subject, message,
                    html_message=html_message,
                    attachments=attachments,
                ))
            except Exception as exc:
                logger.error(f"Receipt: email failed for payment {payment.id}: {exc}")
        else:
            logger.info(f"Receipt: parent of student {student.id} has no email on file -- skipping receipt email.")

    # ---- SMS confirmation ----
    if send_sms:
        if recipient_phone:
            sms_text = (
                f"{invoice.school.name}: Payment of GH\u00a2{payment.amount:.2f} received for "
                f"{student_name} ({student.admission_number}). Receipt {payment.receipt_number}. "
                f"Balance: GH\u00a2{context['balance_due']:.2f}. Thank you."
            )
            try:
                result['sms_sent'] = bool(NotificationService.send_sms(recipient_phone, sms_text[:160]))
            except Exception as exc:
                logger.error(f"Receipt: SMS failed for payment {payment.id}: {exc}")
        else:
            logger.info(f"Receipt: parent of student {student.id} has no phone on file -- skipping receipt SMS.")

    if send_email and send_sms and not recipient_email and not recipient_phone:
        result['reason'] = "The parent/guardian on file has no email or phone number to send a receipt to."
    elif send_email and not send_sms and not recipient_email:
        result['reason'] = "The parent/guardian on file has no email address to send a receipt to."
    elif send_sms and not send_email and not recipient_phone:
        result['reason'] = "The parent/guardian on file has no phone number to send a receipt to."

    # Log it centrally too (shows up in the in-app notification center),
    # independent of whether the email/SMS above actually went out.
    try:
        NotificationService.trigger(
            recipient=parent,
            category=NotificationCategory.PAYMENT_RECEIPT,
            subject=subject,
            message=message,
            channel=NotificationChannel.IN_APP,
            reference_id=str(payment.id),
            reference_type='Payment',
            school=invoice.school,
        )
    except Exception as exc:
        logger.error(f"Receipt: could not log in-app notification for payment {payment.id}: {exc}")

    return result


def send_receipt_notifications_async(payment):
    """Fire-and-forget version so the payment API response doesn't wait on email/SMS delivery."""
    thread = threading.Thread(target=send_receipt_notifications, args=(payment,))
    thread.daemon = True
    thread.start()
