from celery import shared_task
from .services import AnnouncementService


@shared_task
def publish_scheduled_announcements():
    """Publish due announcements and create recipient notifications."""
    return AnnouncementService.publish_due_announcements()
