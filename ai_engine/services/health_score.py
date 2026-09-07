from django.db.models import Count

from attendance.models import Attendance
from finance.models import Invoice
from ai_engine.models import (
    StudentRiskAssessment,
    ReportCard,
)
from students.models import Student


class SchoolHealthService:
    """
    Calculates an overall AI health score (0-100)
    using weighted operational metrics.
    """

    @staticmethod
    def calculate(school):

        score = 100

        breakdown = {}

        # -----------------------------------
        # Student Risk
        # -----------------------------------

        total_students = Student.objects.filter(
            school=school,
            is_active=True,
        ).count()

        high_risk = StudentRiskAssessment.objects.filter(
            school=school,
            risk_band="HIGH",
        ).count()

        if total_students:
            risk_percent = (high_risk / total_students) * 100

            penalty = min(risk_percent * 0.30, 20)

            score -= penalty

            breakdown["risk"] = round(100 - penalty)

        else:
            breakdown["risk"] = 100

        # -----------------------------------
        # Outstanding Fees
        # -----------------------------------

        unpaid = Invoice.objects.filter(
            school=school,
            status__in=["UNPAID", "PARTIAL"],
        ).count()

        if total_students:

            unpaid_percent = (unpaid / total_students) * 100

            penalty = min(unpaid_percent * 0.20, 15)

            score -= penalty

            breakdown["finance"] = round(100 - penalty)

        else:

            breakdown["finance"] = 100

        # -----------------------------------
        # Draft Report Cards
        # -----------------------------------

        draft_cards = ReportCard.objects.filter(
            school=school,
            is_finalized=False,
        ).count()

        if total_students:

            draft_percent = (draft_cards / total_students) * 100

            penalty = min(draft_percent * 0.10, 10)

            score -= penalty

            breakdown["report_cards"] = round(100 - penalty)

        else:

            breakdown["report_cards"] = 100

        score = max(round(score), 0)

        # ==========================================
        # Overall Health Status
        # ==========================================

        if score >= 95:
            status = "Excellent"

        elif score >= 85:
            status = "Very Good"

        elif score >= 75:
            status = "Good"

        elif score >= 60:
            status = "Needs Attention"

        else:
            status = "Critical"

        return {
            "score": score,
            "status": status,
            "breakdown": breakdown,
        }