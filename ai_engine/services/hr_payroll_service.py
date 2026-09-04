# ai_engine/services/hr_payroll_service.py
"""
HR & Payroll AI Service
Handles natural language queries about staff, HR, and payroll
"""

from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
import logging

from staff.models import (
    StaffProfile,
    StaffGrade,
    SalaryStructure,
    Allowance,
    Deduction,
    StaffAllowance,
    StaffDeduction,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    LeaveRequest,  # Use LeaveRequest instead of Leave
    LeaveType,     # Use LeaveType for leave type information
    StaffLeaveBalance,
    Teacher,
    Department,
)

logger = logging.getLogger(__name__)


class HRPayrollService:
    """
    AI service for HR and Payroll queries
    """

    def run(self, school, user, question, context=None):
        """Process HR and Payroll queries"""
        question_lower = question.lower()

        # ==========================================================
        # STAFF COUNT
        # ==========================================================
        if any(word in question_lower for word in ["how many", "count", "total staff", "staff count"]):
            return self._get_staff_count(school, question_lower)

        # ==========================================================
        # STAFF LIST
        # ==========================================================
        if any(word in question_lower for word in ["list", "show me", "who are", "all staff"]):
            return self._list_staff(school, question_lower)

        # ==========================================================
        # PAYROLL
        # ==========================================================
        if any(word in question_lower for word in ["payroll", "salary", "pay", "wages"]):
            return self._get_payroll_info(school, question_lower)

        # ==========================================================
        # SALARY
        # ==========================================================
        if any(word in question_lower for word in ["salary", "earn", "paid", "payment"]):
            return self._get_salary_info(school, question_lower)

        # ==========================================================
        # LEAVE
        # ==========================================================
        if any(word in question_lower for word in ["leave", "absence", "off", "holiday"]):
            return self._get_leave_info(school, question_lower)

        # ==========================================================
        # DEPARTMENT
        # ==========================================================
        if "department" in question_lower:
            return self._get_department_info(school, question_lower)

        # ==========================================================
        # GRADE / POSITION
        # ==========================================================
        if any(word in question_lower for word in ["grade", "position", "role", "level"]):
            return self._get_grade_info(school, question_lower)

        # ==========================================================
        # PAYSLIP
        # ==========================================================
        if "payslip" in question_lower or "slip" in question_lower:
            return self._get_payslip_info(school, question_lower)

        # ==========================================================
        # HELP
        # ==========================================================
        return self._get_help()

    def _get_staff_count(self, school, question):
        """Get staff count information"""
        total = StaffProfile.objects.filter(school=school, is_active=True).count()
        teachers = StaffProfile.objects.filter(school=school, is_active=True, staff_position='TEACHER').count()
        admin = StaffProfile.objects.filter(
            school=school,
            is_active=True,
            staff_position__in=['SCHOOL_ADMIN', 'REGISTRAR', 'SECRETARY', 'BURSAR', 'HOD']
        ).count()
        support = StaffProfile.objects.filter(
            school=school,
            is_active=True,
            staff_position__in=['IT_SUPPORT', 'LIBRARIAN']
        ).count()

        return f"""
📊 **Staff Summary**

• **Total Staff:** {total}
• **Teachers:** {teachers}
• **Administrators:** {admin}
• **Support Staff:** {support}

💡 *Tip: Ask me about specific departments or positions for more detail.*
"""

    def _list_staff(self, school, question):
        """List staff members"""
        staff = StaffProfile.objects.filter(school=school, is_active=True).select_related('user')

        if not staff:
            return "No active staff members found."

        # Filter by position if specified
        if "teacher" in question:
            staff = staff.filter(staff_position='TEACHER')
        elif "admin" in question or "administrator" in question:
            staff = staff.filter(staff_position__in=['SCHOOL_ADMIN', 'REGISTRAR', 'SECRETARY', 'BURSAR', 'HOD'])
        elif "hod" in question or "head" in question:
            staff = staff.filter(staff_position='HOD')

        if not staff:
            return "No staff members found matching that criteria."

        response = f"📋 **Staff List ({staff.count()} members)**\n\n"

        for s in staff[:20]:
            response += f"• **{s.user.get_full_name()}** - {s.get_staff_position_display()}"
            if s.department:
                response += f" ({s.department})"
            response += f"\n  *ID: {s.staff_id}*\n\n"

        if staff.count() > 20:
            response += f"\n*...and {staff.count() - 20} more staff members.*"

        return response

    def _get_payroll_info(self, school, question):
        """Get payroll information"""
        # Get current payroll period
        current_period = PayrollPeriod.objects.filter(
            school=school,
            status__in=['OPEN', 'PROCESSING']
        ).first()

        if not current_period:
            return "No active payroll period found. Please create a payroll period first."

        # Get payroll runs for this period
        runs = PayrollRun.objects.filter(
            school=school,
            payroll_period=current_period
        )

        total_gross = runs.aggregate(Sum('gross_pay'))['gross_pay__sum'] or Decimal('0.00')
        total_net = runs.aggregate(Sum('net_pay'))['net_pay__sum'] or Decimal('0.00')
        processed = runs.filter(status='PAID').count()
        pending = runs.filter(status__in=['PENDING', 'CALCULATED', 'REVIEWED']).count()

        return f"""
💼 **Payroll Information - {current_period.name}**

• **Period:** {current_period.period_start} to {current_period.period_end}
• **Payment Date:** {current_period.payment_date}
• **Total Staff:** {runs.count()}
• **Processed/Paid:** {processed}
• **Pending:** {pending}
• **Total Gross Pay:** ₵{total_gross:,.2f}
• **Total Net Pay:** ₵{total_net:,.2f}
• **Status:** {current_period.get_status_display()}

💡 *Tip: Ask about specific staff members or departments for detailed payroll information.*
"""

    def _get_salary_info(self, school, question):
        """Get salary information for staff"""
        # Try to find a specific staff member
        staff = None
        if "name" in question or "staff" in question:
            words = question.split()
            for word in words:
                if len(word) > 2 and word.isalpha():
                    potential_staff = StaffProfile.objects.filter(
                        school=school,
                        user__first_name__icontains=word,
                        is_active=True
                    ).first()
                    if potential_staff:
                        staff = potential_staff
                        break

        if staff:
            return self._get_staff_salary(staff)

        return self._get_payroll_summary(school, question)

    def _get_staff_salary(self, staff):
        """Get salary details for a specific staff member"""
        latest_run = PayrollRun.objects.filter(
            school=staff.school,
            staff=staff
        ).order_by('-created_at').first()

        if latest_run:
            payslip = Payslip.objects.filter(payroll_run=latest_run).first()
            earnings = payslip.earnings if payslip else {}
            deductions = payslip.deductions if payslip else {}

            response = f"""
💰 **Salary Information - {staff.user.get_full_name()}**

• **Staff ID:** {staff.staff_id}
• **Position:** {staff.get_staff_position_display()}
• **Department:** {staff.department or 'N/A'}

**Latest Payslip ({latest_run.payroll_period.name})**
• **Basic Salary:** ₵{latest_run.basic_salary:,.2f}
• **Allowances:** ₵{latest_run.total_allowances:,.2f}
• **Deductions:** ₵{latest_run.total_deductions:,.2f}
• **Gross Pay:** ₵{latest_run.gross_pay:,.2f}
• **Net Pay:** ₵{latest_run.net_pay:,.2f}
• **Days Worked:** {latest_run.days_worked}
• **Days Absent:** {latest_run.days_absent}
• **Status:** {latest_run.get_status_display()}
"""

            if earnings:
                response += "\n**Earnings Breakdown:**\n"
                for name, amount in earnings.items():
                    response += f"• {name}: ₵{amount:,.2f}\n"

            if deductions:
                response += "\n**Deductions Breakdown:**\n"
                for name, amount in deductions.items():
                    response += f"• {name}: ₵{amount:,.2f}\n"

            return response

        return f"""
💰 **Salary Information - {staff.user.get_full_name()}**

• **Staff ID:** {staff.staff_id}
• **Position:** {staff.get_staff_position_display()}

No payroll records found for this staff member. 
Please ensure payroll has been processed for the current period.
"""

    def _get_payroll_summary(self, school, question):
        """Get payroll summary across the school"""
        periods = PayrollPeriod.objects.filter(
            school=school,
            status__in=['CLOSED', 'APPROVED']
        ).order_by('-period_end')[:3]

        if not periods:
            return "No completed payroll periods found."

        response = "📊 **Payroll Summary (Last 3 Periods)**\n\n"

        for period in periods:
            runs = PayrollRun.objects.filter(school=school, payroll_period=period)
            total_net = runs.aggregate(Sum('net_pay'))['net_pay__sum'] or Decimal('0.00')
            staff_count = runs.count()

            response += f"**{period.name}**\n"
            response += f"• Staff: {staff_count}\n"
            response += f"• Total Net Pay: ₵{total_net:,.2f}\n"
            response += f"• Avg Net Pay: ₵{(total_net / staff_count) if staff_count else 0:,.2f}\n\n"

        return response

    def _get_leave_info(self, school, question):
        """Get leave information using the enhanced LeaveRequest model"""
        today = timezone.localdate()

        # Get staff on leave today (using LeaveRequest with APPROVED status)
        active_leaves = LeaveRequest.objects.filter(
            school=school,
            start_date__lte=today,
            end_date__gte=today,
            status='APPROVED'
        ).select_related('staff__user', 'leave_type')

        if active_leaves.exists():
            response = "🏖️ **Staff on Leave Today**\n\n"
            for leave in active_leaves:
                response += f"• **{leave.staff.user.get_full_name()}** - {leave.leave_type.name}\n"
                response += f"  {leave.start_date} to {leave.end_date} ({leave.requested_days} days)\n\n"
        else:
            response = "🏖️ **No staff are currently on leave.**\n"

        # Get pending leave requests
        pending = LeaveRequest.objects.filter(
            school=school,
            status='PENDING'
        ).count()

        if pending:
            response += f"\n📋 **Pending Leave Requests:** {pending}\n"

        return response

    def _get_department_info(self, school, question):
        """Get department information"""
        departments = StaffProfile.objects.filter(
            school=school,
            is_active=True
        ).exclude(department__isnull=True).exclude(department='').values('department').distinct()

        if not departments:
            return "No departments found."

        response = "📋 **Departments**\n\n"

        for dept in departments:
            count = StaffProfile.objects.filter(
                school=school,
                department=dept['department'],
                is_active=True
            ).count()

            teachers = StaffProfile.objects.filter(
                school=school,
                department=dept['department'],
                is_active=True,
                staff_position='TEACHER'
            ).count()

            response += f"**{dept['department']}**\n"
            response += f"• Total Staff: {count}\n"
            response += f"• Teachers: {teachers}\n"
            response += f"• HOD: {self._get_hod_name(school, dept['department'])}\n\n"

        return response

    def _get_hod_name(self, school, department):
        """Get HOD name for a department"""
        hod = StaffProfile.objects.filter(
            school=school,
            department=department,
            staff_position='HOD',
            is_active=True
        ).select_related('user').first()

        return hod.user.get_full_name() if hod else "Not assigned"

    def _get_grade_info(self, school, question):
        """Get staff grade information"""
        grades = StaffGrade.objects.filter(school=school, is_active=True).order_by('level')

        if not grades:
            return "No staff grades configured."

        response = "📊 **Staff Grades**\n\n"

        for grade in grades:
            count = StaffProfile.objects.filter(
                school=school,
                is_active=True,
                staff_grade=grade
            ).count()

            SalaryStructure.objects.filter(
                school=staff.school,
                staff_grade=grade,
                is_active=True,
                effective_date__lte=payroll_period.period_end,
            ).order_by(
                "-effective_date",
                "-created_at",
            ).first()

            response += f"**{grade.name} ({grade.code})**\n"
            response += f"• Level: {grade.level}\n"
            if salary:
                response += f"• Basic Salary: ₵{salary.basic_salary:,.2f}\n"
            response += f"• Staff: {count}\n\n"

        return response

    def _get_payslip_info(self, school, question):
        """Get payslip information"""
        staff = None
        if "my" in question.lower():
            try:
                from accounts.models import User
                user = User.objects.get(pk=self.user.pk)
                staff = StaffProfile.objects.get(user=user)
            except (StaffProfile.DoesNotExist, User.DoesNotExist):
                pass
        else:
            words = question.split()
            for word in words:
                if len(word) > 2 and word.isalpha():
                    potential_staff = StaffProfile.objects.filter(
                        school=school,
                        user__first_name__icontains=word,
                        is_active=True
                    ).first()
                    if potential_staff:
                        staff = potential_staff
                        break

        if staff:
            payslip = Payslip.objects.filter(
                school=school,
                payroll_run__staff=staff
            ).order_by('-generated_at').first()

            if payslip:
                return self._format_payslip(payslip)
            else:
                return f"No payslip found for {staff.user.get_full_name()}."

        payslips = Payslip.objects.filter(
            school=school
        ).select_related('payroll_run__staff__user').order_by('-generated_at')[:5]

        if not payslips:
            return "No payslips generated yet."

        response = "📄 **Latest Payslips**\n\n"
        for ps in payslips:
            staff_name = ps.payroll_run.staff.user.get_full_name()
            response += f"• **{staff_name}** - {ps.payroll_run.payroll_period.name}\n"
            response += f"  Net Pay: ₵{ps.payroll_run.net_pay:,.2f}\n"
            response += f"  Generated: {ps.generated_at.strftime('%Y-%m-%d %H:%M')}\n\n"

        return response

    def _format_payslip(self, payslip):
        """Format a single payslip for display"""
        run = payslip.payroll_run
        staff = run.staff

        response = f"""
📄 **Payslip - {staff.user.get_full_name()}**

**Staff Details**
• Staff ID: {staff.staff_id}
• Position: {staff.get_staff_position_display()}
• Department: {staff.department or 'N/A'}

**Period Information**
• Period: {run.payroll_period.name}
• Payment Date: {run.payroll_period.payment_date}
• Days Worked: {run.days_worked}
• Days Absent: {run.days_absent}

**Earnings**
• Basic Salary: ₵{run.basic_salary:,.2f}
• Total Allowances: ₵{run.total_allowances:,.2f}
• Gross Pay: ₵{run.gross_pay:,.2f}

**Deductions**
• Total Deductions: ₵{run.total_deductions:,.2f}

**Net Pay: ₵{run.net_pay:,.2f}**

**Status:** {run.get_status_display()}
**Generated:** {payslip.generated_at.strftime('%Y-%m-%d %H:%M')}
"""

        return response

    def _get_help(self):
        """Get help text for HR queries"""
        return """
👔 **HR & Payroll Assistant** - I can help you with:

**Staff Management**
• List all staff or specific positions
• Staff counts and statistics
• Department information
• Staff grades and positions

**Payroll**
• Payroll summary and status
• Staff salary information
• Payslip generation and viewing
• Payroll processing status

**Leave Management**
• Staff on leave
• Pending leave requests
• Leave balances

**Try asking:**
• "How many teachers do we have?"
• "List all staff in the Mathematics department"
• "Show me this month's payroll summary"
• "What is John's salary?"
• "Who is on leave today?"
• "Show me my payslip"
• "How many staff are in each department?"
"""