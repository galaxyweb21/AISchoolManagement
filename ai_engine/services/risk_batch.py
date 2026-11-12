# ai_engine/services/risk_batch.py
from django.db import transaction

from students.models import Student
from ai_engine.models import RiskAssessmentRun, StudentRiskAssessment
from ai_engine.services.risk_engine import RiskEngineService

# Only spend an LLM call narrating the cases that actually need a human's
# attention soonest - keeps API cost proportional to how many students are
# actually at risk, not the size of the school.
NARRATIVE_BANDS = {'HIGH', 'CRITICAL'}


class RiskBatchService:

    @staticmethod
    def create_pending(school, academic_term, triggered_by=None) -> RiskAssessmentRun:
        return RiskAssessmentRun.objects.create(
            school=school, academic_term=academic_term, triggered_by=triggered_by, status='PENDING'
        )

    @classmethod
    def run(cls, run: RiskAssessmentRun) -> RiskAssessmentRun:
        run.status = 'RUNNING'
        run.save(update_fields=['status'])

        try:
            school = run.school
            academic_term = run.academic_term
            students = Student.objects.filter(school=school, is_active=True).select_related('user')

            assessments = []
            high_count = 0
            critical_count = 0

            for student in students:
                data = RiskEngineService.assess_student(student, academic_term)

                narrative = ""
                if data['risk_band'] in NARRATIVE_BANDS:
                    narrative = RiskEngineService.generate_narrative(student, data)

                if data['risk_band'] == 'HIGH':
                    high_count += 1
                elif data['risk_band'] == 'CRITICAL':
                    critical_count += 1

                assessments.append(StudentRiskAssessment(
                    run=run,
                    school=school,
                    student=student,
                    narrative=narrative,
                    **data,
                ))

            with transaction.atomic():
                StudentRiskAssessment.objects.filter(run=run).delete()
                StudentRiskAssessment.objects.bulk_create(assessments)
                run.students_assessed = len(assessments)
                run.high_risk_count = high_count
                run.critical_risk_count = critical_count
                run.status = 'COMPLETE'
                run.save(update_fields=['students_assessed', 'high_risk_count', 'critical_risk_count', 'status'])

        except Exception as exc:
            run.status = 'FAILED'
            run.error_message = str(exc)[:500]
            run.save(update_fields=['status', 'error_message'])

        return run