from ai_engine.models import (
    GeneratedExam,
    StudentRiskAssessment,
    ReportCard,
    ParentChatMessage,
    AIActivity,
    AIInsight,
)

from finance.models import Invoice

from ai_engine.services.health_score import SchoolHealthService
from ai_engine.services.insight_engine import InsightEngine
from ai_engine.services.recommendation_engine import RecommendationEngine
from ai_engine.models import AIAutomationTask


class CommandCenterService:
    """
    Builds the complete context for the AI Command Center.
    """

    @staticmethod
    def build_dashboard(school):
        # -----------------------------------
        # School Health
        # -----------------------------------

        health = SchoolHealthService.calculate(school)

        # -----------------------------------
        # AI Insights
        # -----------------------------------


        try:
            InsightEngine.generate(school)
        except Exception:
            pass

        insights = (
            AIInsight.objects
            .filter(school=school)
            .order_by("-created_at")[:20]
        )

        # -----------------------------------
        # Dashboard Statistics
        # -----------------------------------

        generated_exams = GeneratedExam.objects.filter(
            school=school
        ).count()

        high_risk_students = StudentRiskAssessment.objects.filter(
            school=school,
            risk_band="HIGH"
        ).count()

        report_cards = ReportCard.objects.filter(
            school=school
        ).count()

        parent_chats = ParentChatMessage.objects.filter(
            school=school
        ).count()

        outstanding_invoices = Invoice.objects.filter(
            school=school,
            status__in=["UNPAID", "PARTIAL"]
        ).count()

        # -----------------------------------
        # AI Recommendations
        # -----------------------------------

        recommendations = RecommendationEngine.get_recommendations(
            school
        )

        # -----------------------------------
        # Timeline
        # -----------------------------------

        recent_activity = (
            AIActivity.objects
            .filter(school=school)
            .select_related("created_by")
            .order_by("-created_at")[:10]
        )


        automation_tasks = (
            AIAutomationTask.objects
                .filter(
                school=school,
                status="PENDING"
            )
                .order_by("-created_at")[:10]
        )

        return {
            "health": health,
            "insights": insights,
            "generated_exams": generated_exams,
            "high_risk_students": high_risk_students,
            "report_cards": report_cards,
            "parent_chats": parent_chats,
            "outstanding_invoices": outstanding_invoices,
            "recommendations": recommendations,
            "recent_activity": recent_activity,
            "automation_tasks": automation_tasks,
        }