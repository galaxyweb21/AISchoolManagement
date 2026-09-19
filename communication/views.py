from core.pagination import paginate_queryset
# communication/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _parse_announcement_datetime(value, field_name):
    """Parse datetime-local/ISO input and return a timezone-aware datetime."""
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except (TypeError, ValueError):
            raise ValueError(f'Invalid {field_name}. Please use a valid date and time.')
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(timezone.get_current_timezone())


def _admin_announcement_required(request):
    return getattr(request.user, 'role', None) in ['SUPER_ADMIN', 'SCHOOL_ADMIN']

from .models import Announcement, NotificationLog, NotificationStatus, UserNotificationPreference, NotificationCategory
from .services import NotificationService, AnnouncementService


@login_required
def communication_inbox(request):
    """
    Renders the central bulletin notice feed board for the active user's tenant school.
    """
    school = request.user.school
    if not school:
        messages.error(request, "No school associated with your account.")
        return redirect('dashboard')

    # Publish due scheduled announcements for this school as a safe local/demo fallback.
    try:
        AnnouncementService.publish_due_announcements(school=school)
    except Exception:
        logger.exception('Scheduled announcement sync failed for school %s', school.pk)

    # Get announcements for user
    announcements = AnnouncementService.get_announcements_for_user(request.user)

    # Pagination
    page_obj = paginate_queryset(announcements, request)
    paginator = page_obj.paginator

    # Get unread notification count
    unread_count = NotificationLog.objects.filter(
        recipient=request.user,
        status=NotificationStatus.DELIVERED
    ).count()

    context = {
        'announcements': page_obj,
        'audience_choices': Announcement.AUDIENCE_CHOICES,
        'priority_choices': Announcement.PRIORITY_CHOICES,
        'unread_count': unread_count,
        'is_admin': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
        'active_tab': 'communication'
    }
    return render(request, 'communication/inbox.html', context)


