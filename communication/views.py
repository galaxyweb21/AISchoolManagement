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
from django.db.models import Q, Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime
import json
import logging

logger = logging.getLogger(__name__)

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
    """
    Asynchronously posts a new broadcast circular text bulletin.
    """
    try:
        data = json.loads(request.body)
        title = data.get('title', '').strip()
        content = data.get('content', '').strip()
        audience = data.get('audience', 'ALL')
        priority = data.get('priority', 'NORMAL')
        publish_at = data.get('publish_at')
        expires_at = data.get('expires_at')

        if not title or not content:
            return JsonResponse({
                'success': False,
                'error': 'Title and content fields are required.'
            }, status=400)

        school = request.user.school
        if not school:
            return JsonResponse({
                'success': False,
                'error': 'No school associated with your account.'
            }, status=400)

        # Parse browser datetime-local values safely. datetime-local sends
        # a naive datetime (no timezone offset), while timezone.now() is
        # timezone-aware when USE_TZ=True. Normalize both before any
        # comparisons so scheduled announcements work reliably.
        def parse_form_datetime(value):
            if not value:
                return None
            parsed = parse_datetime(str(value).strip())
            if parsed is None:
                raise ValueError('Invalid date/time value.')
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed

        publish_date = parse_form_datetime(publish_at)
        expire_date = parse_form_datetime(expires_at)

        now = timezone.now()
        if publish_date is not None and expire_date is not None and expire_date <= publish_date:
            return JsonResponse({
                'success': False,
                'error': 'Expiry date/time must be later than the publish date/time.'
            }, status=400)

        announcement = AnnouncementService.create_announcement(
            school=school,
            sender=request.user,
            title=title,
            content=content,
            audience=audience,
            priority=priority,
            publish_at=publish_date,
            expires_at=expire_date
        )

        return JsonResponse({
            'success': True,
            'id': str(announcement.id),
            'title': announcement.title,
            'created_at': announcement.created_at.strftime('%b %d, %Y'),
            'message': ('Announcement scheduled successfully.' if not announcement.is_published else 'Announcement published successfully.')
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


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
@user_passes_test(lambda u: u.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'])
def announcement_management(request):
    """Admin lifecycle view for school announcements, including scheduled items."""
    school = request.user.school
    if not school:
        messages.error(request, "No school associated with your account.")
        return redirect('dashboard')

    qs = Announcement.objects.filter(school=school).select_related('sender').order_by('-created_at')
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', 'all').strip().lower()
    priority = request.GET.get('priority', '').strip().upper()

    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(content__icontains=query))
    if priority:
        qs = qs.filter(priority=priority)

    now = timezone.now()
    if status == 'published':
        qs = qs.filter(is_published=True, is_archived=False, publish_at__lte=now).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )
    elif status == 'scheduled':
        qs = qs.filter(is_published=False, publish_at__gt=now, is_archived=False)
    elif status == 'expired':
        qs = qs.filter(is_published=True, expires_at__isnull=False, expires_at__lte=now)
    elif status == 'archived':
        qs = qs.filter(is_archived=True)

    page_obj = paginate_queryset(qs, request)
    all_qs = Announcement.objects.filter(school=school)
    context = {
        'announcements': page_obj,
        'total_count': all_qs.count(),
        'published_count': all_qs.filter(is_published=True, is_archived=False, publish_at__lte=now).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).count(),
        'scheduled_count': all_qs.filter(is_published=False, publish_at__gt=now, is_archived=False).count(),
        'expired_count': all_qs.filter(is_published=True, expires_at__isnull=False, expires_at__lte=now).count(),
        'archived_count': all_qs.filter(is_archived=True).count(),
        'now': now,
        'query': query,
        'status': status,
        'priority': priority,
        'priority_choices': Announcement.PRIORITY_CHOICES,
        'active_tab': 'communication',
    }
    return render(request, 'communication/announcement_management.html', context)


@login_required
@user_passes_test(lambda u: u.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'])
@require_POST
def announcement_publish(request, announcement_id):
    """Publish a scheduled announcement immediately."""
    school = request.user.school
    announcement = get_object_or_404(Announcement, id=announcement_id, school=school)
    announcement.is_published = True
    announcement.publish_at = timezone.now()
    announcement.is_archived = False
    announcement.save(update_fields=['is_published', 'publish_at', 'is_archived', 'updated_at'])
    notification_count = AnnouncementService.notify_announcement(announcement)
    return JsonResponse({
        'success': True,
        'message': 'Announcement published successfully.',
        'notifications_created': notification_count,
    })

def _sync_announcement_notifications_for_user(user):
    """Backfill published announcement notifications for the current user."""
    if getattr(user, 'role', None) not in ['PARENT', 'STUDENT']:
        return 0
    if not getattr(user, 'school_id', None):
        return 0

    now = timezone.now()
    announcements = Announcement.objects.filter(
        school_id=user.school_id,
        is_published=True,
        is_archived=False,
        publish_at__lte=now,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))

    if user.role == 'PARENT':
        announcements = announcements.filter(Q(audience='ALL') | Q(audience='PARENTS'))
    else:
        announcements = announcements.filter(Q(audience='ALL') | Q(audience='STUDENTS'))

    created = 0
    for announcement in announcements.select_related('school', 'sender').iterator():
        # Use a user-specific path here. It deliberately does not depend on the
        # parent's User.school field when the parent is linked to the school via
        # Student.parent. This repairs older demo records as soon as the parent
        # opens the bell or Notification Center.
        if AnnouncementService.ensure_announcement_notification_for_user(announcement, user):
            created += 1
    return created


