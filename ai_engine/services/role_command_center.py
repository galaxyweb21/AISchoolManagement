"""Role-scoped command-center dashboard data."""

from django.db.models import Count, Avg
from django.utils.timezone import localdate, timedelta

from students.models import Student
from attendance.models import Attendance
from assessments.models import Grade
from academics.models import SchoolClass, TimetableEntry
from staff.models import Teacher
from .copilot_context import allowed_students, _teacher_classes
from .role_ai_policy import get_policy, can_use


class RoleCommandCenterService:
    @staticmethod
    def build(user, school):
        policy = get_policy(user)
        students = allowed_students(user, school)
        context = {
            "ai_role": policy["label"],
            "ai_scope": policy["scope"],
            "ai_scope_description": policy["description"],
            "ai_capabilities": sorted(policy["capabilities"]),
            "today": localdate(),
            "students_count": students.count(),
        }

        if can_use(user, "attendance"):
            attendance = Attendance.objects.filter(
                school=school,
                student__in=students,
                date=localdate(),
            )
            marked = attendance.count()
            present = attendance.filter(status="PRESENT").count()
            context.update({
                "attendance_marked": marked,
                "attendance_present": present,
                "attendance_rate": round(present * 100 / marked, 1) if marked else 0,
            })

        if can_use(user, "academics"):
            classes = SchoolClass.objects.filter(school=school)
            if user.role == "TEACHER":
                classes = _teacher_classes(user, school)
            elif user.role == "HOD":
                classes = classes.filter(student_enrollments__in=students).distinct()
            context["classes_count"] = classes.count()
            context["classes"] = list(classes.values("name", "grade_level__name")[:12])

        if can_use(user, "exams") or can_use(user, "reports"):
            grades = Grade.objects.filter(student__in=students)
            context["grades_count"] = grades.count()
            context["average_score"] = round(float(grades.aggregate(avg=Avg("score_achieved"))["avg"] or 0), 1)

        if can_use(user, "finance"):
            from finance.models import Invoice
            invoices = Invoice.objects.filter(school=school, student__in=students)
            context["unpaid_invoices"] = invoices.filter(status__in=["UNPAID", "PARTIAL"]).count()

        if user.role == "TEACHER":
            try:
                teacher = user.teacher_profile
                context["subjects"] = list(teacher.subjects.values_list("name", flat=True))
            except Exception:
                context["subjects"] = []

        if user.role == "HOD":
            try:
                context["department"] = user.staff_profile.department or user.teacher_profile.department
            except Exception:
                context["department"] = "Department"

        if user.role == "PARENT":
            context["children"] = list(
                students.values("user__first_name", "user__last_name", "grade_level__name", "school_class__name")
            )

        if user.role == "STUDENT":
            student = students.first()
            if student:
                context["student"] = {
                    "name": student.user.get_full_name(),
                    "admission_number": student.admission_number,
                    "class": getattr(student.school_class, "name", ""),
                    "grade_level": getattr(student.grade_level, "name", ""),
                }

        return context
