from django.utils import timezone

from ai_engine.models import AIAutomationTask
from ai_engine.models import PaymentReminder
from finance.models import Invoice
from ai_engine.services.services import AIService


class WorkflowEngine:

    """
    Executes approved AI automation tasks.
    """

    @staticmethod
    def execute(task):

        handlers = {

            "PAYMENT_REMINDER":
                WorkflowEngine.payment_reminder,

            "HIGH_RISK_INTERVENTION":
                WorkflowEngine.high_risk_student,

            "REPORT_CARD_PUBLISH":
                WorkflowEngine.publish_report_cards,

            "ATTENDANCE_ALERT":
                WorkflowEngine.attendance_alert,

            "GRADEBOOK_SYNC":
                WorkflowEngine.gradebook_sync,

        }

        handler = handlers.get(task.task_type)

        if handler is None:

            raise Exception(
                f"No workflow for {task.task_type}"
            )

        task.status = "RUNNING"

        task.save(update_fields=["status"])

        handler(task)

        task.status = "COMPLETED"

        task.completed_at = timezone.now()

        task.save(
            update_fields=[
                "status",
                "completed_at",
            ]
        )


@staticmethod
def payment_reminder(task):

    invoice = Invoice.objects.select_related("student__user").prefetch_related(
        "line_items__fee_category"
    ).get(

        id=task.metadata["invoice_id"]

    )

    line_item_categories = [li.fee_category.name for li in invoice.line_items.all()]
    fee_category_name = ", ".join(dict.fromkeys(line_item_categories)) or "Fees"

    reminder = AIService.generate_payment_reminder(

        student_name=invoice.student.user.get_full_name(),

        fee_category_name=fee_category_name,

        total_amount=invoice.total_amount,

        balance_due=invoice.balance_due,

        overdue_days=0,

        due_date=invoice.due_date,

    )

    PaymentReminder.objects.create(

        school=invoice.school,

        invoice=invoice,

        student=invoice.student,

        message=reminder,

    )