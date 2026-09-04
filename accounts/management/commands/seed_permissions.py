from django.core.management.base import BaseCommand

from accounts.models import Permission


class Command(BaseCommand):

    help = "Create enterprise permissions"

    modules = [

        "dashboard",

        "students",

        "parents",

        "teachers",

        "attendance",

        "academics",

        "exams",

        "finance",

        "hostel",

        "library",

        "transport",

        "inventory",

        "clinic",

        "staff",

        "reports",

        "settings",

        "users",

        "roles",

        "ai",

        "notifications",

    ]

    actions = [

        "view",

        "create",

        "edit",

        "delete",

        "approve",

        "export",

        "print",

    ]

    def handle(self, *args, **kwargs):

        for module in self.modules:

            for action in self.actions:

                Permission.objects.get_or_create(

                    module=module,

                    action=action,

                )

        self.stdout.write(

            self.style.SUCCESS(

                "Permissions created successfully."

            )

        )