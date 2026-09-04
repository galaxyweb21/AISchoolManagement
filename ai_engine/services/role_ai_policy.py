"""
Central AI authorization policy for the AI School Management system.

IMPORTANT
---------
This module is the SINGLE SOURCE OF TRUTH for AI role authorization.

The LLM must NEVER decide what a user is allowed to see.

This policy controls:

    - AI chat
    - Ghana Education research
    - school data access
    - student scope
    - class scope
    - academic intelligence
    - attendance
    - examinations
    - reports
    - finance
    - staff
    - payroll
    - AI teaching tools
    - school-level intelligence
    - predictive/risk intelligence

Actual records are still filtered by the relevant service/queryset.
This policy only determines what capabilities are available.
"""

# ============================================================================
# ROLE POLICIES
# ============================================================================

ROLE_POLICIES = {

    # ========================================================================
    # SUPER ADMIN
    # ========================================================================

    "SUPER_ADMIN": {
        "label": "Platform Administrator",
        "scope": "school",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "reports",
            "finance",
            "staff",
            "payroll",
            "research",
            "risk",
            "school_intelligence",
        },

        "description": (
            "Full school operational intelligence, academic intelligence, "
            "staff management, payroll, finance, predictive intelligence, "
            "risk monitoring and Ghana education research."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": True,
            "can_view_class_results": True,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": True,
            "can_analyse_performance": True,
            "can_generate_report_narrative": True,

            "can_view_staff": True,
            "can_view_school_reports": True,
            "can_view_school_settings": True,

            "can_view_finance": True,
            "can_view_fees": True,

            "can_view_risk": True,
            "can_view_school_intelligence": True,

            "can_research_ghana_education": True,

            "student_scope": "school",
            "class_scope": "school",
        },
    },

    # ========================================================================
    # SCHOOL ADMIN
    # ========================================================================

    "SCHOOL_ADMIN": {
        "label": "School Administrator",
        "scope": "school",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "reports",
            "finance",
            "staff",
            "payroll",
            "research",
            "risk",
            "school_intelligence",
        },

        "description": (
            "Whole-school intelligence, academic administration, staff "
            "management, payroll, finance, risk monitoring, decision "
            "support and Ghana education research."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": True,
            "can_view_class_results": True,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": True,
            "can_analyse_performance": True,
            "can_generate_report_narrative": True,

            "can_view_staff": True,
            "can_view_school_reports": True,
            "can_view_school_settings": True,

            "can_view_finance": True,
            "can_view_fees": True,

            "can_view_risk": True,
            "can_view_school_intelligence": True,

            "can_research_ghana_education": True,

            "student_scope": "school",
            "class_scope": "school",
        },
    },

    # ========================================================================
    # HEADMASTER
    # ========================================================================

    "HEADMASTER": {
        "label": "Headmaster",
        "scope": "school",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "reports",
            "staff",
            "research",
            "risk",
            "school_intelligence",
        },

        "description": (
            "Whole-school academic and operational intelligence, staff "
            "oversight, student performance monitoring, risk intelligence "
            "and Ghana education research. Finance access is restricted "
            "unless separately authorized."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": True,
            "can_view_class_results": True,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": True,
            "can_analyse_performance": True,
            "can_generate_report_narrative": True,

            "can_view_staff": True,
            "can_view_school_reports": True,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": False,

            "can_view_risk": True,
            "can_view_school_intelligence": True,

            "can_research_ghana_education": True,

            "student_scope": "school",
            "class_scope": "school",
        },
    },

    # ========================================================================
    # PRINCIPAL
    # ========================================================================

    "PRINCIPAL": {
        "label": "Principal",
        "scope": "school",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "reports",
            "staff",
            "research",
            "risk",
            "school_intelligence",
        },

        "description": (
            "Whole-school academic and operational intelligence, staff "
            "oversight, student performance monitoring, risk intelligence "
            "and Ghana education research. Finance access is restricted "
            "unless separately authorized."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": True,
            "can_view_class_results": True,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": True,
            "can_analyse_performance": True,
            "can_generate_report_narrative": True,

            "can_view_staff": True,
            "can_view_school_reports": True,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": False,

            "can_view_risk": True,
            "can_view_school_intelligence": True,

            "can_research_ghana_education": True,

            "student_scope": "school",
            "class_scope": "school",
        },
    },

    # ========================================================================
    # HOD
    # ========================================================================

    "HOD": {
        "label": "Head of Department",
        "scope": "department",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "reports",
            "staff",
            "research",
            "risk",
        },

        "description": (
            "Department-level academic intelligence, assigned student "
            "performance, attendance, examinations, staff intelligence "
            "within the department and Ghana education research."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": True,
            "can_view_class_results": True,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": True,
            "can_analyse_performance": True,
            "can_generate_report_narrative": True,

            "can_view_staff": True,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": False,

            "can_view_risk": True,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "department",
            "class_scope": "department",
        },
    },

    # ========================================================================
    # TEACHER
    # ========================================================================

    "TEACHER": {
        "label": "Teacher",
        "scope": "assigned",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "reports",
            "research",
        },

        "description": (
            "Assigned classes, assigned students, teaching support, "
            "attendance, examinations, performance analysis and Ghana "
            "education research."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": True,
            "can_view_class_results": True,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": True,
            "can_analyse_performance": True,
            "can_generate_report_narrative": True,

            "can_view_staff": False,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": False,

            "can_view_risk": False,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "assigned",
            "class_scope": "assigned",
        },
    },

    # ========================================================================
    # BURSAR
    # ========================================================================

    "BURSAR": {
        "label": "Bursar / Finance Officer",
        "scope": "finance",

        "capabilities": {
            "students",
            "finance",
            "staff",
            "payroll",
            "research",
        },

        "description": (
            "Finance intelligence, payroll, staff payroll information "
            "and limited student identity information."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": False,
            "can_view_attendance": False,

            "can_view_classes": False,
            "can_view_class_results": False,
            "can_view_exams": False,

            "can_generate_lessons": False,
            "can_generate_questions": False,
            "can_generate_exams": False,
            "can_analyse_performance": False,
            "can_generate_report_narrative": False,

            "can_view_staff": True,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": True,
            "can_view_fees": True,

            "can_view_risk": False,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "school",
            "class_scope": "none",
        },
    },

    # ========================================================================
    # ACCOUNTANT
    # ========================================================================

    "ACCOUNTANT": {
        "label": "Accountant",
        "scope": "finance",

        "capabilities": {
            "finance",
            "payroll",
            "research",
        },

        "description": (
            "Finance and payroll intelligence with no academic student "
            "record access."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": False,
            "can_view_student_results": False,
            "can_view_attendance": False,

            "can_view_classes": False,
            "can_view_class_results": False,
            "can_view_exams": False,

            "can_generate_lessons": False,
            "can_generate_questions": False,
            "can_generate_exams": False,
            "can_analyse_performance": False,
            "can_generate_report_narrative": False,

            "can_view_staff": False,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": True,
            "can_view_fees": True,

            "can_view_risk": False,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "none",
            "class_scope": "none",
        },
    },

    # ========================================================================
    # REGISTRAR
    # ========================================================================

    "REGISTRAR": {
        "label": "Registrar",
        "scope": "school",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "staff",
            "research",
        },

        "description": (
            "Admissions, enrolment, student records, attendance and "
            "administrative staff-record intelligence."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": False,
            "can_view_attendance": True,

            "can_view_classes": True,
            "can_view_class_results": False,
            "can_view_exams": False,

            "can_generate_lessons": False,
            "can_generate_questions": False,
            "can_generate_exams": False,
            "can_analyse_performance": False,
            "can_generate_report_narrative": False,

            "can_view_staff": True,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": False,

            "can_view_risk": False,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "school",
            "class_scope": "school",
        },
    },

    # ========================================================================
    # SECRETARY
    # ========================================================================

    "SECRETARY": {
        "label": "Secretary",
        "scope": "administrative",

        "capabilities": {
            "students",
            "attendance",
            "staff",
            "research",
        },

        "description": (
            "Administrative and communication support with protected "
            "academic, finance and payroll information."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": True,
            "can_view_student_results": False,
            "can_view_attendance": True,

            "can_view_classes": False,
            "can_view_class_results": False,
            "can_view_exams": False,

            "can_generate_lessons": False,
            "can_generate_questions": False,
            "can_generate_exams": False,
            "can_analyse_performance": False,
            "can_generate_report_narrative": False,

            "can_view_staff": True,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": False,

            "can_view_risk": False,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "school",
            "class_scope": "none",
        },
    },

    # ========================================================================
    # STUDENT
    # ========================================================================

    "STUDENT": {
        "label": "Student",
        "scope": "self",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "research",
        },

        "description": (
            "Personal learning support, personal academic information, "
            "study assistance and Ghana education research."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": False,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": False,
            "can_view_class_results": False,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": False,
            "can_analyse_performance": True,
            "can_generate_report_narrative": False,

            "can_view_staff": False,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": True,

            "can_view_risk": False,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "self",
            "class_scope": "none",
        },
    },

    # ========================================================================
    # PARENT
    # ========================================================================

    "PARENT": {
        "label": "Parent / Guardian",
        "scope": "children",

        "capabilities": {
            "students",
            "academics",
            "attendance",
            "exams",
            "research",
        },

        "description": (
            "Support for the parent's own children, academic progress, "
            "attendance, examination guidance and Ghana education research."
        ),

        "permissions": {
            "can_chat": True,
            "can_research": True,
            "can_use_school_data": True,

            "can_view_students": False,
            "can_view_student_results": True,
            "can_view_attendance": True,

            "can_view_classes": False,
            "can_view_class_results": False,
            "can_view_exams": True,

            "can_generate_lessons": True,
            "can_generate_questions": True,
            "can_generate_exams": False,
            "can_analyse_performance": True,
            "can_generate_report_narrative": False,

            "can_view_staff": False,
            "can_view_school_reports": False,
            "can_view_school_settings": False,

            "can_view_finance": False,
            "can_view_fees": True,

            "can_view_risk": False,
            "can_view_school_intelligence": False,

            "can_research_ghana_education": True,

            "student_scope": "children",
            "class_scope": "none",
        },
    },
}


