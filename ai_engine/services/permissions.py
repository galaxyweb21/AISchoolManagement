"""
Compatibility layer for detailed AI permissions.

IMPORTANT:
-------------
Do not add role-specific authorization logic here.

The authoritative role policy lives in:

    ai_engine/services/role_ai_policy.py

This module converts that policy into the AIPermissions object used by
existing views and templates.
"""

from dataclasses import dataclass

from .role_ai_policy import (
    get_policy,
    get_permission,
    get_ai_capabilities,
)


@dataclass
class AIPermissions:

    # ========================================================================
    # CORE AI
    # ========================================================================

    can_chat: bool = False
    can_research: bool = False

    # ========================================================================
    # SCHOOL DATA
    # ========================================================================

    can_use_school_data: bool = False

    # ========================================================================
    # STUDENTS
    # ========================================================================

    can_view_students: bool = False
    can_view_student_results: bool = False
    can_view_attendance: bool = False

    # ========================================================================
    # CLASSES / ACADEMICS
    # ========================================================================

    can_view_classes: bool = False
    can_view_class_results: bool = False
    can_view_exams: bool = False

    # ========================================================================
    # AI TEACHING TOOLS
    # ========================================================================

    can_generate_lessons: bool = False
    can_generate_questions: bool = False
    can_generate_exams: bool = False
    can_analyse_performance: bool = False
    can_generate_report_narrative: bool = False

    # ========================================================================
    # ADMINISTRATION
    # ========================================================================

    can_view_staff: bool = False
    can_view_school_reports: bool = False
    can_view_school_settings: bool = False

    # ========================================================================
    # FINANCE
    # ========================================================================

    can_view_finance: bool = False
    can_view_fees: bool = False

    # ========================================================================
    # RISK / INTELLIGENCE
    # ========================================================================

    can_view_risk: bool = False
    can_view_school_intelligence: bool = False

    # ========================================================================
    # GHANA EDUCATION
    # ========================================================================

    can_research_ghana_education: bool = False

    # ========================================================================
    # DATA SCOPE
    # ========================================================================

    student_scope: str = "none"
    class_scope: str = "none"

    # ========================================================================
    # CAPABILITIES
    # ========================================================================

    capabilities: tuple = ()


def get_ai_permissions(user):
    """
    Build the compatibility permission object from the central AI policy.

    There is intentionally NO role-specific authorization logic here.

    All role decisions are made by:

        role_ai_policy.py
    """

    if not user or not getattr(
        user,
        "is_authenticated",
        False,
    ):
        return AIPermissions(
            can_chat=False,
            can_research=False,
            can_use_school_data=False,
            can_research_ghana_education=False,
            student_scope="none",
            class_scope="none",
            capabilities=(),
        )

    policy = get_policy(user)

    capabilities = tuple(
        get_ai_capabilities(user)
    )

    return AIPermissions(

        # ====================================================================
        # CORE
        # ====================================================================

        can_chat=get_permission(
            user,
            "can_chat",
            False,
        ),

        can_research=get_permission(
            user,
            "can_research",
            False,
        ),

        can_use_school_data=get_permission(
            user,
            "can_use_school_data",
            False,
        ),

        # ====================================================================
        # STUDENTS
        # ====================================================================

        can_view_students=get_permission(
            user,
            "can_view_students",
            False,
        ),

        can_view_student_results=get_permission(
            user,
            "can_view_student_results",
            False,
        ),

        can_view_attendance=get_permission(
            user,
            "can_view_attendance",
            False,
        ),

        # ====================================================================
        # ACADEMICS
        # ====================================================================

        can_view_classes=get_permission(
            user,
            "can_view_classes",
            False,
        ),

        can_view_class_results=get_permission(
            user,
            "can_view_class_results",
            False,
        ),

        can_view_exams=get_permission(
            user,
            "can_view_exams",
            False,
        ),

        # ====================================================================
        # AI TEACHING
        # ====================================================================

        can_generate_lessons=get_permission(
            user,
            "can_generate_lessons",
            False,
        ),

        can_generate_questions=get_permission(
            user,
            "can_generate_questions",
            False,
        ),

        can_generate_exams=get_permission(
            user,
            "can_generate_exams",
            False,
        ),

        can_analyse_performance=get_permission(
            user,
            "can_analyse_performance",
            False,
        ),

        can_generate_report_narrative=get_permission(
            user,
            "can_generate_report_narrative",
            False,
        ),

        # ====================================================================
        # ADMINISTRATION
        # ====================================================================

        can_view_staff=get_permission(
            user,
            "can_view_staff",
            False,
        ),

        can_view_school_reports=get_permission(
            user,
            "can_view_school_reports",
            False,
        ),

        can_view_school_settings=get_permission(
            user,
            "can_view_school_settings",
            False,
        ),

        # ====================================================================
        # FINANCE
        # ====================================================================

        can_view_finance=get_permission(
            user,
            "can_view_finance",
            False,
        ),

        can_view_fees=get_permission(
            user,
            "can_view_fees",
            False,
        ),

        # ====================================================================
        # RISK / INTELLIGENCE
        # ====================================================================

        can_view_risk=get_permission(
            user,
            "can_view_risk",
            False,
        ),

        can_view_school_intelligence=get_permission(
            user,
            "can_view_school_intelligence",
            False,
        ),

        # ====================================================================
        # GHANA EDUCATION
        # ====================================================================

        can_research_ghana_education=get_permission(
            user,
            "can_research_ghana_education",
            False,
        ),

        # ====================================================================
        # SCOPE
        # ====================================================================

        student_scope=get_permission(
            user,
            "student_scope",
            "none",
        ),

        class_scope=get_permission(
            user,
            "class_scope",
            "none",
        ),

        # ====================================================================
        # CAPABILITIES
        # ====================================================================

        capabilities=capabilities,
    )