from django.db.models import Q
from students.models import Student
from ai_engine.services.finance_engine import FinanceInsightService


class StudentTool:
    """
    Enterprise Student AI Tool.
    Handles every student-related question.
    """

    name = "student"

    @staticmethod
    def run(school, user, question):
        question_lower = question.lower()

        # --------------------------------------------------
        # SMART INTENT REDIRECTION
        # If the question is about students AND money, hand it to Finance.
        # --------------------------------------------------
        finance_keywords = ["fee", "fees", "payment", "money", "billing", "owing", "unpaid", "debt"]
        if any(word in question_lower for word in finance_keywords):
            return FinanceInsightService().run(
                school=school,
                user=user,
                question=question
            )

        # --------------------------------------------------
        # STANDARD STUDENT LOGIC
        # --------------------------------------------------
        students = Student.objects.filter(
            school=school,
            is_active=True
        ).select_related("user")

        # Student count
        if any(word in question_lower for word in [
            "how many students",
            "student count",
            "number of students",
            "total students",
        ]):
            return f"There are {students.count()} active students."

        # Student names
        if any(word in question_lower for word in [
            "student names",
            "names of the students",
            "list students",
            "show students",
            "all students",
        ]):
            names = []
            for s in students[:50]:
                names.append(s.user.get_full_name())

            if not names:
                return "No students were found."

            return "Active students:\n\n" + "\n".join(f"• {n}" for n in names)

        # Search student
        if "student" in question_lower:
            search = question_lower.replace("student", "").strip()

            if search:
                qs = students.filter(
                    Q(user__first_name__icontains=search) |
                    Q(user__last_name__icontains=search) |
                    Q(admission_number__icontains=search)
                )

                if qs.exists():
                    s = qs.first()
                    return (
                        f"{s.user.get_full_name()}\n"
                        f"Admission No: {s.admission_number}"
                    )

        # --------------------------------------------------
        # Fallback
        # --------------------------------------------------
        return (
            "I can help with:\n"
            "• Student list\n"
            "• Student count\n"
            "• Student search by name or ID"
        )