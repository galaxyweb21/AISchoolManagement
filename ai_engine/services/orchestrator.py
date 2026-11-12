from ai_engine.services.workflow_engine import WorkflowEngine
from ai_engine.services.automation_engine import AutomationEngine


class AIOrchestrator:
    """
    Central coordinator for all AI operations.
    """

    @staticmethod
    def refresh_school(school):
        """
        Refresh AI state for an entire school.
        Safe to call repeatedly.
        """
        AutomationEngine.generate_tasks(school)

    @staticmethod
    def execute_task(task):
        WorkflowEngine.execute(task)