# ============================================================================
# SAFE DEFAULT
# ============================================================================

DEFAULT_POLICY = {
    "label": "User",
    "scope": "none",
    "capabilities": {
        "research",
    },
    "description": (
        "General Ghana education research only. "
        "No private school records are available."
    ),
    "permissions": {
        "can_chat": True,
        "can_research": True,
        "can_use_school_data": False,

        "can_view_students": False,
        "can_view_student_results": False,
        "can_view_attendance": False,

        "can_view_classes": False,
        "can_view_class_results": False,
        "can_view_exams": False,

        "can_generate_lessons": False,
        "can_generate_questions": False,
        "can_generate_exams": False,
        "can_analyse_performance": False,
        "can_generate_report_narrative": False,

        "can_view_staff": False,
        "can_view_school_reports": False,
        "can_view_school_settings": False,

        "can_view_finance": False,
        "can_view_fees": False,

        "can_view_risk": False,
        "can_view_school_intelligence": False,

        "can_research_ghana_education": True,

        "student_scope": "none",
        "class_scope": "none",
    },
}


# ============================================================================
# POLICY HELPERS
# ============================================================================

def get_policy(user):
    """
    Return the single authoritative AI policy for the authenticated user.
    """

    if not user:
        return DEFAULT_POLICY

    role = getattr(user, "role", "") or ""
    role = str(role).upper().strip()

    return ROLE_POLICIES.get(
        role,
        DEFAULT_POLICY,
    )


def can_use(user, capability):
    """
    Check whether the user's role has a specific AI capability.
    """

    policy = get_policy(user)

    return capability in policy.get(
        "capabilities",
        set(),
    )


def get_permission(user, permission_name, default=False):
    """
    Return a detailed permission from the same central policy.

    This replaces role-specific permission duplication in other modules.
    """

    policy = get_policy(user)

    return policy.get(
        "permissions",
        {}
    ).get(
        permission_name,
        default,
    )


def get_student_scope(user):
    """
    Return the user's authorized student scope.
    """

    return get_permission(
        user,
        "student_scope",
        "none",
    )


def get_class_scope(user):
    """
    Return the user's authorized class scope.
    """

    return get_permission(
        user,
        "class_scope",
        "none",
    )


def get_ai_capabilities(user):
    """
    Return a sorted list of capabilities available to the user.
    """

    return sorted(
        get_policy(user).get(
            "capabilities",
            set(),
        )
    )


def is_known_ai_role(user):
    """
    Determine whether the user's role is explicitly configured.
    """

    if not user:
        return False

    role = getattr(user, "role", "") or ""

    return str(role).upper().strip() in ROLE_POLICIES