"""Attendance notification helpers.

Phase 1E: same-day absence alerts for linked parents/students.
No database migration is required.
"""

import logging

from communication.models import NotificationCategory, NotificationChannel, NotificationLog
from communication.services import NotificationService

logger = logging.getLogger(__name__)


def notify_absence(attendance):
    """Create one idempotent in-app absence alert per recipient/date."""
    if not attendance or attendance.status != "ABSENT":
        return []

    student = getattr(attendance, "student", None)
    school = getattr(attendance, "school", None)
    if not student or not school:
        return []

    recipients = []
    parent = getattr(student, "parent", None)
    student_user = getattr(student, "user", None)

    if parent and getattr(parent, "is_active", True):
        recipients.append(parent)
    if student_user and getattr(student_user, "is_active", True):
        if not parent or parent.pk != student_user.pk:
            recipients.append(student_user)

    full_name = ""
    try:
        full_name = student.user.get_full_name().strip()
    except Exception:
        pass
    full_name = full_name or getattr(student, "admission_number", None) or "Student"

    class_name = getattr(getattr(student, "school_class", None), "name", None) or "their class"
    date_label = attendance.date.strftime("%d %B %Y")

    subject = f"Attendance Alert: {full_name} absent"
    message = (
        f"Attendance alert for {full_name}. "
        f"The student was marked absent on {date_label} "
        f"from {class_name}. Please review the attendance record."
    )

    created_logs = []
    for recipient in recipients:
        try:
            exists = NotificationLog.objects.filter(
                recipient=recipient,
                category=NotificationCategory.ATTENDANCE_ALERT,
                reference_type="Attendance",
                reference_id=str(attendance.id),
            ).exists()
            if exists:
                continue

            log = NotificationService.trigger(
                recipient=recipient,
                category=NotificationCategory.ATTENDANCE_ALERT,
                subject=subject,
                message=message,
                channel=NotificationChannel.IN_APP,
                reference_id=str(attendance.id),
                reference_type="Attendance",
                school=school,
            )
            created_logs.append(log)
        except Exception:
            logger.exception(
                "Failed to create attendance alert for recipient %s",
                getattr(recipient, "pk", None),
            )

    return created_logs


def sync_absence_notifications_for_user(user):
    """Backfill missing absence alerts for a parent or student.

    This covers absences recorded before the notification hook was installed
    and absences recorded through alternate capture workflows. Phase 1E is a
    same-day alert feature, so only today's ABSENT records are synchronized.
    Historical attendance must not be turned into new notification alerts.
    """
    from attendance.models import Attendance

    role = str(getattr(user, "role", "") or "").strip().upper()
    if role not in {"PARENT", "STUDENT"}:
        return []

    # Do not depend on user.school here. The Student -> parent/user link is
    # the authoritative relationship and is also what protects the query.
    # This makes the sync work with existing demo records even if an older
    # parent account was created without the expected school FK populated.
    from django.utils.timezone import localdate

    today = localdate()

    if role == "PARENT":
        records = (
            Attendance.objects
            .filter(student__parent=user, status="ABSENT", date=today)
            .select_related("student", "student__user", "student__school_class", "school")
            .order_by("-id")
        )
    else:
        records = (
            Attendance.objects
            .filter(student__user=user, status="ABSENT", date=today)
            .select_related("student", "student__user", "student__school_class", "school")
            .order_by("-id")
        )

    # Remove stale Phase 1E attendance alerts. Attendance alerts represent the
    # current day's absence status; they must never make an old ABSENT record
    # look like a new absence after the student has subsequently been marked
    # PRESENT/LATE/EXCUSED.
    stale_logs = NotificationLog.objects.filter(
        recipient=user,
        category=NotificationCategory.ATTENDANCE_ALERT,
        reference_type="Attendance",
    )
    for log in stale_logs.only("id", "reference_id"):
        attendance = Attendance.objects.filter(id=log.reference_id).only("date", "status").first()
        if not attendance or attendance.date != today or attendance.status != "ABSENT":
            log.delete()

    created = []
    for attendance in records:
        created.extend(notify_absence(attendance))
    return created
