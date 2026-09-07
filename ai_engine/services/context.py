# ai_engine/services/context.py

from .permissions import get_ai_permissions
from .role_ai_policy import (
    get_policy,
    get_ai_capabilities,
    get_student_scope,
    get_class_scope,
)


class SchoolAIContext:

    def __init__(self, user):
        self.user = user
        self.school = getattr(user, "school", None)
        self.permissions = get_ai_permissions(user)

    def get_identity_context(self):
        user = self.user

        full_name = ""

        try:
            full_name = user.get_full_name()
        except Exception:
            full_name = getattr(user, "username", "")

        return {
            "user_id": user.pk,
            "name": full_name,
            "role": getattr(user, "role", ""),
            "school_id": getattr(self.school, "id", None),
            "school_name": getattr(self.school, "name", ""),
        }

    def get_permission_context(self):
        p = self.permissions

        return {
            "can_view_students": p.can_view_students,
            "can_view_student_results": p.can_view_student_results,
            "can_view_attendance": p.can_view_attendance,

            "can_view_classes": p.can_view_classes,
            "can_view_class_results": p.can_view_class_results,
            "can_view_exams": p.can_view_exams,

            "can_generate_lessons": p.can_generate_lessons,
            "can_generate_questions": p.can_generate_questions,
            "can_generate_exams": p.can_generate_exams,
            "can_analyse_performance": p.can_analyse_performance,

            "can_view_staff": p.can_view_staff,
            "can_view_school_reports": p.can_view_school_reports,

            "can_view_finance": p.can_view_finance,
            "can_view_fees": p.can_view_fees,

            "can_research_ghana_education":
                p.can_research_ghana_education,

            "student_scope": p.student_scope,
            "class_scope": p.class_scope,
        }

    def build(self):
        """Build the complete AI context for the user."""
        policy = get_policy(self.user)

        return {
            "identity": self.get_identity_context(),
            "permissions": self.get_permission_context(),
            "ai_policy": {
                "label": policy["label"],
                "scope": policy["scope"],
                "description": policy["description"],
                "capabilities": get_ai_capabilities(self.user),
                "student_scope": get_student_scope(self.user),
                "class_scope": get_class_scope(self.user),
            },
        }