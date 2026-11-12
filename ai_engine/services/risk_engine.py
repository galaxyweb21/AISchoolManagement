# ai_engine/services/risk_engine.py
"""
Deterministic, explainable dropout-risk scoring.

Deliberately NOT an LLM call for the score itself: this flags vulnerable
children, so the number an admin acts on needs to be reproducible and
auditable (same inputs -> same score, every time), not a black box. An
optional LLM narrative can be layered on top purely for readability - see
generate_narrative() below - but it never changes the score or the band.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from attendance.models import Attendance
from assessments.models import Grade
from finance.models import Invoice, InvoiceLineItem, Payment

ATTENDANCE_LOOKBACK_DAYS = 30
ATTENDANCE_MAX_POINTS = 40
GRADE_AVG_MAX_POINTS = 20
GRADE_TREND_MAX_POINTS = 15
FINANCE_DAYS_MAX_POINTS = 15
FINANCE_RATIO_MAX_POINTS = 10

RISK_BANDS = [
    (75, 'CRITICAL'),
    (50, 'HIGH'),
    (25, 'MEDIUM'),
    (0, 'LOW'),
]


def _clamp(value, low, high):
    return max(low, min(high, value))


def _band_for_score(score: float) -> str:
    for threshold, band in RISK_BANDS:
        if score >= threshold:
            return band
    return 'LOW'


class RiskEngineService:

    @staticmethod
    def _attendance_component(student, academic_term):
        today = timezone.localdate()
        window_start = max(academic_term.start_date, today - timedelta(days=ATTENDANCE_LOOKBACK_DAYS))

        records = Attendance.objects.filter(student=student, date__gte=window_start, date__lte=today)
        total = records.count()
        factors = []

        if total == 0:
            return None, 0.0, factors

        present = records.filter(status__in=['PRESENT', 'LATE']).count()
        rate = round((present / total) * 100, 1)

        points = _clamp((95 - rate) / 35 * ATTENDANCE_MAX_POINTS, 0, ATTENDANCE_MAX_POINTS)

        if points > 0:
            factors.append({
                'factor': 'Attendance',
                'detail': f"{rate}% present over the last {total} tracked school day(s)"
                          f" (since {window_start:%b %d}).",
                'points': round(points, 1),
            })
        return rate, points, factors

    @staticmethod
    def _grade_component(student):
        grades = list(
            Grade.objects.filter(student=student)
                .select_related('assessment')
                .order_by('updated_at')
        )
        factors = []

        if not grades:
            return None, None, 0.0, factors

        percentages = [
            float(g.score_achieved) / float(g.assessment.max_score) * 100
            for g in grades if g.assessment.max_score
        ]
        if not percentages:
            return None, None, 0.0, factors

        avg = round(sum(percentages) / len(percentages), 1)

        avg_points = _clamp((70 - avg) / 30 * GRADE_AVG_MAX_POINTS, 0, GRADE_AVG_MAX_POINTS)
        if avg_points > 0:
            factors.append({
                'factor': 'Grade average',
                'detail': f"Average score across {len(percentages)} graded assessment(s) is {avg}%.",
                'points': round(avg_points, 1),
            })

        trend = None
        trend_points = 0.0
        if len(percentages) >= 2:
            midpoint = len(percentages) // 2
            earlier_half = percentages[:midpoint] or percentages[:1]
            recent_half = percentages[midpoint:]
            earlier_avg = sum(earlier_half) / len(earlier_half)
            recent_avg = sum(recent_half) / len(recent_half)
            trend = round(recent_avg - earlier_avg, 1)

            if trend < 0:
                trend_points = _clamp(abs(trend) / 15 * GRADE_TREND_MAX_POINTS, 0, GRADE_TREND_MAX_POINTS)
                factors.append({
                    'factor': 'Declining grades',
                    'detail': f"Average dropped from {round(earlier_avg, 1)}% to {round(recent_avg, 1)}% "
                              f"across the graded assessments on record.",
                    'points': round(trend_points, 1),
                })

        return avg, trend, avg_points + trend_points, factors

    @staticmethod
    def _finance_component(student):
        today = timezone.localdate()

        # Get all invoices for this student
        invoices = Invoice.objects.filter(student=student)

        # Calculate total billed from line items (database field)
        total_billed = InvoiceLineItem.objects.filter(
            invoice__student=student
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Calculate total paid from confirmed payments (database field)
        total_paid = Payment.objects.filter(
            invoice__student=student,
            status='CONFIRMED'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # Calculate overdue invoices
        overdue = invoices.filter(status__in=['UNPAID', 'PARTIAL'], due_date__lt=today)
        factors = []

        overdue_amount = sum((inv.balance_due for inv in overdue), Decimal('0'))
        overdue_days = 0
        if overdue.exists():
            overdue_days = max((today - inv.due_date).days for inv in overdue)

        overdue_ratio = float(overdue_amount) / float(total_billed) if total_billed else 0.0

        days_points = _clamp(overdue_days / 60 * FINANCE_DAYS_MAX_POINTS, 0, FINANCE_DAYS_MAX_POINTS)
        ratio_points = _clamp(overdue_ratio * FINANCE_RATIO_MAX_POINTS, 0, FINANCE_RATIO_MAX_POINTS)
        points = days_points + ratio_points

        if points > 0:
            factors.append({
                'factor': 'Overdue fees',
                'detail': f"{overdue_amount} outstanding, {overdue_days} day(s) past due "
                          f"({round(overdue_ratio * 100)}% of total billed).",
                'points': round(points, 1),
            })

        return overdue_amount, overdue_days, points, factors

    @classmethod
    def assess_student(cls, student, academic_term) -> dict:
        """Returns a dict of everything needed to build a StudentRiskAssessment row."""
        attendance_rate, attendance_points, attendance_factors = cls._attendance_component(student, academic_term)
        grade_avg, grade_trend, grade_points, grade_factors = cls._grade_component(student)
        fee_overdue_amount, fee_overdue_days, finance_points, finance_factors = cls._finance_component(student)

        total_score = round(attendance_points + grade_points + finance_points, 1)
        total_score = _clamp(total_score, 0, 100)

        all_factors = sorted(
            attendance_factors + grade_factors + finance_factors,
            key=lambda f: f['points'],
            reverse=True,
        )

        return {
            'risk_score': total_score,
            'risk_band': _band_for_score(total_score),
            'attendance_rate': attendance_rate,
            'attendance_points': round(attendance_points, 1),
            'grade_average': grade_avg,
            'grade_trend': grade_trend,
            'grade_points': round(grade_points, 1),
            'fee_overdue_amount': fee_overdue_amount,
            'fee_overdue_days': fee_overdue_days,
            'finance_points': round(finance_points, 1),
            'contributing_factors': all_factors,
        }

    @staticmethod
    def generate_narrative(student, assessment_data: dict) -> str:
        """
        Optional plain-language summary for HIGH/CRITICAL cases, generated
        by the same Groq client ai_engine already uses for report-card
        feedback. Never affects the score - if the API key is missing or
        the call fails, the dashboard still works fine without it.
        """
        from django.conf import settings
        from groq import Groq

        api_key = getattr(settings, 'GROQ_API_KEY', '')
        if not api_key:
            return ""

        factor_lines = "\n".join(
            f"- {f['factor']}: {f['detail']}" for f in assessment_data['contributing_factors']
        )
        prompt = f"""
        You are a school pastoral-care advisor. A student has been flagged by an early-warning
        system with a dropout risk score of {assessment_data['risk_score']}/100 ({assessment_data['risk_band']}).

        Contributing factors:
        {factor_lines or "No single dominant factor - risk is spread across several small signals."}

        In 2-3 sentences, summarize the concern for a busy school administrator and suggest one
        concrete, compassionate next step (e.g. who to talk to first). Do not diagnose the student
        or speculate about causes you weren't given. Be direct and practical, not alarmist.
        """
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",  # llama-3.3-70b-versatile was retired by Groq on 08/16/26
                messages=[
                    {"role": "system", "content": "You are a calm, practical school pastoral-care advisor."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=150,
                temperature=0.4,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            return ""


# Export the class for import
__all__ = ['RiskEngineService']