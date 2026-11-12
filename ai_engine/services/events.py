from ai_engine.services.orchestrator import AIOrchestrator


class AIEvents:

    @staticmethod
    def invoice_paid(invoice):

        AIOrchestrator.refresh_school(
            invoice.school
        )

    @staticmethod
    def report_card_finalized(report):

        AIOrchestrator.refresh_school(
            report.school
        )

    @staticmethod
    def attendance_saved(attendance):

        AIOrchestrator.refresh_school(
            attendance.school
        )

    @staticmethod
    def exam_created(exam):

        AIOrchestrator.refresh_school(
            exam.school
        )