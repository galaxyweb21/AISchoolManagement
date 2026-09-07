# ai_engine/services/tools/staff_tool.py
"""
Staff Management AI Tool
"""

from django.db.models import Count, Q
from django.utils import timezone
from staff.models import Teacher, TeacherAbsence
from users.models import User


class StaffTool:
    """AI tool for staff management queries."""

    def run(self, school, user, question, context=None):
        """Process staff-related queries."""
        question_lower = question.lower()

        # ==========================================================
        # LIST STAFF
        # ==========================================================
        if any(word in question_lower for word in ["list", "show", "who", "all", "staff"]):
            if "teacher" in question_lower or "teachers" in question_lower:
                return self._list_teachers(school)
            return self._list_all_staff(school)

        # ==========================================================
        # STAFF ABSENCE
        # ==========================================================
        if any(word in question_lower for word in ["absent", "absence", "leave", "away"]):
            return self._get_absences(school, question_lower)

        # ==========================================================
        # STAFF COUNT
        # ==========================================================
        if any(word in question_lower for word in ["count", "many", "number", "total"]):
            return self._count_staff(school)

        # ==========================================================
        # DEPARTMENT
        # ==========================================================
        if "department" in question_lower:
            return self._get_department_info(school, question_lower)

        return self._get_help()

    def _list_teachers(self, school):
        """List all teachers."""
        teachers = Teacher.objects.filter(school=school, is_active=True).select_related('user')
        if not teachers:
            return "No active teachers found in the school."

        response = f"📋 **Teachers ({teachers.count()})**\n\n"
        for t in teachers[:20]:
            subjects = ", ".join([s.name for s in t.subjects.all()[:5]])
            response += f"• **{t.user.get_full_name()}**"
            if subjects:
                response += f" - {subjects}"
            response += "\n"

        if teachers.count() > 20:
            response += f"\n*...and {teachers.count() - 20} more teachers.*"

        return response

    def _list_all_staff(self, school):
        """List all staff members."""
        staff = User.objects.filter(school=school, is_active=True, role__in=['TEACHER', 'STAFF', 'ADMIN'])
        if not staff:
            return "No staff members found."

        response = f"📋 **Staff Members ({staff.count()})**\n\n"
        for s in staff[:20]:
            response += f"• **{s.get_full_name()}** - {s.get_role_display()}\n"

        if staff.count() > 20:
            response += f"\n*...and {staff.count() - 20} more staff members.*"

        return response

    def _get_absences(self, school, question):
        """Get staff absence information."""
        today = timezone.localdate()
        if "today" in question:
            absences = TeacherAbsence.objects.filter(school=school, date=today)
        elif "this month" in question or "month" in question:
            month_start = today.replace(day=1)
            absences = TeacherAbsence.objects.filter(school=school, date__gte=month_start)
        else:
            absences = TeacherAbsence.objects.filter(school=school)[:10]

        if not absences:
            return "✅ No staff absences found."

        response = f"📋 **Staff Absences**\n\n"
        for a in absences[:10]:
            response += f"• **{a.teacher.user.get_full_name()}** - {a.date} ({a.get_reason_display()})\n"

        return response

    def _count_staff(self, school):
        """Count staff members."""
        total = User.objects.filter(school=school, is_active=True).exclude(role='STUDENT').count()
        teachers = Teacher.objects.filter(school=school, is_active=True).count()
        admin = User.objects.filter(school=school, is_active=True, role='SCHOOL_ADMIN').count()

        return f"""
📊 **Staff Summary**

• **Total Staff:** {total}
• **Teachers:** {teachers}
• **Administrators:** {admin}
• **Other Staff:** {total - teachers - admin}
"""

    def _get_department_info(self, school, question):
        """Get department information."""
        # Simple implementation - can be expanded
        departments = Teacher.objects.filter(school=school, is_active=True).values('department').distinct()
        if not departments:
            return "No departments found."

        response = f"📋 **Departments**\n\n"
        for dept in departments:
            if dept['department']:
                count = Teacher.objects.filter(school=school, department=dept['department']).count()
                response += f"• **{dept['department']}** - {count} teachers\n"

        return response

    def _get_help(self):
        """Get help text for staff queries."""
        return """
👨‍🏫 **Staff Management** - I can help you with:

• List all teachers or staff members
• View staff absences
• Staff counts and statistics
• Department information
• Staff profiles

Try asking:
• "List all teachers"
• "Show me staff absences today"
• "How many teachers do we have?"
• "Show me the mathematics department"
"""