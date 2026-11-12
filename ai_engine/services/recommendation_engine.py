from finance.models import Invoice
from students.models import Student
from ai_engine.models import StudentRiskAssessment, ReportCard
from django.db.models import Count


class RecommendationEngine:

    @staticmethod
    def get_recommendations(school):

        recommendations = []

        # Outstanding invoices
        overdue = Invoice.objects.filter(
            school=school,
            status__in=["UNPAID", "PARTIAL"]
        ).count()

        if overdue:
            recommendations.append({
                "icon": "bi-cash-stack",
                "color": "warning",
                "title": "Outstanding School Fees",
                "message": f"{overdue} invoices require follow-up.",
                "url": "finance_insights_dashboard"
            })

        # High-risk students
        risk = StudentRiskAssessment.objects.filter(
            school=school,
            risk_band="HIGH"
        ).count()

        if risk:
            recommendations.append({
                "icon": "bi-exclamation-triangle",
                "color": "danger",
                "title": "Students At Risk",
                "message": f"{risk} students need intervention.",
                "url": "risk_dashboard"
            })

        # Draft report cards
        drafts = ReportCard.objects.filter(
            school=school,
            is_finalized=False
        ).count()

        if drafts:
            recommendations.append({
                "icon": "bi-file-earmark-text",
                "color": "primary",
                "title": "Pending Report Cards",
                "message": f"{drafts} report cards need approval.",
                "url": "report_card_dashboard"
            })

        return recommendations