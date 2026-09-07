from django.conf import settings
from django.core.mail import get_connection, EmailMessage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Send a real test email using the configured SMTP settings.'

    def add_arguments(self, parser):
        parser.add_argument('recipient')

    def handle(self, *args, **options):
        recipient = options['recipient']
        required = ['EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD', 'DEFAULT_FROM_EMAIL']
        missing = [name for name in required if not getattr(settings, name, None)]
        if missing:
            raise CommandError('Missing email settings: ' + ', '.join(missing))

        connection = get_connection(fail_silently=False)
        message = EmailMessage(
            subject='EduAI School Management — SMTP Test',
            body=(
                'This is a test message from EduAI School Management.\n\n'
                'If you received this email, the SMTP password-reset delivery '
                'configuration is working.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
            connection=connection,
        )
        message.send(fail_silently=False)
        self.stdout.write(self.style.SUCCESS(f'Test email sent successfully to {recipient}.'))
