from django.conf import settings
from django.core.mail import get_connection, EmailMessage
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Send a real test email using the configured email provider.'

    def add_arguments(self, parser):
        parser.add_argument('recipient')

    def handle(self, *args, **options):
        recipient = options['recipient']
        provider = getattr(settings, 'EMAIL_PROVIDER', 'unknown')
        if provider == 'brevo' and not getattr(settings, 'BREVO_API_KEY', ''):
            raise CommandError('BREVO_API_KEY is not configured.')

        connection = get_connection(fail_silently=False)
        message = EmailMessage(
            subject='EduAI School Management — Email Provider Test',
            body=(
                'This is a test message from EduAI School Management.\n\n'
                f'Provider: {provider}\n'
                'If you received this email, the configured email delivery path is working.'
            ),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            to=[recipient],
            connection=connection,
        )
        message.send(fail_silently=False)
        self.stdout.write(self.style.SUCCESS(
            f'Test email submitted successfully via {provider} to {recipient}.'
        ))
