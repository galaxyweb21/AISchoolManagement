"""Attendance notification helpers for parents and students.

One notification is maintained per attendance record and recipient.
The notification always reflects the current attendance status.
"""
import logging
from django.utils.timezone import localdate
from communication.models import NotificationCategory, NotificationChannel, NotificationLog
from communication.services import NotificationService

logger = logging.getLogger(__name__)

TRACKED_STATUSES = {"PRESENT", "LATE", "ABSENT"}


def _recipients(attendance):
    student = getattr(attendance, "student", None)
    if not student:
        return []
    result=[]
    parent=getattr(student,"parent",None)
    student_user=getattr(student,"user",None)
    if parent and getattr(parent,"is_active",True): result.append(parent)
    if student_user and getattr(student_user,"is_active",True) and (not parent or parent.pk != student_user.pk): result.append(student_user)
    return result


def _status_copy(attendance):
    student=attendance.student
    try: name=student.user.get_full_name().strip()
    except Exception: name=""
    name=name or getattr(student,"admission_number",None) or "Student"
    cls=getattr(getattr(student,"school_class",None),"name",None) or "their class"
    date_label=attendance.date.strftime("%d %B %Y")
    status=str(attendance.status or "").upper()
    if status == "ABSENT":
        subject=f"Attendance Alert: {name} absent"
        message=f"Attendance alert for {name}. The student was marked absent on {date_label} from {cls}. Please review the attendance record."
    elif status == "LATE":
        subject=f"Attendance Update: {name} late"
        message=f"Attendance update for {name}. The student was marked late on {date_label} in {cls}."
    else:
        subject=f"Attendance Update: {name} present"
        message=f"Attendance update for {name}. The student was marked present on {date_label} in {cls}."
    return subject,message


def notify_attendance(attendance):
    """Replace the notification for this attendance record with its current status."""
    if not attendance or attendance.status not in TRACKED_STATUSES:
        return []
    school=getattr(attendance,"school",None)
    if not school or not getattr(attendance,"student",None): return []
    # Remove only notifications for this exact attendance record. This makes a status change atomic from the UI perspective.
    NotificationLog.objects.filter(category=NotificationCategory.ATTENDANCE_ALERT, reference_type="Attendance", reference_id=str(attendance.id)).delete()
    subject,message=_status_copy(attendance)
    created=[]
    for recipient in _recipients(attendance):
        try:
            created.append(NotificationService.trigger(recipient=recipient,category=NotificationCategory.ATTENDANCE_ALERT,subject=subject,message=message,channel=NotificationChannel.IN_APP,reference_id=str(attendance.id),reference_type="Attendance",school=school))
        except Exception:
            logger.exception("Failed to create attendance notification for %s", getattr(recipient,"pk",None))
    return created


def notify_absence(attendance):
    """Backward-compatible wrapper used by older attendance code."""
    if attendance and attendance.status == "ABSENT": return notify_attendance(attendance)
    return []


def clear_absence_notification(attendance):
    if not attendance: return 0
    return NotificationLog.objects.filter(category=NotificationCategory.ATTENDANCE_ALERT,reference_type="Attendance",reference_id=str(attendance.id)).delete()[0]


def sync_attendance_notifications_for_user(user):
    from attendance.models import Attendance
    role=str(getattr(user,"role","") or "").strip().upper()
    if role not in {"PARENT","STUDENT"}: return []
    today=localdate()
    if role=="PARENT": qs=Attendance.objects.filter(student__parent=user,date=today,status__in=TRACKED_STATUSES)
    else: qs=Attendance.objects.filter(student__user=user,date=today,status__in=TRACKED_STATUSES)
    qs=qs.select_related("student","student__user","student__school_class","school").order_by("-date","-id")
    created=[]
    for attendance in qs:
        # Only create if no current notification exists; status changes are handled by the save path.
        if not NotificationLog.objects.filter(recipient=user,category=NotificationCategory.ATTENDANCE_ALERT,reference_type="Attendance",reference_id=str(attendance.id)).exists():
            created.extend(notify_attendance(attendance))
    return created


def sync_absence_notifications_for_user(user):
    return sync_attendance_notifications_for_user(user)


def cleanup_invalid_attendance_notifications_for_user(user):
    """Remove stale attendance notifications and leave current PRESENT/LATE/ABSENT alerts."""
    from attendance.models import Attendance
    role=str(getattr(user,"role","") or "").strip().upper()
    if role not in {"PARENT","STUDENT"}: return 0
    alerts=list(NotificationLog.objects.filter(recipient=user,category=NotificationCategory.ATTENDANCE_ALERT,reference_type="Attendance").only("id","reference_id"))
    ids=[a.reference_id for a in alerts if a.reference_id]
    if role=="PARENT": valid=set(str(x) for x in Attendance.objects.filter(id__in=ids,student__parent=user,status__in=TRACKED_STATUSES).values_list("id",flat=True))
    else: valid=set(str(x) for x in Attendance.objects.filter(id__in=ids,student__user=user,status__in=TRACKED_STATUSES).values_list("id",flat=True))
    stale=[a.id for a in alerts if not a.reference_id or str(a.reference_id) not in valid]
    return NotificationLog.objects.filter(id__in=stale).delete()[0] if stale else 0
