from django.core.management.base import BaseCommand
from communication.tasks import publish_scheduled_announcements


class Command(BaseCommand):
    help = "Publish scheduled announcements and create recipient notifications."

    def handle(self, *args, **options):
        result = publish_scheduled_announcements()
        self.stdout.write(self.style.SUCCESS(
            f"Published {result['published']} scheduled announcement(s); "
            f"created {result['notifications_created']} notification(s)."
        ))
