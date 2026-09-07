from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from ai_engine.services.email_monitoring import EmailMonitoringService

class Command(BaseCommand):
    help = 'Test SMTP configuration and optionally send a real test email.'
    def add_arguments(self, parser):
        parser.add_argument('recipient', nargs='?', help='Real mailbox to receive the test email')
        parser.add_argument('--username', default='demo_admin', help='User whose school is used for the health record')
    def handle(self, *args, **options):
        User=get_user_model()
        try: user=User.objects.select_related('school').get(username=options['username'])
        except User.DoesNotExist: raise CommandError(f"User {options['username']} was not found.")
        if not user.school: raise CommandError('The selected user is not linked to a school.')
        check=EmailMonitoringService.test(user.school,user,options.get('recipient') or user.email)
        if check.success: self.stdout.write(self.style.SUCCESS(check.message))
        else: raise CommandError(check.message)
