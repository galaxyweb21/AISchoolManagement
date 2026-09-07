# finance/services/payment_plan_engine.py
from decimal import Decimal
from django.utils import timezone  # <-- ADD THIS IMPORT
from datetime import timedelta  # <-- ADD THIS IMPORT


class SmartPaymentPlanEngine:

    @staticmethod
    def generate_custom_installment_plan(total_balance: Decimal, max_installments: int = 4) -> list:
        """
        Breaks down overdue balances into manageable micro-installments
        spread across the remaining academic term.
        """
        if total_balance <= 0:
            return []

        installment_amount = round(total_balance / max_installments, 2)
        plan = []
        today = timezone.now().date()

        for i in range(1, max_installments + 1):
            due_date = today + timedelta(days=30 * i)
            plan.append({
                'installment_number': i,
                'amount_due': float(installment_amount),
                'due_date': due_date.isoformat(),
                'status': 'SCHEDULED'
            })
        return plan