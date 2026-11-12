from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import NotificationCategory, NotificationChannel
from .services import NotificationService

# NOTE: Import your existing models here.
# Using string matching/try-except protects the app if model names differ slightly.

try:
    from scheduler.models import Timetable  # Adjust to your scheduler app model
    @receiver(post_save, sender=Timetable)
    def notify_timetable_published(sender, instance, created, **kwargs):
        """Triggers notification when new schedule is published."""
        if getattr(instance, 'is_published', True):
            # If timetable is linked to a class/section, notify relevant users
            users = getattr(instance, 'get_affected_users', lambda: [])()
            for user in users:
                NotificationService.trigger(
                    recipient=user,
                    category=NotificationCategory.TIMETABLE_UPDATE,
                    subject="Update: New Class Timetable Published",
                    message=f"Hello {user.first_name},\n\nA new timetable has been published for your class. "
                            f"Please check your student portal to view the updated schedule.",
                    channel=NotificationChannel.EMAIL
                )
except ImportError:
    pass