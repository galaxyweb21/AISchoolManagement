# ai_engine/services/finance_engine.py
"""
Deterministic, explainable non-payment risk scoring and cash-flow
forecasting - same philosophy as risk_engine.py: the number an admin acts
on (who to chase for fees, how much to expect this term) needs to be
reproducible and auditable, not a black box. Computed live on each
dashboard load rather than as a stored batch/run, because it's cheap
arithmetic over a school's own invoices, not a search/optimization problem
- there's nothing here that benefits from being cached or backgrounded.
"""
from datetime import date
from decimal import Decimal

from django.utils import timezone

from finance.models import Invoice, InvoiceLineItem, Payment

OVERDUE_DAYS_MAX_POINTS = 40
PAYMENT_RATIO_MAX_POINTS = 30
HISTORY_MAX_POINTS = 30

RISK_BANDS = [
    (75, 'CRITICAL'),
    (50, 'HIGH'),
    (25, 'MEDIUM'),
    (0, 'LOW'),
]

# Heuristic probability that an outstanding balance in each age bucket is
# eventually collected. NOT learned from this school's actual data - there's
# no payment-date field on Invoice to build a real collection curve from
# (only due_date/status/amount_paid), so this is a reasonable industry-typical
# assumption, disclosed as such wherever it's shown. See AI_FINANCE_ASSISTANT.md.
COLLECTION_PROBABILITY = {
    'not_yet_due': 0.95,
    'overdue_1_30': 0.80,
    'overdue_31_60': 0.55,
    'overdue_61_plus': 0.30,
}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _band_for_score(score: float) -> str:
    for threshold, band in RISK_BANDS:
        if score >= threshold:
            return band
    return 'LOW'


