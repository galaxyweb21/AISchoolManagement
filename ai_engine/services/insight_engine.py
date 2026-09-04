from ai_engine.models import AIInsight

from finance.models import Invoice

from ai_engine.models import StudentRiskAssessment

from django.utils.timezone import localdate


class InsightEngine:

    @staticmethod
    def generate(school):

        AIInsight.objects.filter(

            school=school

        ).delete()

        high_risk = StudentRiskAssessment.objects.filter(

            school=school,

            risk_band="HIGH"

        ).count()

        if high_risk:

            AIInsight.objects.create(

                school=school,

                title="High Risk Students",

                message=f"{high_risk} students need intervention.",

                level="CRITICAL",

                source="Risk Engine"

            )

        overdue = Invoice.objects.filter(

            school=school,

            balance_due__gt=0,

            due_date__lt=localdate()

        ).count()

        if overdue:

            AIInsight.objects.create(

                school=school,

                title="Outstanding Fees",

                message=f"{overdue} invoices are overdue.",

                level="WARNING",

                source="Finance Engine"

            )