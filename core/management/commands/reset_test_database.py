from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Destructively clear all database data while preserving the schema and migration history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required safety confirmation.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError(
                "This permanently deletes all database records. "
                "Back up anything needed, then rerun with --confirm."
            )

        self.stdout.write(self.style.WARNING("Clearing ALL application data..."))
        # Django's native flush is safer than manually ordering every model:
        # it understands FK dependencies, works across SQLite/MySQL/PostgreSQL,
        # preserves the schema and migration history, and resets sequences.
        call_command(
            "flush",
            interactive=False,
            reset_sequences=True,
            allow_cascade=True,
            verbosity=0,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Database cleared successfully. Schema and migration history were preserved."
            )
        )
