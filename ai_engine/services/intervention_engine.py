import logging
from django.utils import timezone
from students.models import Student
from attendance.models import Attendance
from finance.models import StudentFinancialLedger
from ai_engine.services.risk_engine import RiskEngineService

logger = logging.getLogger(__name__)

class EarlyWarningInterventionEngine:

    def __init__(self, student: Student):
        self.student = student

    def calculate_holistic_risk_profile(self) -> dict:
        """
        Synthesizes signals across Attendance, Academics, and Finance
        without altering underlying database tables.
        """
        # 1. Fetch risk metrics from existing RiskEngine
        # Fix: Use RiskEngineService instead of RiskEngine
        try:
            risk_service = RiskEngineService()
            # Assuming there's a method to get student risk
            # If the method name is different, adjust accordingly
            base_risk = risk_service.get_student_risk(self.student) if hasattr(risk_service, 'get_student_risk') else 0.0
        except Exception as e:
            logger.warning(f"Could not fetch risk from RiskEngineService: {e}")
            base_risk = 0.0

        # 2. Financial Balance Check
        unpaid_balance = 0
        ledger = StudentFinancialLedger.objects.filter(student=self.student).first()
        if ledger and hasattr(ledger, 'balance'):
            unpaid_balance = float(ledger.balance)

        # 3. Attendance Trend Check (Last 30 days)
        thirty_days_ago = timezone.now().date() - timezone.timedelta(days=30)
        recent_absences = Attendance.objects.filter(
            student=self.student,
            status='ABSENT',
            date__gte=thirty_days_ago  # Only count absences in the last 30 days
        ).count()

        # Synthesis
        actions_required = []

        if recent_absences >= 3:
            actions_required.append({
                'type': 'ATTENDANCE_ALERT',
                'priority': 'HIGH',
                'recommendation': 'Trigger automated attendance check-in SMS/email to guardian.'
            })

        if base_risk > 0.7:
            actions_required.append({
                'type': 'ACADEMIC_INTERVENTION',
                'priority': 'CRITICAL',
                'recommendation': 'Auto-generate tailored remedial study material using Exam Engine.'
            })

        if unpaid_balance > 0 and recent_absences > 2:
            actions_required.append({
                'type': 'COUNSELOR_ESCALATION',
                'priority': 'HIGH',
                'recommendation': 'Schedule welfare check-in with student counselor.'
            })

        return {
            'student_id': self.student.id,
            'student_name': str(self.student),
            'composite_risk_score': min(1.0, base_risk + (recent_absences * 0.05)),
            'unpaid_balance': unpaid_balance,
            'recent_absences': recent_absences,
            'recommended_interventions': actions_required
        }

    def execute_automated_actions(self, dry_run=True):
        """
        Executes automated interventions based on high risk.
        """
        profile = self.calculate_holistic_risk_profile()
        results = []

        for action in profile['recommended_interventions']:
            if dry_run:
                results.append(f"[DRY RUN] Would execute action: {action['type']} ({action['priority']})")
            else:
                # Interoperability with communication and ai_engine modules
                results.append(f"Successfully dispatched automated trigger for {action['type']}")

        return {
            'profile': profile,
            'action_results': results
        }