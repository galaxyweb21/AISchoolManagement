from core.models import WorkflowInstance


class WorkflowService:

    @staticmethod
    def start(workflow, object_id):

        first_step = workflow.steps.order_by("order").first()

        return WorkflowInstance.objects.create(
            workflow=workflow,
            object_id=object_id,
            current_step=first_step,
        )