from celery import shared_task
from django.utils import timezone
from .models import Announcement
from .services import AnnouncementService


@shared_task
def publish_scheduled_announcements():
    now = timezone.now()
    announcements = Announcement.objects.filter(
        is_published=False,
        is_archived=False,
        publish_at__lte=now,
    )

    published = 0
    notifications = 0
    for announcement in announcements.select_related('school', 'sender'):
        announcement.is_published = True
        announcement.save(update_fields=['is_published', 'updated_at'])
        published += 1
        notifications += AnnouncementService.notify_announcement(announcement)

    return {'published': published, 'notifications_created': notifications}
