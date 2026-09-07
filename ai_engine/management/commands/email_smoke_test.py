from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a provider-neutral email smoke test (console locally, Brevo on Render)."

    def add_arguments(self, parser):
        parser.add_argument("recipient", help="Mailbox to receive the test email.")

    def handle(self, *args, **options):
        recipient = options["recipient"]
        provider = getattr(settings, "EMAIL_PROVIDER", "unknown")
        try:
            connection = get_connection(fail_silently=False)
            message = EmailMessage(
                subject="EduAI School Management — Email Smoke Test",
                body=(
                    "This is an email smoke test from EduAI School Management.\n\n"
                    f"Provider: {provider}\n"
                    "If you are using the local development console backend, "
                    "the complete message is printed in the terminal instead of sent.\n"
                ),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                to=[recipient],
                connection=connection,
            )
            sent = message.send(fail_silently=False)
        except Exception as exc:
            raise CommandError(f"Email smoke test failed: {type(exc).__name__}: {exc}") from exc

        if sent:
            self.stdout.write(self.style.SUCCESS(
                f"Email smoke test submitted successfully via {provider}: {recipient}"
            ))
        else:
            raise CommandError("The email backend reported that no message was sent.")
