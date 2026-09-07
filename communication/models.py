# communication/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from school.models import School
from staff.models import StaffProfile
from students.models import *
from django.contrib.auth import get_user_model
import uuid

User = get_user_model()


class Announcement(models.Model):
    """
    School-wide announcements and circulars.
    """
    AUDIENCE_CHOICES = (
        ('ALL', 'All Personnel & Parents'),
        ('TEACHERS', 'Faculty & Staff Only'),
        ('PARENTS', 'Parents Only'),
        ('STUDENTS', 'Students Only'),
        ('STAFF', 'Staff Only'),
        ('ADMIN', 'Administrators Only'),
    )

    PRIORITY_CHOICES = (
        ('LOW', 'Low'),
        ('NORMAL', 'Normal'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='announcements')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_announcements')

    title = models.CharField(max_length=255, help_text="e.g., Parent-Teacher Association Meeting")
    content = models.TextField(help_text="Detailed announcement content")
    summary = models.CharField(max_length=500, blank=True, null=True, help_text="Short summary for preview")

    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default='ALL')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='NORMAL')

    # Scheduling
    publish_at = models.DateTimeField(default=timezone.now, help_text="When to publish this announcement")
    expires_at = models.DateTimeField(null=True, blank=True, help_text="When this announcement expires")
    is_published = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)

    # Tracking
    views_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-publish_at', '-created_at']
        indexes = [
            models.Index(fields=['school', 'is_published']),
            models.Index(fields=['school', 'audience']),
            models.Index(fields=['publish_at', 'expires_at']),
        ]

    def __str__(self):
        return f"{self.title} - {self.school.name}"

    @property
    def is_active(self):
        """Check if announcement is currently active."""
        now = timezone.now()
        return (
                self.is_published and
                self.publish_at <= now and
                (not self.expires_at or self.expires_at > now) and
                not self.is_archived
        )

    @property
    def days_until_expiry(self):
        """Get days until expiry."""
        if not self.expires_at:
            return None
        delta = self.expires_at - timezone.now()
        return max(0, delta.days)


class NotificationCategory(models.TextChoices):
    """System notification categories."""
    OVERDUE_BALANCE = 'OVERDUE_BALANCE', 'Overdue Balance'
    TIMETABLE_UPDATE = 'TIMETABLE_UPDATE', 'Timetable Update'
    GRADE_RELEASE = 'GRADE_RELEASE', 'Grade Release'
    ANNOUNCEMENT = 'ANNOUNCEMENT', 'Announcement'
    PAYMENT_RECEIPT = 'PAYMENT_RECEIPT', 'Payment Receipt'
    ATTENDANCE_ALERT = 'ATTENDANCE_ALERT', 'Attendance Alert'
    PROMOTION_RESULT = 'PROMOTION_RESULT', 'Promotion Result'
    SYSTEM_ALERT = 'SYSTEM_ALERT', 'System Alert'
    LEAVE_APPROVAL = 'LEAVE_APPROVAL', 'Leave Approval'
    STAFF_REMINDER = 'STAFF_REMINDER', 'Staff Reminder'


class NotificationChannel(models.TextChoices):
    """Available notification channels."""
    EMAIL = 'EMAIL', 'Email'
    SMS = 'SMS', 'SMS'
    IN_APP = 'IN_APP', 'In-App'
    BOTH = 'BOTH', 'Email & SMS'
    ALL = 'ALL', 'All Channels'


class NotificationStatus(models.TextChoices):
    """Notification delivery status."""
    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    SENT = 'SENT', 'Sent'
    DELIVERED = 'DELIVERED', 'Delivered'
    FAILED = 'FAILED', 'Failed'
    READ = 'READ', 'Read'


class NotificationLog(models.Model):
    """
    Tracks all notifications sent through the system.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='notification_logs', null=True)
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='sent_notifications')

    category = models.CharField(max_length=30, choices=NotificationCategory.choices)
    channel = models.CharField(max_length=10, choices=NotificationChannel.choices, default=NotificationChannel.EMAIL)

    subject = models.CharField(max_length=255)
    message = models.TextField()

    status = models.CharField(max_length=10, choices=NotificationStatus.choices, default=NotificationStatus.PENDING)
    error_message = models.TextField(blank=True, null=True)

    # Tracking
    sent_at = models.DateTimeField(blank=True, null=True)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Related reference
    reference_id = models.CharField(max_length=100, blank=True, null=True,
                                    help_text="Reference to related object (invoice_id, leave_id, etc.)")
    reference_type = models.CharField(max_length=50, blank=True, null=True,
                                      help_text="Type of reference (invoice, leave, etc.)")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'status']),
            models.Index(fields=['school', 'created_at']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f"{self.category} → {self.recipient.username} [{self.status}]"

    def mark_as_read(self):
        """Mark notification as read."""
        self.status = NotificationStatus.READ
        self.read_at = timezone.now()
        self.save(update_fields=['status', 'read_at'])


class UserNotificationPreference(models.Model):
    """
    User preferences for notification channels.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='notification_preferences')
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preferences')

    # Channel preferences
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    in_app_enabled = models.BooleanField(default=True)

    # Category preferences
    overdue_balance_enabled = models.BooleanField(default=True)
    timetable_update_enabled = models.BooleanField(default=True)
    grade_release_enabled = models.BooleanField(default=True)
    announcement_enabled = models.BooleanField(default=True)
    attendance_alert_enabled = models.BooleanField(default=True)
    promotion_result_enabled = models.BooleanField(default=True)
    leave_approval_enabled = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['school', 'user']
        verbose_name_plural = 'User Notification Preferences'

    def __str__(self):
        return f"{self.user.username} - Notification Preferences"