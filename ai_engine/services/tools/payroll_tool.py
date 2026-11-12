# ai_engine/services/tools/payroll_tool.py
"""
Payroll AI Tool
"""

from django.db.models import Sum, Count
from django.utils import timezone
from staff.models import Teacher
from finance.models import Payment, Invoice


class PayrollTool:
    """AI tool for payroll and salary queries."""

    def run(self, school, user, question, context=None):
        """Process payroll-related queries."""
        question_lower = question.lower()

        # ==========================================================
        # PAYROLL SUMMARY
        # ==========================================================
        if any(word in question_lower for word in ["summary", "overview", "total", "month"]):
            return self._get_payroll_summary(school)

        # ==========================================================
        # SALARY QUERY
        # ==========================================================
        if any(word in question_lower for word in ["salary", "pay", "wages", "paid"]):
            return self._get_salary_info(school, question_lower)

        # ==========================================================
        # STAFF PAYMENTS
        # ==========================================================
        if "payment" in question_lower or "paid" in question_lower:
            return self._get_payment_info(school)

        return self._get_help()

    def _get_payroll_summary(self, school):
        """Get payroll summary."""
        total_staff = Teacher.objects.filter(school=school, is_active=True).count()

        # This is a placeholder - actual payroll data would come from a Payroll model
        return f"""
📊 **Payroll Summary**

• **Total Staff:** {total_staff}
• **This Month's Payroll:** Processing...
• **Next Pay Date:** End of month

*Note: Detailed payroll information requires the Payroll module to be fully configured.*
"""

    def _get_salary_info(self, school, question):
        """Get salary information."""
        # Placeholder - would query actual salary data
        return """
💰 **Salary Information**

I can help you with salary-related queries once the Payroll module is fully configured.

To set up payroll, please ensure:
1. Staff salary grades are configured
2. Monthly payroll is processed
3. Bank details are set up

Contact your system administrator for more details.
"""

    def _get_payment_info(self, school):
        """Get payment information."""
        # Placeholder - would query actual payment data
        return """
💳 **Payment Information**

Payment information will be available once the Payroll module is activated.

Features coming soon:
• Staff salary payments
• Payment history
• Payslip generation
• Bank transfer processing
"""

    def _get_help(self):
        """Get help text for payroll queries."""
        return """
💰 **Payroll Assistant** - I can help you with:

• Payroll summaries and overview
• Staff salary information
• Payment tracking
• Payslip generation

Try asking:
• "Show me this month's payroll summary"
• "What is the total staff salary?"
• "List staff payments this month"
"""