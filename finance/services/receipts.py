# finance/services/receipts.py
"""
Payment receipt generation and delivery.

- generate_receipt_pdf(payment)      -> PDF bytes (xhtml2pdf), or None on failure
- build_receipt_context(payment)     -> dict used by both the HTML page and the PDF
- send_receipt_notifications(payment) -> emails the PDF to the parent and texts
                                          a confirmation, using the existing
                                          communication.NotificationService
- send_receipt_notifications_async(payment) -> backward-compatible name;
                                                delivery is attempted synchronously after
                                                the payment transaction commits

Everything here is best-effort: a missing parent, a missing email/phone, or
an SMS/email provider failure is logged and returned in the result dict --
it never raises, so it can never turn a *saved* payment into an apparent
failure for the person recording it.
"""
import io
import logging
import os
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


def create_payment_in_app_notification(payment):
    """Create the parent-facing in-app payment receipt notification exactly once."""
    from communication.services import NotificationService
    from communication.models import NotificationCategory, NotificationChannel

    invoice = payment.invoice
    student = invoice.student
    parent = student.parent
    if not parent:
        return None

    context = build_receipt_context(payment)
    parent_name = parent.get_full_name() or 'Parent/Guardian'
    student_name = student.user.get_full_name()
    subject = f"Payment Receipt - {payment.receipt_number}"
    message = (
        f"Dear {parent_name},\n\n"
        f"We confirm receipt of GH¢ {payment.amount:.2f} for {student_name} "
        f"({student.admission_number}), paid via {payment.get_method_display()} on "
        f"{payment.paid_at.strftime('%d %b %Y')}.\n\n"
        f"Receipt No: {payment.receipt_number}\n"
        f"Invoice: {invoice.invoice_number}\n"
        f"Balance remaining: GH¢ {context['balance_due']:.2f}\n\n"
        f"Thank you.\n{invoice.school.name}"
    )

    # Idempotent: payment receipt notifications must never duplicate.
    from communication.models import NotificationLog
    if NotificationLog.objects.filter(
        recipient=parent, category=NotificationCategory.PAYMENT_RECEIPT,
        reference_id=str(payment.id), reference_type='Payment'
    ).exists():
        return None

    return NotificationService.trigger(
        recipient=parent, category=NotificationCategory.PAYMENT_RECEIPT,
        subject=subject, message=message, channel=NotificationChannel.IN_APP,
        reference_id=str(payment.id), reference_type='Payment', school=invoice.school,
    )


def send_receipt_notifications(payment, send_email=True, send_sms=True, create_in_app=False):
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

    result = {'email_sent': False, 'sms_sent': False, 'reason': None, 'email_error': None, 'sms_error': None}

    invoice = payment.invoice
    student = invoice.student
    parent = student.parent

    if not parent:
        result['reason'] = 'No parent/guardian is linked to this student, so no receipt could be sent.'
        result['email_error'] = result['reason'] if send_email else None
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

    recipient_email = (NotificationService.get_recipient_email(parent) or '').strip() if send_email else None
    recipient_phone = (NotificationService.get_recipient_phone(parent) or '').strip() if send_sms else None

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
                    raise_on_error=True,
                ))
                if not result['email_sent']:
                    result['email_error'] = (
                        'The configured email backend did not accept the message. '
                        'Run `python manage.py email_smoke_test recipient@example.com` and check the terminal logs.'
                    )
                    logger.error(
                        'Receipt email delivery failed for payment %s to configured parent email.',
                        payment.id,
                    )
            except Exception as exc:
                result['email_error'] = str(exc)[:500]
                logger.exception("Receipt: email failed for payment %s", payment.id)
        else:
            result['email_error'] = 'The parent/guardian account has no email address.'
            logger.warning("Receipt: parent of student %s has no email on file; payment=%s", student.id, payment.id)

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
                if not result['sms_sent']:
                    result['sms_error'] = 'The SMS provider did not confirm delivery.'
            except Exception as exc:
                result['sms_error'] = str(exc)[:500]
                logger.exception("Receipt: SMS failed for payment %s", payment.id)
        else:
            result['sms_error'] = 'The parent/guardian account has no phone number.'
            logger.info("Receipt: parent of student %s has no phone on file; payment=%s", student.id, payment.id)

    failures = []
    if send_email and not result['email_sent']:
        failures.append(result['email_error'] or 'Receipt email could not be delivered.')
    if send_sms and not result['sms_sent']:
        failures.append(result['sms_error'] or 'Receipt SMS could not be delivered.')
    if failures:
        result['reason'] = ' '.join(failures)

    # Optional for resend flows. The payment-recording flow creates the
    # in-app notification synchronously after the accounting transaction commits.
    if create_in_app:
        try:
            create_payment_in_app_notification(payment)
        except Exception as exc:
            logger.error(f"Receipt: could not log in-app notification for payment {payment.id}: {exc}")

    return result


def send_receipt_notifications_async(payment):
    """Backward-compatible wrapper that delivers before returning.

    A daemon thread can be terminated when a web worker is recycled (common on
    hosted platforms), silently dropping payment receipts. Callers that need a
    reliable delivery attempt use this wrapper; accounting has already committed
    before it is called. The result exposes failures to the payment workflow.
    """
    return send_receipt_notifications(payment, create_in_app=False)