@login_required
@require_POST
def api_post_announcement(request):
    """Create an immediate or scheduled school announcement."""
    if not _admin_announcement_required(request):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body or '{}')
        title = str(data.get('title') or '').strip()
        content = str(data.get('content') or '').strip()
        audience = str(data.get('audience') or 'ALL').strip().upper()
        priority = str(data.get('priority') or 'NORMAL').strip().upper()

        if not title or not content:
            return JsonResponse({
                'success': False,
                'error': 'Title and content fields are required.'
            }, status=400)

        school = getattr(request.user, 'school', None)
        if not school:
            return JsonResponse({
                'success': False,
                'error': 'No school associated with your account.'
            }, status=400)

        publish_date = _parse_announcement_datetime(data.get('publish_at'), 'publish date')
        expire_date = _parse_announcement_datetime(data.get('expires_at'), 'expiry date')

        if expire_date is not None and publish_date is not None and expire_date <= publish_date:
            return JsonResponse({
                'success': False,
                'error': 'Expiry date must be later than the publish date.'
            }, status=400)

        announcement = AnnouncementService.create_announcement(
            school=school,
            sender=request.user,
            title=title,
            content=content,
            audience=audience,
            priority=priority,
            publish_at=publish_date,
            expires_at=expire_date,
        )

        return JsonResponse({
            'success': True,
            'id': str(announcement.id),
            'title': announcement.title,
            'created_at': announcement.created_at.strftime('%b %d, %Y'),
            'is_published': announcement.is_published,
            'message': (
                'Announcement published successfully.'
                if announcement.is_published
                else 'Announcement scheduled successfully.'
            )
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'}, status=400)
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.exception('Announcement creation failed')
        return JsonResponse({
            'success': False,
            'error': 'Unable to save the announcement. Please try again.'
        }, status=400)


@login_required
def announcement_management(request):
    """Admin-only announcement management workspace."""
    if not _admin_announcement_required(request):
        messages.error(request, 'You do not have permission to manage announcements.')
        return redirect('communication:inbox')

    school = getattr(request.user, 'school', None)
    if not school:
        messages.error(request, 'No school associated with your account.')
        return redirect('dashboard:dashboard')

    AnnouncementService.publish_due_announcements(school=school)
    now = timezone.now()
    qs = Announcement.objects.filter(school=school).select_related('sender').order_by('-publish_at', '-created_at')

    query = (request.GET.get('q') or '').strip()
    status = (request.GET.get('status') or 'all').strip().lower()
    priority = (request.GET.get('priority') or '').strip().upper()

    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(content__icontains=query))
    if priority in {v for v, _ in Announcement.PRIORITY_CHOICES}:
        qs = qs.filter(priority=priority)
    if status == 'published':
        qs = qs.filter(is_published=True, is_archived=False, publish_at__lte=now).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
    elif status == 'scheduled':
        qs = qs.filter(is_published=False, is_archived=False, publish_at__gt=now)
    elif status == 'expired':
        qs = qs.filter(is_published=True, expires_at__isnull=False, expires_at__lte=now)
    elif status == 'archived':
        qs = qs.filter(is_archived=True)

    total_count = Announcement.objects.filter(school=school).count()
    published_count = Announcement.objects.filter(
        school=school, is_published=True, is_archived=False, publish_at__lte=now
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).count()
    scheduled_count = Announcement.objects.filter(
        school=school, is_published=False, is_archived=False, publish_at__gt=now
    ).count()
    expired_count = Announcement.objects.filter(
        school=school, is_published=True, expires_at__isnull=False, expires_at__lte=now
    ).count()
    archived_count = Announcement.objects.filter(school=school, is_archived=True).count()

    page_obj = paginate_queryset(qs, request)
    return render(request, 'communication/announcement_management.html', {
        'announcements': page_obj,
        'priority_choices': Announcement.PRIORITY_CHOICES,
        'total_count': total_count,
        'published_count': published_count,
        'scheduled_count': scheduled_count,
        'expired_count': expired_count,
        'archived_count': archived_count,
        'query': query,
        'status': status,
        'priority': priority,
        'now': now,
        'active_tab': 'communication',
    })


@login_required
@require_POST
def announcement_publish(request, announcement_id):
    """Publish a scheduled announcement immediately and notify recipients."""
    if not _admin_announcement_required(request):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    announcement = get_object_or_404(Announcement, id=announcement_id, school=request.user.school)
    announcement.is_archived = False
    announcement.is_published = True
    announcement.publish_at = timezone.now()
    announcement.save(update_fields=['is_archived', 'is_published', 'publish_at', 'updated_at'])
    created = AnnouncementService.notify_announcement(announcement)
    return JsonResponse({'success': True, 'message': f'Announcement published. {created} notification(s) created.'})


@login_required
@require_POST
def announcement_update(request, announcement_id):
    """Update an announcement using JSON from the management editor."""
    if not _admin_announcement_required(request):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    announcement = get_object_or_404(Announcement, id=announcement_id, school=request.user.school)
    try:
        data = json.loads(request.body or '{}')
        publish_at = _parse_announcement_datetime(data.get('publish_at'), 'publish date')
        expires_at = _parse_announcement_datetime(data.get('expires_at'), 'expiry date')
        # An empty expiry means remove the expiry date.
        if data.get('expires_at') in (None, ''):
            expires_at = None
            if 'expires_at' in data and publish_at is None:
                # handled below by retaining the current publish date
                pass
        if publish_at is None and 'publish_at' in data:
            publish_at = announcement.publish_at
        if expires_at is not None and expires_at <= publish_at:
            raise ValueError('Expiry date must be later than the publish date.')
        AnnouncementService.update_announcement(
            announcement,
            title=data.get('title'),
            content=data.get('content'),
            audience=data.get('audience'),
            priority=data.get('priority'),
            publish_at=publish_at,
            expires_at=expires_at,
        )
        return JsonResponse({'success': True, 'message': 'Announcement updated successfully.'})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'}, status=400)
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception:
        logger.exception('Announcement update failed')
        return JsonResponse({'success': False, 'error': 'Unable to update the announcement.'}, status=400)


@login_required
@require_POST
def announcement_delete(request, announcement_id):
    """Permanently delete an announcement belonging to the current school."""
    if not _admin_announcement_required(request):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    announcement = get_object_or_404(Announcement, id=announcement_id, school=request.user.school)
    NotificationLog.objects.filter(
        school=announcement.school,
        category=NotificationCategory.ANNOUNCEMENT,
        reference_id=str(announcement.id),
        reference_type='announcement',
    ).delete()
    announcement.delete()
    return JsonResponse({'success': True, 'message': 'Announcement and its related notifications were deleted successfully.'})


@login_required
def announcement_detail(request, announcement_id):
    """View a single announcement."""
    school = request.user.school
    announcement = get_object_or_404(Announcement, id=announcement_id, school=school)

    # Increment view count
    announcement.views_count += 1
    announcement.save(update_fields=['views_count'])

    context = {
        'announcement': announcement,
        'active_tab': 'communication'
    }
    return render(request, 'communication/announcement_detail.html', context)


@login_required
@require_POST
def announcement_toggle_archive(request, announcement_id):
    """Archive or unarchive an announcement."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    school = request.user.school
    announcement = get_object_or_404(Announcement, id=announcement_id, school=school)
    announcement.is_archived = not announcement.is_archived
    announcement.save(update_fields=['is_archived'])

    status = 'archived' if announcement.is_archived else 'unarchived'
    return JsonResponse({
        'success': True,
        'message': f'Announcement {status} successfully.',
        'is_archived': announcement.is_archived
    })


@login_required
@require_GET
def notification_list(request):
    """Return the current user's latest notifications for the navbar dropdown."""
    try:
        AnnouncementService.publish_due_announcements(school=getattr(request.user, 'school', None))
    except Exception:
        logger.exception('Scheduled announcement notification sync failed for user %s', request.user.pk)

    # Keep the navbar bell in sync with attendance alerts as well as the full
    # Notification Center. This is idempotent and only creates missing alerts.
    if getattr(request.user, 'role', None) in ['PARENT', 'STUDENT']:
        try:
            from attendance.services.notifications import cleanup_invalid_attendance_notifications_for_user
            cleanup_invalid_attendance_notifications_for_user(request.user)
        except Exception:
            logger.exception('Attendance notification cleanup failed for user %s', request.user.pk)
        try:
            from attendance.services.notifications import sync_attendance_notifications_for_user
            sync_attendance_notifications_for_user(request.user)
        except Exception:
            logger.exception('Attendance notification bell sync failed for user %s', request.user.pk)

    notifications = (
        NotificationLog.objects
        .filter(recipient=request.user)
        .select_related('sender')
        .order_by('-created_at')[:50]
    )

    unread_count = NotificationLog.objects.filter(
        recipient=request.user,
        status=NotificationStatus.DELIVERED,
    ).count()

    data = [{
        'id': str(n.id),
        'subject': n.subject,
        'message': n.message[:200],
        'category': n.get_category_display(),
        'category_code': n.category,
        'created_at': n.created_at.isoformat(),
        'is_read': n.status == NotificationStatus.READ,
        'status': n.status,
        'reference_id': n.reference_id,
        'reference_type': n.reference_type,
    } for n in notifications]

    return JsonResponse({
        'success': True,
        'notifications': data,
        'unread_count': unread_count,
    })


@login_required
@require_GET
def notification_center(request):
    """Full notification center for the authenticated user's notifications."""
    try:
        AnnouncementService.publish_due_announcements(school=getattr(request.user, 'school', None))
    except Exception:
        logger.exception('Scheduled announcement center sync failed for user %s', request.user.pk)

    # Backfill promotion-result notifications for existing promotion records.
    # This makes older promotion batches visible to parents/students without
    # requiring the administrator to re-run the promotion process.
    if getattr(request.user, 'role', None) in ['PARENT', 'STUDENT']:
        try:
            from academics.services.promotion_service import PromotionService
            PromotionService.sync_promotion_notifications_for_user(request.user)
        except Exception:
            logger.exception('Promotion notification sync failed for user %s', request.user.pk)

    # Reconcile attendance alerts against the authoritative attendance record
    # before loading the page. A PRESENT/LATE/EXCUSED record must never be
    # represented by an old ABSENT notification.
    if getattr(request.user, 'role', None) in ['PARENT', 'STUDENT']:
        try:
            from attendance.services.notifications import cleanup_invalid_attendance_notifications_for_user
            cleanup_invalid_attendance_notifications_for_user(request.user)
        except Exception:
            logger.exception('Attendance notification cleanup failed for user %s', request.user.pk)

    # Backfill today's attendance alerts so parents/students also see absences
    # recorded before the notification hook or through face/live capture.
    # The sync intentionally ignores historical attendance records.
    if getattr(request.user, 'role', None) in ['PARENT', 'STUDENT']:
        try:
            from attendance.services.notifications import sync_attendance_notifications_for_user
            sync_attendance_notifications_for_user(request.user)
        except Exception:
            logger.exception('Attendance notification sync failed for user %s', request.user.pk)

    notifications = NotificationLog.objects.filter(
        recipient=request.user
    ).select_related('sender')

    search = (request.GET.get('search') or '').strip()
    category = (request.GET.get('category') or '').strip()
    status = (request.GET.get('status') or '').strip().upper()

    if search:
        notifications = notifications.filter(
            Q(subject__icontains=search) |
            Q(message__icontains=search) |
            Q(category__icontains=search)
        )

    valid_categories = {value for value, _label in NotificationCategory.choices}
    if category in valid_categories:
        notifications = notifications.filter(category=category)
    else:
        category = ''

    if status == 'UNREAD':
        notifications = notifications.filter(status=NotificationStatus.DELIVERED)
    elif status == 'READ':
        notifications = notifications.filter(status=NotificationStatus.READ)
    else:
        status = ''

    total_count = NotificationLog.objects.filter(recipient=request.user).count()
    unread_count = NotificationLog.objects.filter(
        recipient=request.user, status=NotificationStatus.DELIVERED
    ).count()
    read_count = NotificationLog.objects.filter(
        recipient=request.user, status=NotificationStatus.READ
    ).count()

    page_obj = paginate_queryset(notifications.order_by('-created_at'), request)

    for notification in page_obj.object_list:
        notification.action_url = None
        if notification.category == NotificationCategory.PAYMENT_RECEIPT and notification.reference_id:
            try:
                notification.action_url = reverse('finance:payment_receipt', args=[notification.reference_id])
            except Exception:
                notification.action_url = None
        elif notification.category == NotificationCategory.GRADE_RELEASE and notification.reference_id:
            try:
                notification.action_url = reverse('ai_engine:report_card_detail', args=[notification.reference_id])
            except Exception:
                notification.action_url = None
        elif notification.category == NotificationCategory.PROMOTION_RESULT and notification.reference_id:
            try:
                notification.action_url = reverse('academics:promotion_result_detail', args=[notification.reference_id])
            except Exception:
                notification.action_url = None
        elif notification.category == NotificationCategory.ATTENDANCE_ALERT and notification.reference_id:
            try:
                from attendance.models import Attendance
                attendance_qs = Attendance.objects.filter(id=notification.reference_id)
                if getattr(request.user, 'role', None) == 'PARENT':
                    attendance_qs = attendance_qs.filter(student__parent=request.user)
                elif getattr(request.user, 'role', None) == 'STUDENT':
                    attendance_qs = attendance_qs.filter(student__user=request.user)
                else:
                    attendance_qs = attendance_qs.filter(school=getattr(request.user, 'school', None))
                attendance = attendance_qs.first()
                if attendance:
                    notification.action_url = reverse('attendance:student_attendance_history', args=[attendance.student_id])
            except Exception:
                notification.action_url = None

    context = {
        'notifications': page_obj,
        'total_count': total_count,
        'unread_count': unread_count,
        'read_count': read_count,
        'category_choices': NotificationCategory.choices,
        'selected_category': category,
        'selected_status': status,
        'search': search,
        'active_tab': 'communication',
    }
    return render(request, 'communication/notification_center.html', context)


@login_required
@require_POST
def notification_mark_read(request, notification_id):
    """Mark one of the current user's notifications as read."""
    notification = get_object_or_404(
        NotificationLog,
        id=notification_id,
        recipient=request.user,
    )
    notification.mark_as_read()

    unread_count = NotificationLog.objects.filter(
        recipient=request.user,
        status=NotificationStatus.DELIVERED,
    ).count()

    return JsonResponse({
        'success': True,
        'message': 'Notification marked as read.',
        'notification_id': str(notification.id),
        'unread_count': unread_count,
    })


@login_required
@require_POST
def notification_mark_all_read(request):
    """Mark all currently unread in-app notifications as read."""
    now = timezone.now()
    updated = NotificationLog.objects.filter(
        recipient=request.user,
        status=NotificationStatus.DELIVERED,
    ).update(
        status=NotificationStatus.READ,
        read_at=now,
    )

    return JsonResponse({
        'success': True,
        'message': 'All notifications marked as read.',
        'updated': updated,
        'unread_count': 0,
    })


# communication/views.py - Fixed notification_preferences view

@login_required
def notification_preferences(request):
    """View and update notification preferences."""
    school = request.user.school
    if not school:
        messages.error(request, "No school associated with your account.")
        return redirect('dashboard')

    preferences, created = UserNotificationPreference.objects.get_or_create(
        school=school,
        user=request.user
    )

    if request.method == 'POST':
        # Get all checkbox values - if checkbox is checked, it sends 'on', if not, it's not in the POST data
        # So we check if the key exists in POST data
        email_enabled = request.POST.get('email_enabled') == 'on'
        sms_enabled = request.POST.get('sms_enabled') == 'on'
        in_app_enabled = request.POST.get('in_app_enabled') == 'on'

        # Category preferences
        overdue_balance_enabled = request.POST.get('overdue_balance_enabled') == 'on'
        timetable_update_enabled = request.POST.get('timetable_update_enabled') == 'on'
        grade_release_enabled = request.POST.get('grade_release_enabled') == 'on'
        announcement_enabled = request.POST.get('announcement_enabled') == 'on'
        attendance_alert_enabled = request.POST.get('attendance_alert_enabled') == 'on'
        promotion_result_enabled = request.POST.get('promotion_result_enabled') == 'on'
        leave_approval_enabled = request.POST.get('leave_approval_enabled') == 'on'
        payment_receipt_enabled = request.POST.get('payment_receipt_enabled') == 'on'
        system_alert_enabled = request.POST.get('system_alert_enabled') == 'on'
        staff_reminder_enabled = request.POST.get('staff_reminder_enabled') == 'on'

        # Update channel preferences
        preferences.email_enabled = email_enabled
        preferences.sms_enabled = sms_enabled
        preferences.in_app_enabled = in_app_enabled

        # Update category preferences
        preferences.overdue_balance_enabled = overdue_balance_enabled
        preferences.timetable_update_enabled = timetable_update_enabled
        preferences.grade_release_enabled = grade_release_enabled
        preferences.announcement_enabled = announcement_enabled
        preferences.attendance_alert_enabled = attendance_alert_enabled
        preferences.promotion_result_enabled = promotion_result_enabled
        preferences.leave_approval_enabled = leave_approval_enabled
        preferences.payment_receipt_enabled = payment_receipt_enabled
        preferences.system_alert_enabled = system_alert_enabled
        preferences.staff_reminder_enabled = staff_reminder_enabled

        preferences.save()

        # Check if AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Notification preferences updated successfully.',
                'data': {
                    'email_enabled': preferences.email_enabled,
                    'sms_enabled': preferences.sms_enabled,
                    'in_app_enabled': preferences.in_app_enabled,
                    'overdue_balance_enabled': preferences.overdue_balance_enabled,
                    'timetable_update_enabled': preferences.timetable_update_enabled,
                    'grade_release_enabled': preferences.grade_release_enabled,
                    'announcement_enabled': preferences.announcement_enabled,
                    'attendance_alert_enabled': preferences.attendance_alert_enabled,
                    'promotion_result_enabled': preferences.promotion_result_enabled,
                    'leave_approval_enabled': preferences.leave_approval_enabled,
                    'payment_receipt_enabled': preferences.payment_receipt_enabled,
                    'system_alert_enabled': preferences.system_alert_enabled,
                    'staff_reminder_enabled': preferences.staff_reminder_enabled,
                }
            })

        messages.success(request, "Notification preferences updated successfully.")
        return redirect('communication:notification_preferences')

    context = {
        'preferences': preferences,
        'active_tab': 'communication'
    }
    return render(request, 'communication/notification_preferences.html', context)


