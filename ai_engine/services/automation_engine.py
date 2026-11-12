from ai_engine.models import AIAutomationTask


class AutomationEngine:

    @staticmethod
    def generate_tasks(school):

        """
        Build AI automation tasks.

        This method should be safe to run repeatedly.
        """

        return []


from finance.models import Invoice


@staticmethod
def generate_overdue_invoice_tasks(school):

    invoices = Invoice.objects.filter(

        school=school,

        status__in=["UNPAID", "PARTIAL"]

    )

    for invoice in invoices:

        AIAutomationTask.objects.get_or_create(

            school=school,

            task_type="PAYMENT_REMINDER",

            metadata={

                "invoice_id": invoice.id

            },

            defaults={

                "title": f"Send reminder to {invoice.student.user.get_full_name()}",

                "description": "AI detected an overdue invoice.",

                "priority": "HIGH",

            }

        )