@login_required
@require_GET
def notification_list(request):
    """Return the current user's latest notifications for the navbar dropdown."""
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

    try:
        _sync_announcement_notifications_for_user(request.user)
    except Exception:
        logger.exception('Announcement notification sync failed for user %s', request.user.pk)

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

    try:
        _sync_announcement_notifications_for_user(request.user)
    except Exception:
        logger.exception('Announcement notification sync failed for user %s', request.user.pk)

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
        if notification.category == NotificationCategory.OVERDUE_BALANCE and notification.reference_id:
            try:
                from finance.models import Invoice
                invoice = Invoice.objects.select_related('student').filter(
                    id=notification.reference_id,
                    student__parent=request.user,
                ).first()
                if invoice:
                    notification.action_url = reverse(
                        'finance:student_financial_account',
                        args=[invoice.student_id]
                    )
            except Exception:
                notification.action_url = None
        elif notification.category == NotificationCategory.PAYMENT_RECEIPT and notification.reference_id:
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
        elif notification.category == NotificationCategory.LEAVE_APPROVAL and notification.reference_id:
            try:
                notification.action_url = reverse(
                    'staff:leave_detail',
                    args=[notification.reference_id]
                )
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

        elif notification.category == NotificationCategory.ANNOUNCEMENT and notification.reference_id:
            try:
                announcement = Announcement.objects.filter(
                    id=notification.reference_id,
                    school=getattr(request.user, 'school', None),
                    is_archived=False,
                ).first()
                if announcement:
                    notification.action_url = reverse(
                        'communication:announcement_detail',
                        args=[announcement.id]
                    )
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
    """Mark a notification as read."""
    notification = get_object_or_404(NotificationLog, id=notification_id, recipient=request.user)
    notification.mark_as_read()
    return JsonResponse({'success': True, 'message': 'Notification marked as read.'})


@login_required
@require_POST
def notification_mark_all_read(request):
    """Mark all notifications as read."""
    NotificationLog.objects.filter(
        recipient=request.user,
        status=NotificationStatus.DELIVERED
    ).update(status=NotificationStatus.READ, read_at=timezone.now())
    return JsonResponse({'success': True, 'message': 'All notifications marked as read.'})


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
    """View and manage notification delivery logs for the current school."""
    school = request.user.school
    if not school:
        messages.error(request, "No school associated with your account.")
        return redirect('dashboard')

    logs = (
        NotificationLog.objects
        .filter(school=school)
        .select_related('recipient', 'sender')
        .order_by('-created_at')
    )

    status_filter = (request.GET.get('status') or '').strip().upper()
    category_filter = (request.GET.get('category') or '').strip().upper()
    search = (request.GET.get('search') or '').strip()

    valid_statuses = {value for value, _label in NotificationStatus.choices}
    valid_categories = {value for value, _label in NotificationCategory.choices}

    if status_filter in valid_statuses:
        logs = logs.filter(status=status_filter)
    else:
        status_filter = ''

    if category_filter in valid_categories:
        logs = logs.filter(category=category_filter)
    else:
        category_filter = ''

    if search:
        logs = logs.filter(
            Q(subject__icontains=search) |
            Q(message__icontains=search) |
            Q(recipient__username__icontains=search) |
            Q(recipient__first_name__icontains=search) |
            Q(recipient__last_name__icontains=search) |
            Q(recipient__email__icontains=search)
        )

    # Dashboard counts intentionally use the current school's complete log set,
    # not the filtered queryset, so administrators can see the real delivery
    # health while investigating a filtered result set.
    school_logs = NotificationLog.objects.filter(school=school)
    total_logs = school_logs.count()
    sent_count = school_logs.filter(status__in=[NotificationStatus.SENT, NotificationStatus.DELIVERED]).count()
    pending_count = school_logs.filter(status__in=[NotificationStatus.PENDING, NotificationStatus.QUEUED]).count()
    failed_count = school_logs.filter(status=NotificationStatus.FAILED).count()
    read_count = school_logs.filter(status=NotificationStatus.READ).count()

    page_obj = paginate_queryset(logs, request)

    context = {
        'logs': page_obj,
        'status_choices': NotificationStatus.choices,
        'category_choices': NotificationCategory.choices,
        'selected_status': status_filter,
        'selected_category': category_filter,
        'search': search,
        'total_logs': total_logs,
        'sent_count': sent_count,
        'pending_count': pending_count,
        'failed_count': failed_count,
        'read_count': read_count,
        'active_tab': 'communication',
    }
    return render(request, 'communication/log_list.html', context)


