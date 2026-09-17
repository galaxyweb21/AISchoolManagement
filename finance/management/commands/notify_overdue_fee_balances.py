from django.core.management.base import BaseCommand

from finance.tasks import notify_overdue_fee_balances


class Command(BaseCommand):
    help = "Create in-app notifications for overdue student fee balances."

    def handle(self, *args, **options):
        created = notify_overdue_fee_balances()
        self.stdout.write(
            self.style.SUCCESS(
                f"Overdue balance notification scan completed. {created} notification(s) created."
            )
        )
