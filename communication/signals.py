from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import NotificationCategory, NotificationChannel
from .services import NotificationService

# NOTE: Import your existing models here.
# Using string matching/try-except protects the app if model names differ slightly.

try:
    from billing.models import Invoice  # Adjust to your billing app model
    @receiver(post_save, sender=Invoice)
    def notify_overdue_invoice(sender, instance, created, **kwargs):
        """Triggers notification when an invoice is marked overdue or created with unpaid balance."""
        if getattr(instance, 'is_overdue', False) or getattr(instance, 'status', '').upper() == 'OVERDUE':
            student_user = getattr(instance.student, 'user', instance.student)
            NotificationService.trigger(
                recipient=student_user,
                category=NotificationCategory.OVERDUE_BALANCE,
                subject="Notice: Overdue Tuition Balance",
                message=f"Dear {student_user.get_full_name() or student_user.username},\n\n"
                        f"You have an outstanding balance of {getattr(instance, 'amount_due', 'your bill')}. "
                        f"Please clear this balance at your earliest convenience.\n\nThank you.",
                channel=NotificationChannel.BOTH
            )
except ImportError:
    pass

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