@login_required
@user_passes_test(lambda u: u.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'])
def notification_log_list(request):
    """View notification logs (admin only)."""
    school = request.user.school

    # ---------------------------------------------------------
    # BASE QUERYSET (school-scoped)
    # ---------------------------------------------------------
    base_qs = NotificationLog.objects.filter(
        school=school
    ).select_related('recipient', 'sender')

    # ---------------------------------------------------------
    # KPI COUNTS
    #
    # Counts are computed on the school-scoped queryset so the
    # KPI cards remain a stable, school-wide overview regardless
    # of the active filter.
    #
    # We build a per-status dict with ALL NotificationStatus
    # values so the template can iterate over the full pipeline.
    #
    # We also expose the legacy variables (total_logs,
    # sent_count, pending_count, failed_count) so nothing else
    # in the project that references them breaks.
    # ---------------------------------------------------------

    # Total (all statuses)
    total_logs = base_qs.count()

    # Per-status counts — one entry per NotificationStatus value
    kpi_counts = {}
    for status_value, status_label in NotificationStatus.choices:
        kpi_counts[status_value] = {
            'value': status_value,
            'label': status_label,
            'count': base_qs.filter(status=status_value).count(),
        }

    # Grouped KPIs for the four "headline" cards the template shows
    sent_count = (
        kpi_counts[NotificationStatus.SENT]['count']
        + kpi_counts[NotificationStatus.DELIVERED]['count']
    )
    pending_count = (
        kpi_counts[NotificationStatus.PENDING]['count']
        + kpi_counts[NotificationStatus.QUEUED]['count']
    )
    failed_count = kpi_counts[NotificationStatus.FAILED]['count']
    read_count = kpi_counts[NotificationStatus.READ]['count']

    # ---------------------------------------------------------
    # FILTERS (applied only to the table queryset)
    # ---------------------------------------------------------
    logs = base_qs

    status_filter = request.GET.get('status')
    if status_filter:
        logs = logs.filter(status=status_filter)

    category_filter = request.GET.get('category')
    if category_filter:
        logs = logs.filter(category=category_filter)

    search = request.GET.get('search')
    if search:
        logs = logs.filter(
            Q(subject__icontains=search) |
            Q(message__icontains=search) |
            Q(recipient__username__icontains=search) |
            Q(recipient__email__icontains=search)
        )

    # ---------------------------------------------------------
    # PAGINATION
    # ---------------------------------------------------------
    page_obj = paginate_queryset(logs, request)

    context = {
        'logs': page_obj,
        'status_choices': NotificationLog._meta.get_field('status').choices,
        'category_choices': NotificationLog._meta.get_field('category').choices,
        'selected_status': status_filter,
        'selected_category': category_filter,
        'search': search,

        # Full per-status breakdown (all NotificationStatus values)
        'kpi_counts': kpi_counts,

        # Legacy/grouped KPIs (kept for backwards compatibility)
        'total_logs': total_logs,
        'sent_count': sent_count,
        'pending_count': pending_count,
        'failed_count': failed_count,
        'read_count': read_count,

        'active_tab': 'communication',
    }
    return render(request, 'communication/log_list.html', context)
