"""Ensure the fictional demo administrator can access both the application and Django admin.

This command is called from docker-entrypoint.sh on every container start, on every
plan tier (Render's pre-deploy command and initialDeployHook are either paid-plan-only
or unreliable/one-shot, so they cannot be depended on here). If the demo school itself
is missing -- e.g. a brand new database on first deploy -- this command now seeds the
full demo dataset first (via seed_demo_school, which is idempotent/get_or_create-based
and safe to call repeatedly) instead of silently giving up and leaving no login at all.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import User
from school.models import School


DEMO_SUBDOMAIN = "eduai-demo"
DEMO_USERNAME = "demo_admin"
DEMO_PASSWORD = "Demo@2026!"


class Command(BaseCommand):
    help = "Create/repair the EduAI demo administrator account."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=DEMO_USERNAME)
        parser.add_argument("--password", default=DEMO_PASSWORD)

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]

        school = School.objects.filter(subdomain=DEMO_SUBDOMAIN).first()
        if not school:
            self.stdout.write(self.style.WARNING(
                "Demo school not found; seeding the full EduAI demo dataset now..."
            ))
            call_command("seed_demo_school", password=password)
            school = School.objects.filter(subdomain=DEMO_SUBDOMAIN).first()
            if not school:
                self.stdout.write(self.style.ERROR(
                    "Demo school seeding did not succeed; demo administrator was not created."
                ))
                return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"school": school, "role": "SCHOOL_ADMIN"},
        )
        user.school = school
        user.role = "SCHOOL_ADMIN"
        user.first_name = "Demo"
        user.last_name = "Administrator"
        user.email = f"{username}@eduai.school"
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.default_password = password
        user.set_password(password)
        user.save()

        action = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"Demo administrator {action}: {username} (Django admin + School Admin)"
        ))