@login_required
@user_passes_test(lambda u: u.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'])
def notification_analytics(request):
    """Admin notification delivery health dashboard for the current school."""
    school = request.user.school
    if not school:
        messages.error(request, "No school associated with your account.")
        return redirect('dashboard')

    now = timezone.now()
    recent_start = now - timezone.timedelta(days=30)
    logs = NotificationLog.objects.filter(school=school)
    recent_logs = logs.filter(created_at__gte=recent_start)

    total = logs.count()
    recent_total = recent_logs.count()
    delivered = logs.filter(status__in=[NotificationStatus.SENT, NotificationStatus.DELIVERED, NotificationStatus.READ]).count()
    failed = logs.filter(status=NotificationStatus.FAILED).count()
    pending = logs.filter(status__in=[NotificationStatus.PENDING, NotificationStatus.QUEUED]).count()
    read = logs.filter(status=NotificationStatus.READ).count()

    delivery_rate = round((delivered / total) * 100, 1) if total else 0
    failure_rate = round((failed / total) * 100, 1) if total else 0
    read_rate = round((read / delivered) * 100, 1) if delivered else 0

    category_rows = list(
        recent_logs.values('category')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    category_labels = dict(NotificationCategory.choices)
    max_category = max((row['total'] for row in category_rows), default=1)
    for row in category_rows:
        row['label'] = category_labels.get(row['category'], row['category'])
        row['percent'] = round((row['total'] / max_category) * 100, 1)

    channel_rows = list(
        recent_logs.values('channel')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
    channel_labels = dict(NotificationLog._meta.get_field('channel').choices)
    max_channel = max((row['total'] for row in channel_rows), default=1)
    for row in channel_rows:
        row['label'] = channel_labels.get(row['channel'], row['channel'])
        row['percent'] = round((row['total'] / max_channel) * 100, 1)

    daily_rows = []
    for offset in range(6, -1, -1):
        day = (now - timezone.timedelta(days=offset)).date()
        count = recent_logs.filter(created_at__date=day).count()
        failed_day = recent_logs.filter(created_at__date=day, status=NotificationStatus.FAILED).count()
        daily_rows.append({
            'date': day,
            'label': day.strftime('%a'),
            'total': count,
            'failed': failed_day,
        })
    max_daily = max((row['total'] for row in daily_rows), default=1)
    for row in daily_rows:
        row['height'] = round((row['total'] / max_daily) * 100, 1) if row['total'] else 4

    recent_failures = logs.filter(status=NotificationStatus.FAILED).select_related('recipient').order_by('-created_at')[:8]

    context = {
        'active_tab': 'communication',
        'total': total,
        'recent_total': recent_total,
        'delivered': delivered,
        'failed': failed,
        'pending': pending,
        'read': read,
        'delivery_rate': delivery_rate,
        'failure_rate': failure_rate,
        'read_rate': read_rate,
        'category_rows': category_rows,
        'channel_rows': channel_rows,
        'daily_rows': daily_rows,
        'recent_failures': recent_failures,
        'recent_start': recent_start,
        'now': now,
    }
    return render(request, 'communication/notification_analytics.html', context)


@login_required
@user_passes_test(lambda u: u.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'])
@require_POST
def notification_retry(request, notification_id):
    """Retry one failed notification from the current school's delivery log."""
    school = request.user.school
    if not school:
        return JsonResponse({'success': False, 'error': 'No school associated with your account.'}, status=400)

    notification = get_object_or_404(
        NotificationLog.objects.select_related('recipient', 'school'),
        id=notification_id,
        school=school,
    )

    if notification.status != NotificationStatus.FAILED:
        return JsonResponse({
            'success': False,
            'error': 'Only failed notifications can be retried.'
        }, status=400)

    # Re-check the current preference before retrying. The service will also
    # enforce this during dispatch, preventing a stale log from bypassing
    # the user's latest notification settings.
    if not NotificationService.should_send_notification(notification.recipient, notification.category):
        return JsonResponse({
            'success': False,
            'error': 'The recipient has disabled this notification category.'
        }, status=400)

    notification.status = NotificationStatus.QUEUED
    notification.error_message = ''
    notification.sent_at = None
    notification.save(update_fields=['status', 'error_message', 'sent_at'])

    # Keep the retry lightweight and compatible with the existing application
    # architecture; the service already handles email/SMS/in-app dispatch.
    import threading
    thread = threading.Thread(
        target=NotificationService.dispatch_notification,
        args=(notification.id,),
        daemon=True,
    )
    thread.start()

    return JsonResponse({
        'success': True,
        'message': 'Notification retry queued successfully.'
    })
