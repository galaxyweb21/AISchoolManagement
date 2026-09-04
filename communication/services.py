# communication/services.py
import threading
import logging
from datetime import datetime
from django.core.mail import send_mail, EmailMultiAlternatives
from django.utils import timezone
from django.conf import settings
from django.template.loader import render_to_string
from django.db import transaction
from django.db import models  # <-- ADD THIS IMPORT
from .models import NotificationLog, NotificationStatus, NotificationChannel, NotificationCategory, \
    UserNotificationPreference, Announcement

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Enterprise-grade notification service with multi-channel support,
    template rendering, and queuing capabilities.
    """

    @staticmethod
    def get_recipient_email(user):
        """Get email from user or profile."""
        if user.email:
            return user.email
        # Check if user has staff profile with email
        if hasattr(user, 'staff_profile') and user.staff_profile:
            return user.staff_profile.user.email
        if hasattr(user, 'student_profile') and user.student_profile:
            return user.student_profile.user.email
        return None

    @staticmethod
    def get_recipient_phone(user):
        """Get phone number from user or profile."""
        if hasattr(user, 'phone_number') and user.phone_number:
            return user.phone_number
        # Check staff profile
        if hasattr(user, 'staff_profile') and user.staff_profile:
            return user.staff_profile.user.phone_number
        # Check student profile
        if hasattr(user, 'student_profile') and user.student_profile:
            return user.student_profile.user.phone_number
        return None

    @staticmethod
    def send_email(recipient_email, subject, message, html_message=None, attachments=None):
        """
        Send email with optional HTML alternative and optional attachments.

        attachments: optional list of (filename, content_bytes, mimetype) tuples,
        e.g. [("Receipt-RCT-001.pdf", pdf_bytes, "application/pdf")].
        """
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'no-reply@localhost'
        try:
            if html_message or attachments:
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=message,
                    from_email=from_email,
                    to=[recipient_email]
                )
                if html_message:
                    email.attach_alternative(html_message, "text/html")
                for filename, content, mimetype in (attachments or []):
                    email.attach(filename, content, mimetype)
                return email.send()
            else:
                return send_mail(
                    subject=subject,
                    message=message,
                    from_email=from_email,
                    recipient_list=[recipient_email],
                    fail_silently=False,
                )
        except Exception as e:
            logger.error(f"Email send failed: {str(e)}")
            return False

    @staticmethod
    def send_sms(phone_number, message):
        """
        Send SMS via provider (Twilio, Hubtel, Arkesel).
        Placeholder - implement with your SMS provider.
        """
        try:
            # Example for Twilio
            # from twilio.rest import Client
            # client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            # message = client.messages.create(
            #     body=message,
            #     from_=settings.TWILIO_PHONE_NUMBER,
            #     to=phone_number
            # )
            # return True

            # Placeholder for testing
            logger.info(f"SMS sent to {phone_number}: {message[:50]}...")
            return True
        except Exception as e:
            logger.error(f"SMS send failed: {str(e)}")
            return False

    @staticmethod
    def render_notification_template(template_name, context):
        """Render a notification template."""
        try:
            return render_to_string(f'communication/emails/{template_name}.html', context)
        except Exception:
            return None

    @classmethod
    def should_send_notification(cls, user, category):
        """Check if user has opted in for this notification category."""
        try:
            prefs = UserNotificationPreference.objects.get(user=user)
            category_map = {
                NotificationCategory.OVERDUE_BALANCE: prefs.overdue_balance_enabled,
                NotificationCategory.TIMETABLE_UPDATE: prefs.timetable_update_enabled,
                NotificationCategory.GRADE_RELEASE: prefs.grade_release_enabled,
                NotificationCategory.ANNOUNCEMENT: prefs.announcement_enabled,
                NotificationCategory.ATTENDANCE_ALERT: prefs.attendance_alert_enabled,
                NotificationCategory.PROMOTION_RESULT: prefs.promotion_result_enabled,
                NotificationCategory.LEAVE_APPROVAL: prefs.leave_approval_enabled,
            }
            return category_map.get(category, True)
        except UserNotificationPreference.DoesNotExist:
            return True  # Default to sending if no preferences set

    @classmethod
    def dispatch_notification(cls, log_id):
        """
        Execute notification dispatch in background thread.
        """
        try:
            log = NotificationLog.objects.select_related('recipient', 'school').get(id=log_id)

            # Check if user has opted out
            if not cls.should_send_notification(log.recipient, log.category):
                log.status = NotificationStatus.FAILED
                log.error_message = "User has opted out of this notification category."
                log.save()
                return

            email_success = True
            sms_success = True
            in_app_success = True

            recipient_email = cls.get_recipient_email(log.recipient)
            recipient_phone = cls.get_recipient_phone(log.recipient)

            # Send Email
            if log.channel in [NotificationChannel.EMAIL, NotificationChannel.BOTH, NotificationChannel.ALL]:
                if recipient_email:
                    # Try to render HTML template
                    html_message = None
                    try:
                        context = {
                            'recipient': log.recipient,
                            'subject': log.subject,
                            'message': log.message,
                            'category': log.get_category_display(),
                            'school_name': log.school.name if log.school else 'School',
                        }
                        html_message = cls.render_notification_template(
                            f'notification_{log.category.lower()}',
                            context
                        )
                    except Exception:
                        pass

                    email_success = cls.send_email(recipient_email, log.subject, log.message, html_message)
                else:
                    email_success = False

            # Send SMS
            if log.channel in [NotificationChannel.SMS, NotificationChannel.BOTH, NotificationChannel.ALL]:
                if recipient_phone:
                    sms_success = cls.send_sms(recipient_phone, log.message[:160])  # SMS length limit
                else:
                    sms_success = False

            # In-App notification
            if log.channel in [NotificationChannel.IN_APP, NotificationChannel.ALL]:
                # In-app notifications are always "sent" (they're stored in the database)
                in_app_success = True

            # Update log status
            if email_success or sms_success or in_app_success:
                log.status = NotificationStatus.SENT
                log.sent_at = timezone.now()

                # If in-app is the only channel, mark as delivered
                if log.channel == NotificationChannel.IN_APP:
                    log.status = NotificationStatus.DELIVERED
            else:
                log.status = NotificationStatus.FAILED
                errors = []
                if not email_success:
                    errors.append("Email failed")
                if not sms_success:
                    errors.append("SMS failed")
                log.error_message = " | ".join(errors) if errors else "All channels failed"

            log.save()

        except Exception as e:
            logger.error(f"Notification dispatch failed: {str(e)}")
            try:
                log = NotificationLog.objects.get(id=log_id)
                log.status = NotificationStatus.FAILED
                log.error_message = str(e)
                log.save()
            except Exception:
                pass

    @classmethod
    def trigger(cls, recipient, category, subject, message, channel=NotificationChannel.EMAIL,
                sender=None, reference_id=None, reference_type=None, school=None):
        """
        Main public method to trigger notifications.
        """
        # Use recipient's school if not provided
        if not school and hasattr(recipient, 'school'):
            school = recipient.school

        # Create notification log
        log = NotificationLog.objects.create(
            school=school or getattr(recipient, 'school', None),
            recipient=recipient,
            sender=sender,
            category=category,
            channel=channel,
            subject=subject,
            message=message,
            reference_id=reference_id,
            reference_type=reference_type,
            status=NotificationStatus.QUEUED
        )

        # For in-app only, mark as delivered immediately
        if channel == NotificationChannel.IN_APP:
            log.status = NotificationStatus.DELIVERED
            log.sent_at = timezone.now()
            log.save()
            return log

        # Run dispatch in thread for other channels
        thread = threading.Thread(target=cls.dispatch_notification, args=(log.id,))
        thread.daemon = True
        thread.start()
        return log

    @classmethod
    def trigger_bulk(cls, recipients, category, subject, message, channel=NotificationChannel.EMAIL,
                     sender=None, reference_id=None, reference_type=None):
        """
        Send notifications to multiple recipients.
        """
        logs = []
        for recipient in recipients:
            log = cls.trigger(
                recipient=recipient,
                category=category,
                subject=subject,
                message=message,
                channel=channel,
                sender=sender,
                reference_id=reference_id,
                reference_type=reference_type
            )
            logs.append(log)
        return logs


class AnnouncementService:
    """
    Service for managing announcements.
    """

    @staticmethod
    def get_announcements_for_user(user):
        """Get announcements visible to a user based on their role."""
        from .models import Announcement

        school = user.school
        if not school:
            return Announcement.objects.none()

        # Use models.Q for complex queries - models is imported at the top
        queryset = Announcement.objects.filter(
            school=school,
            is_published=True,
            is_archived=False,
            publish_at__lte=timezone.now()
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now())
        )

        # Filter by audience based on user role
        if user.role == 'SUPER_ADMIN':
            queryset = queryset.filter(
                models.Q(audience='ALL') |
                models.Q(audience='ADMIN') |
                models.Q(audience='STAFF')
            )
        elif user.role == 'SCHOOL_ADMIN':
            queryset = queryset.filter(
                models.Q(audience='ALL') |
                models.Q(audience='ADMIN') |
                models.Q(audience='STAFF')
            )
        elif user.role == 'TEACHER':
            queryset = queryset.filter(
                models.Q(audience='ALL') |
                models.Q(audience='TEACHERS') |
                models.Q(audience='STAFF')
            )
        elif user.role == 'PARENT':
            queryset = queryset.filter(
                models.Q(audience='ALL') |
                models.Q(audience='PARENTS')
            )
        elif user.role == 'STUDENT':
            queryset = queryset.filter(
                models.Q(audience='ALL') |
                models.Q(audience='STUDENTS')
            )
        else:
            queryset = queryset.filter(audience='ALL')

        return queryset.order_by('-priority', '-publish_at')

    @staticmethod
    def create_announcement(school, sender, title, content, audience='ALL',
                            priority='NORMAL', publish_at=None, expires_at=None):
        """Create a new announcement."""
        from .models import Announcement

        if publish_at is None:
            publish_at = timezone.now()

        announcement = Announcement.objects.create(
            school=school,
            sender=sender,
            title=title,
            content=content,
            audience=audience,
            priority=priority,
            publish_at=publish_at,
            expires_at=expires_at,
            is_published=True if publish_at <= timezone.now() else False
        )

        return announcement