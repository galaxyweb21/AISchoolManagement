import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from ai_engine.models import EmailHealthCheck, ReportCardDelivery

logger = logging.getLogger(__name__)


def _int_setting(name, default):
    try:
        return max(0, int(getattr(settings, name, default)))
    except (TypeError, ValueError):
        return default


class EmailMonitoringService:
    """SMTP health testing and controlled report-card delivery retries."""

    @staticmethod
    def test(school, user=None, recipient=None):
        recipient = (recipient or '').strip()
        started = time.monotonic()
        check = EmailHealthCheck.objects.create(
            school=school, tested_by=user, recipient_email=recipient
        )
        connection_verified = False
        try:
            connection = get_connection(fail_silently=False)
            connection.open()
            connection_verified = True
            connection.close()

            message = 'SMTP connection and authentication succeeded.'
            if recipient:
                email = EmailMessage(
                    subject=f'{school.name} – EduAI Email Health Test',
                    body=(f'This is a test email from {school.name}.\n\n'
                          'If you received this message, outbound email delivery is working.'),
                    from_email=None, to=[recipient], connection=get_connection(fail_silently=False),
                )
                email.send(fail_silently=False)
                message = f'SMTP connection/authentication and test delivery to {recipient} succeeded.'

            check.success = True
            check.connection_verified = connection_verified
            check.message = message
        except Exception as exc:
            check.success = False
            check.connection_verified = connection_verified
            check.message = f'{type(exc).__name__}: {str(exc)[:1000]}'
            logger.exception('Email health test failed for school %s', school.id)
        finally:
            check.duration_ms = int((time.monotonic() - started) * 1000)
            check.save(update_fields=['success', 'connection_verified', 'message', 'duration_ms'])
        return check

    @classmethod
    def send_report_card_delivery(cls, delivery):
        """Send one report card and persist attempt/retry state."""
        from ai_engine.services.export_service import ExportService

        now = timezone.now()
        delivery.last_attempt_at = now
        delivery.retry_count = (delivery.retry_count or 0) + 1
        delivery.save(update_fields=['last_attempt_at', 'retry_count'])

        recipient = (delivery.recipient_email or '').strip()
        if not recipient:
            delivery.status = 'SKIPPED'
            delivery.error_message = 'No parent/guardian email address.'
            delivery.next_retry_at = None
            delivery.save(update_fields=['status', 'error_message', 'next_retry_at'])
            return 'SKIPPED'

        try:
            card = delivery.report_card
            response = ExportService.export_report_card_to_pdf(card)
            pdf_bytes = bytes(response.content)
            parent = getattr(card.student, 'parent', None)
            school = delivery.release_batch.school
            student_name = card.student.user.get_full_name()
            subject = f'{school.name} – {card.academic_term.name} Report Card – {student_name}'
            text = (f'Dear {parent.get_full_name() if parent else "Parent/Guardian"},\n\n'
                    f'Please find attached the official report card for {student_name} for {card.academic_term}.\n\n'
                    f'Regards,\n{school.name}')
            email = EmailMessage(subject=subject, body=text, from_email=None, to=[recipient])
            email.attach(f'Report-Card-{card.student.admission_number}.pdf', pdf_bytes, 'application/pdf')
            email.send(fail_silently=False)
            delivery.status = 'SENT'
            delivery.sent_at = timezone.now()
            delivery.next_retry_at = None
            delivery.error_message = ''
            delivery.save(update_fields=['status', 'sent_at', 'next_retry_at', 'error_message'])
            return 'SENT'
        except Exception as exc:
            max_retries = _int_setting('REPORT_CARD_EMAIL_MAX_RETRIES', 3)
            delay_minutes = _int_setting('REPORT_CARD_EMAIL_RETRY_DELAY_MINUTES', 15)
            delivery.status = 'FAILED'
            delivery.error_message = f'{type(exc).__name__}: {str(exc)[:500]}'
            if delivery.retry_count < max_retries:
                # Exponential backoff: 15, 30, 60 minutes by default.
                delay = delay_minutes * (2 ** max(0, delivery.retry_count - 1))
                delivery.next_retry_at = timezone.now() + timedelta(minutes=delay)
            else:
                delivery.next_retry_at = None
            delivery.save(update_fields=['status', 'error_message', 'next_retry_at'])
            logger.exception('Report-card delivery attempt failed for %s', delivery.id)
            return 'FAILED'

    @classmethod
    def refresh_batch_counts(cls, batch):
        qs = batch.deliveries.all()
        batch.emailed_count = qs.filter(status='SENT').count()
        batch.email_failed_count = qs.filter(status='FAILED').count()
        batch.email_skipped_count = qs.filter(status='SKIPPED').count()
        if batch.status == 'PARTIAL' and batch.blocked_count == 0 and batch.email_failed_count == 0 and batch.email_skipped_count == 0:
            batch.status = 'COMPLETE'
            batch.completed_at = timezone.now()
            batch.save(update_fields=['emailed_count', 'email_failed_count', 'email_skipped_count', 'status', 'completed_at'])
        else:
            batch.save(update_fields=['emailed_count', 'email_failed_count', 'email_skipped_count'])
        return batch