class FinanceInsightService:

    @staticmethod
    def _overdue_days(invoice, today):
        if invoice.due_date >= today:
            return 0
        return (today - invoice.due_date).days

    @classmethod
    def _history_component(cls, student, exclude_invoice_id, today):
        """What fraction of this student's OTHER invoices ended up unpaid
        or were badly overdue (30+ days) - a student who has reliably paid
        late-but-eventually shouldn't score as risky as one with a pattern
        of never really catching up."""
        others = Invoice.objects.filter(student=student).exclude(id=exclude_invoice_id)
        total = others.count()
        if total == 0:
            return 0.0, []

        troubled = 0
        for inv in others:
            if inv.status == 'UNPAID' and inv.due_date < today:
                troubled += 1
            elif inv.status == 'PARTIAL' and (today - inv.due_date).days > 30:
                troubled += 1

        ratio = troubled / total if total > 0 else 0
        points = _clamp(ratio * HISTORY_MAX_POINTS, 0, HISTORY_MAX_POINTS)
        factors = []
        if points > 0:
            factors.append({
                'factor': 'Payment history',
                'detail': f"{troubled} of {total} previous invoice(s) went unpaid or were more than "
                          f"30 days overdue.",
                'points': round(points, 1),
            })
        return points, factors

    @classmethod
    def assess_invoice(cls, invoice, today=None) -> dict:
        """Pure computation for one unpaid/partial invoice. Returns None
        for a PAID invoice - nothing to assess."""
        if invoice.status == 'PAID':
            return None

        today = today or timezone.localdate()
        factors = []

        overdue_days = cls._overdue_days(invoice, today)
        overdue_points = _clamp(overdue_days / 60 * OVERDUE_DAYS_MAX_POINTS, 0, OVERDUE_DAYS_MAX_POINTS)
        if overdue_points > 0:
            factors.append({
                'factor': 'Overdue',
                'detail': f"{overdue_days} day(s) past the due date ({invoice.due_date:%b %d}).",
                'points': round(overdue_points, 1),
            })

        total = float(invoice.total_amount)
        paid = float(invoice.amount_paid)
        unpaid_ratio = (1 - (paid / total)) if total else 0.0
        ratio_points = _clamp(unpaid_ratio * PAYMENT_RATIO_MAX_POINTS, 0, PAYMENT_RATIO_MAX_POINTS)
        if ratio_points > 0 and paid > 0:
            factors.append({
                'factor': 'Partial payment',
                'detail': f"Only {round((paid / total) * 100)}% paid so far ({invoice.amount_paid} of "
                          f"{invoice.total_amount}).",
                'points': round(ratio_points, 1),
            })
        elif ratio_points > 0:
            factors.append({
                'factor': 'Unpaid',
                'detail': f"No payment recorded yet against {invoice.total_amount}.",
                'points': round(ratio_points, 1),
            })

        history_points, history_factors = cls._history_component(invoice.student, invoice.id, today)
        factors.extend(history_factors)

        score = round(overdue_points + ratio_points + history_points, 1)
        score = _clamp(score, 0, 100)

        return {
            'risk_score': score,
            'risk_band': _band_for_score(score),
            'overdue_days': overdue_days,
            'payment_ratio': round(paid / total, 3) if total else None,
            'contributing_factors': sorted(factors, key=lambda f: f['points'], reverse=True),
        }

    @classmethod
    def compute_school_snapshot(cls, school, today=None) -> dict:
        """
        Everything the finance dashboard needs in one pass: aggregate
        cash-flow numbers, an age-bucket breakdown of what's outstanding, a
        heuristic collection forecast, and a per-invoice risk-sorted list
        for the at-risk table.
        """
        today = today or timezone.localdate()

        # FIXED: Remove select_related('fee_category') - Invoice doesn't have this field
        # Get all invoices for the school with student and academic_term
        invoices = list(
            Invoice.objects.filter(school=school).select_related(
                'student',
                'student__user',
                'academic_term'
            ).prefetch_related(
                'line_items',
                'line_items__fee_category',
                'payments'
            )
        )

        total_billed = sum((inv.total_amount for inv in invoices), Decimal('0'))
        total_collected = sum((inv.amount_paid for inv in invoices), Decimal('0'))
        total_outstanding = total_billed - total_collected

        buckets = {'not_yet_due': Decimal('0'), 'overdue_1_30': Decimal('0'),
                   'overdue_31_60': Decimal('0'), 'overdue_61_plus': Decimal('0')}

        assessments = []
        for inv in invoices:
            if inv.status == 'PAID':
                continue
            balance = inv.balance_due
            if balance <= 0:
                continue

            days = cls._overdue_days(inv, today)
            if days == 0:
                bucket = 'not_yet_due'
            elif days <= 30:
                bucket = 'overdue_1_30'
            elif days <= 60:
                bucket = 'overdue_31_60'
            else:
                bucket = 'overdue_61_plus'
            buckets[bucket] += balance

            result = cls.assess_invoice(inv, today=today)
            if result:
                assessments.append({'invoice': inv, **result})

        projected_collectible = sum(
            (amount * Decimal(str(COLLECTION_PROBABILITY[bucket])) for bucket, amount in buckets.items()),
            Decimal('0'),
        ).quantize(Decimal('0.01'))
        projected_at_risk = (total_outstanding - projected_collectible).quantize(Decimal('0.01'))

        assessments.sort(key=lambda a: a['risk_score'], reverse=True)
        high_risk_count = sum(1 for a in assessments if a['risk_band'] == 'HIGH')
        critical_risk_count = sum(1 for a in assessments if a['risk_band'] == 'CRITICAL')

        return {
            'computed_at': today,
            'total_billed': total_billed,
            'total_collected': total_collected,
            'total_outstanding': total_outstanding,
            'buckets': buckets,
            'projected_collectible': projected_collectible,
            'projected_at_risk': projected_at_risk,
            'assessments': assessments,
            'high_risk_count': high_risk_count,
            'critical_risk_count': critical_risk_count,
        }

    # =================================================================
    # NEW INTELLIGENCE UPGRADE: CONVERSATIONAL AI RUN METHOD
    # =================================================================
    def run(self, school, user, question):
        """
        Processes natural language queries specifically for finance.
        This is what the AI Router actually calls.
        """
        question_lower = question.lower()

        # Compute the financial snapshot once for this query
        snapshot = self.compute_school_snapshot(school)

        # --------------------------------------------------
        # 1. "List of students still owing"
        # --------------------------------------------------
        if any(word in question_lower for word in ["list", "who", "owing", "unpaid", "students"]):

            # Grab the invoices with the highest risk scores
            high_risk_invoices = snapshot['assessments']

            if not high_risk_invoices:
                return "✅ Excellent news! No students are currently owing school fees."

            # Format the list for the chat (Limit to top 20 so chat doesn't crash)
            max_display = 20
            total_owing = len(high_risk_invoices)

            response_lines = [
                f"📋 **Students Currently Owing Fees**:\n",
                f"*Total owing students: {total_owing}*"
            ]

            for idx, assessment in enumerate(high_risk_invoices[:max_display]):
                invoice = assessment['invoice']
                student_name = invoice.student.user.get_full_name()
                balance = invoice.balance_due
                risk_band = assessment['risk_band']

                # Add an emoji based on risk band
                emoji = "🔴" if risk_band == "CRITICAL" else "🟠" if risk_band == "HIGH" else "🟡" if risk_band == "MEDIUM" else "🟢"

                response_lines.append(
                    f"{idx + 1}. {emoji} **{student_name}** — ${balance} (Risk: {risk_band})"
                )

            # If there are more than 20, tell the user
            if total_owing > max_display:
                response_lines.append(f"\n*...and {total_owing - max_display} more students.*")

            return "\n".join(response_lines)

        # --------------------------------------------------
        # 2. "What is the total outstanding balance?"
        # --------------------------------------------------
        if any(word in question_lower for word in ["total", "outstanding", "balance", "overall"]):
            total_owed = snapshot['total_outstanding']
            projected_collect = snapshot['projected_collectible']
            projected_loss = snapshot['projected_at_risk']

            return (
                f"📊 **Overall Financial Health**\n\n"
                f"💰 **Total Outstanding Balance:** ${total_owed}\n"
                f"✅ **Projected Collectible:** ${projected_collect}\n"
                f"⚠️ **Projected At-Risk (Bad Debt):** ${projected_loss}\n\n"
                f"*High-Risk Students: {snapshot['high_risk_count']} | Critical-Risk: {snapshot['critical_risk_count']}*"
            )

        # --------------------------------------------------
        # 3. General/Generic financial summary (LLM Fallback)
        # --------------------------------------------------
        return (
            f"I can provide financial insights for your school.\n\n"
            f"Current snapshot as of {snapshot['computed_at']}:\n"
            f"• 💰 **Total outstanding fees:** ${snapshot['total_outstanding']}\n"
            f"• 📊 **Projected collectible:** ${snapshot['projected_collectible']}\n"
            f"• ⚠️ **Students at risk:** {snapshot['high_risk_count'] + snapshot['critical_risk_count']} (High/Critical)\n\n"
            f"Try asking:\n"
            f"- 'List students still owing fees'\n"
            f"- 'What is the total outstanding balance?'"
        )