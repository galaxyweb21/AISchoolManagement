from ai_engine.services.orchestrator import AIOrchestrator
from schools.models import School


class AIScheduler:

    @staticmethod
    def nightly():

        for school in School.objects.all():

            AIOrchestrator.refresh_school(
                school
            )