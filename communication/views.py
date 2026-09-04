from core.pagination import paginate_queryset
# communication/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
import json

from .models import Announcement, NotificationLog, NotificationStatus, UserNotificationPreference
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

        # Parse dates if provided
        publish_date = None
        expire_date = None
        if publish_at:
            try:
                publish_date = timezone.datetime.fromisoformat(publish_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass

        if expires_at:
            try:
                expire_date = timezone.datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                pass

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
            'message': 'Announcement published successfully.'
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
@require_GET
def notification_list(request):
    """Get user's notifications (AJAX)."""
    notifications = NotificationLog.objects.filter(
        recipient=request.user
    ).order_by('-created_at')[:50]

    data = [{
        'id': str(n.id),
        'subject': n.subject,
        'message': n.message[:200],
        'category': n.get_category_display(),
        'created_at': n.created_at.strftime('%b %d, %Y %H:%M'),
        'is_read': n.status == NotificationStatus.READ
    } for n in notifications]

    return JsonResponse({'success': True, 'notifications': data})


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
    """View notification logs (admin only)."""
    school = request.user.school

    # Apply filters
    logs = NotificationLog.objects.filter(school=school).select_related('recipient', 'sender')

    status_filter = request.GET.get('status')
    if status_filter:
        logs = logs.filter(status=status_filter)

    category_filter = request.GET.get('category')
    if category_filter:
        logs = logs.filter(category=category_filter)

    # Search
    search = request.GET.get('search')
    if search:
        logs = logs.filter(
            Q(subject__icontains=search) |
            Q(message__icontains=search) |
            Q(recipient__username__icontains=search) |
            Q(recipient__email__icontains=search)
        )

    page_obj = paginate_queryset(logs, request)
    paginator = page_obj.paginator

    context = {
        'logs': page_obj,
        'status_choices': NotificationLog._meta.get_field('status').choices,
        'category_choices': NotificationLog._meta.get_field('category').choices,
        'selected_status': status_filter,
        'selected_category': category_filter,
        'search': search,
        'active_tab': 'communication'
    }
    return render(request, 'communication/log_list.html', context)
