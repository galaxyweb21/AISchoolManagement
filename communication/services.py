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
                NotificationCategory.PAYMENT_RECEIPT: prefs.payment_receipt_enabled,
                NotificationCategory.SYSTEM_ALERT: prefs.system_alert_enabled,
                NotificationCategory.STAFF_REMINDER: prefs.staff_reminder_enabled,
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
        Main public method to trigger a notification.

        When a stable reference is supplied, the notification is idempotent:
        the same recipient/category/reference combination is not created twice.
        Existing READ/DELIVERED notifications are preserved so a page refresh,
        backfill, signal retry, or scheduled task cannot turn one event into
        duplicate notifications.
        """
        if not recipient:
            return None

        # Use recipient's school if not provided.
        if not school:
            school = getattr(recipient, 'school', None)

        reference_id = str(reference_id) if reference_id is not None else None
        reference_type = str(reference_type).strip() if reference_type else None

        # Apply category preferences before creating an in-app notification.
        # This is important because IN_APP notifications do not pass through
        # the external dispatch worker.
        if not cls.should_send_notification(recipient, category):
            logger.info(
                'Notification suppressed by user preference: %s -> %s',
                category, getattr(recipient, 'username', recipient.pk)
            )
            return None

        # Stable references are used by attendance, payments, report cards,
        # promotions, overdue balances and announcements. Reuse the existing
        # row instead of creating another notification for the same event.
        if reference_id and reference_type:
            existing = (
                NotificationLog.objects
                .filter(
                    recipient=recipient,
                    category=category,
                    reference_id=reference_id,
                    reference_type=reference_type,
                )
                .order_by('-created_at')
                .first()
            )
            if existing:
                # Keep a notification that the user has already received/read.
                if existing.status in {
                    NotificationStatus.DELIVERED,
                    NotificationStatus.READ,
                    NotificationStatus.SENT,
                }:
                    return existing

                # A previous failed/pending attempt can safely be retried.
                existing.school = school or existing.school
                existing.sender = sender or existing.sender
                existing.channel = channel
                existing.subject = subject
                existing.message = message
                existing.status = NotificationStatus.QUEUED
                existing.error_message = None
                existing.save(update_fields=[
                    'school', 'sender', 'channel', 'subject', 'message',
                    'status', 'error_message'
                ])
                log = existing
            else:
                log = NotificationLog.objects.create(
                    school=school,
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
        else:
            # Reference-less notifications are intentionally not deduplicated:
            # each call represents a separate event.
            log = NotificationLog.objects.create(
                school=school,
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

        # In-app notifications are already stored in the database, so they are
        # immediately available to the Notification Center.
        if channel == NotificationChannel.IN_APP:
            log.status = NotificationStatus.DELIVERED
            log.sent_at = log.sent_at or timezone.now()
            log.error_message = None
            log.save(update_fields=['status', 'sent_at', 'error_message'])
            return log

        # Run external-channel dispatch in a daemon thread, preserving the
        # existing behavior used by the project.
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
    """School announcement creation, scheduling, visibility and delivery."""

    @staticmethod
    def _audience_roles(audience):
        """Return User.role values allowed to receive an announcement."""
        mapping = {
            'ALL': [
                'SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR', 'REGISTRAR',
                'HOD', 'SECRETARY', 'TEACHER', 'PARENT', 'STUDENT',
            ],
            'ADMIN': ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
            'TEACHERS': ['TEACHER', 'HOD'],
            'PARENTS': ['PARENT'],
            'STUDENTS': ['STUDENT'],
            'STAFF': [
                'BURSAR', 'REGISTRAR', 'HOD', 'SECRETARY', 'TEACHER',
            ],
        }
        return mapping.get(audience, mapping['ALL'])

    @staticmethod
    def get_recipient_queryset(announcement):
        """Return active users in the same school matching the audience."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.filter(
            school=announcement.school,
            is_active=True,
            role__in=AnnouncementService._audience_roles(announcement.audience),
        ).order_by('pk')

    @staticmethod
    def get_announcements_for_user(user):
        """Get currently visible announcements for a user's school and role."""
        school = getattr(user, 'school', None)
        if not school:
            return Announcement.objects.none()

        now = timezone.now()
        queryset = Announcement.objects.filter(
            school=school,
            is_published=True,
            is_archived=False,
            publish_at__lte=now,
        ).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

        role = getattr(user, 'role', None)
        audience_map = {
            'SUPER_ADMIN': ['ALL', 'ADMIN', 'STAFF'],
            'SCHOOL_ADMIN': ['ALL', 'ADMIN', 'STAFF'],
            'TEACHER': ['ALL', 'TEACHERS', 'STAFF'],
            'HOD': ['ALL', 'TEACHERS', 'STAFF'],
            'BURSAR': ['ALL', 'STAFF'],
            'REGISTRAR': ['ALL', 'STAFF'],
            'SECRETARY': ['ALL', 'STAFF'],
            'PARENT': ['ALL', 'PARENTS'],
            'STUDENT': ['ALL', 'STUDENTS'],
        }
        queryset = queryset.filter(audience__in=audience_map.get(role, ['ALL']))
        return queryset.order_by('-priority', '-publish_at')

    @classmethod
    def notify_announcement(cls, announcement):
        """Create idempotent in-app notifications for an already-published announcement."""
        if not announcement or not announcement.is_published or announcement.is_archived:
            return 0

        recipients = cls.get_recipient_queryset(announcement)
        created = 0
        subject = announcement.title
        message = announcement.content
        reference_id = str(announcement.id)
        reference_type = 'announcement'

        for recipient in recipients.iterator():
            # Respect the user's announcement preference and avoid duplicates.
            if not NotificationService.should_send_notification(
                recipient, NotificationCategory.ANNOUNCEMENT
            ):
                continue

            already_sent = NotificationLog.objects.filter(
                recipient=recipient,
                category=NotificationCategory.ANNOUNCEMENT,
                reference_id=reference_id,
                reference_type=reference_type,
            ).exists()
            if already_sent:
                continue

            NotificationService.trigger(
                recipient=recipient,
                category=NotificationCategory.ANNOUNCEMENT,
                subject=subject,
                message=message,
                channel=NotificationChannel.IN_APP,
                sender=announcement.sender,
                reference_id=reference_id,
                reference_type=reference_type,
                school=announcement.school,
            )
            created += 1

        return created

    @classmethod
    def publish_due_announcements(cls, school=None):
        """Publish due scheduled announcements and deliver their notifications."""
        now = timezone.now()
        queryset = Announcement.objects.filter(
            is_published=False,
            is_archived=False,
            publish_at__lte=now,
        )
        if school is not None:
            queryset = queryset.filter(school=school)

        published = 0
        notifications = 0
        for announcement in queryset.select_related('school', 'sender').order_by('publish_at'):
            announcement.is_published = True
            announcement.save(update_fields=['is_published', 'updated_at'])
            published += 1
            notifications += cls.notify_announcement(announcement)

        return {'published': published, 'notifications_created': notifications}

    @staticmethod
    def create_announcement(school, sender, title, content, audience='ALL',
                            priority='NORMAL', publish_at=None, expires_at=None):
        """Create an announcement with safe timezone handling and delivery."""
        now = timezone.now()

        if publish_at is None:
            publish_at = now
        elif timezone.is_naive(publish_at):
            publish_at = timezone.make_aware(publish_at, timezone.get_current_timezone())
        else:
            publish_at = publish_at.astimezone(timezone.get_current_timezone())

        if expires_at is not None:
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
            else:
                expires_at = expires_at.astimezone(timezone.get_current_timezone())
            if expires_at <= publish_at:
                raise ValueError('Expiry date must be later than the publish date.')

        valid_audiences = {value for value, _label in Announcement.AUDIENCE_CHOICES}
        valid_priorities = {value for value, _label in Announcement.PRIORITY_CHOICES}
        if audience not in valid_audiences:
            raise ValueError('Invalid announcement audience.')
        if priority not in valid_priorities:
            raise ValueError('Invalid announcement priority.')

        is_published = publish_at <= now
        announcement = Announcement.objects.create(
            school=school,
            sender=sender,
            title=title,
            content=content,
            audience=audience,
            priority=priority,
            publish_at=publish_at,
            expires_at=expires_at,
            is_published=is_published,
        )

        # Immediate announcements must notify recipients now. Scheduled
        # announcements are delivered only when they become due.
        if is_published:
            AnnouncementService.notify_announcement(announcement)

        return announcement

    @classmethod
    def update_announcement(cls, announcement, *, title=None, content=None,
                            audience=None, priority=None, publish_at=None,
                            expires_at=None):
        """Update an announcement and reconcile publication/notifications."""
        now = timezone.now()

        if title is not None:
            title = title.strip()
            if not title:
                raise ValueError('Title is required.')
            announcement.title = title
        if content is not None:
            content = content.strip()
            if not content:
                raise ValueError('Content is required.')
            announcement.content = content
        if audience is not None:
            if audience not in {v for v, _ in Announcement.AUDIENCE_CHOICES}:
                raise ValueError('Invalid announcement audience.')
            announcement.audience = audience
        if priority is not None:
            if priority not in {v for v, _ in Announcement.PRIORITY_CHOICES}:
                raise ValueError('Invalid announcement priority.')
            announcement.priority = priority
        if publish_at is not None:
            if timezone.is_naive(publish_at):
                publish_at = timezone.make_aware(publish_at, timezone.get_current_timezone())
            else:
                publish_at = publish_at.astimezone(timezone.get_current_timezone())
            announcement.publish_at = publish_at
        if expires_at is not None:
            if timezone.is_naive(expires_at):
                expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
            else:
                expires_at = expires_at.astimezone(timezone.get_current_timezone())
            if expires_at <= announcement.publish_at:
                raise ValueError('Expiry date must be later than the publish date.')
            announcement.expires_at = expires_at

        should_be_published = announcement.publish_at <= now
        if not announcement.is_archived:
            announcement.is_published = should_be_published

        announcement.save()
        if announcement.is_published and not announcement.is_archived:
            cls.notify_announcement(announcement)
        return announcement

