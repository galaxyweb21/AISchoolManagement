"""
Staff Leave Policy Helpers

Central source-of-truth helpers for staff leave entitlement.

Policy priority:

1. Active StaffGradeLeavePolicy
2. Legacy StaffGrade entitlement fields
3. LeaveType.default_days

IMPORTANT
--------
This module does not create or modify leave balances.

Balance creation and balance calculations belong to leave_service.py.

This module exists to provide consistent policy lookup for:
    - Staff profiles
    - Leave forms
    - Leave views
    - HR dashboards
    - Payroll/HR integrations
    - AI HR insights
"""

from decimal import Decimal

from staff.models import StaffGradeLeavePolicy


# ============================================================================
# DECIMAL HELPER
# ============================================================================

def _decimal(value, default="0.0"):
    """
    Safely convert a value to Decimal.
    """

    if value is None:
        return Decimal(default)

    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return Decimal(default)


# ============================================================================
# POLICY LOOKUP
# ============================================================================

def get_staff_grade_leave_policy(staff, leave_type):
    """
    Return the active StaffGradeLeavePolicy for a staff member.

    Returns:
        StaffGradeLeavePolicy instance or None
    """

    if not staff or not leave_type:
        return None

    grade = getattr(staff, "staff_grade", None)

    if not grade:
        return None

    school = getattr(staff, "school", None)

    if not school:
        return None

    return (
        StaffGradeLeavePolicy.objects
        .filter(
            school=school,
            staff_grade=grade,
            leave_type=leave_type,
            is_active=True,
        )
        .select_related(
            "staff_grade",
            "leave_type",
        )
        .first()
    )


# ============================================================================
# LEAVE ENTITLEMENT
# ============================================================================

def get_default_leave_days(staff_grade, leave_type, school=None):
    """
    Return the effective leave entitlement.

    Preferred order:

        StaffGradeLeavePolicy
            ↓
        Legacy StaffGrade fields
            ↓
        LeaveType.default_days

    `staff_grade` is retained as the first argument for backward
    compatibility with existing code.

    If a StaffGradeLeavePolicy exists, callers should ideally use
    `get_staff_leave_entitlement()` when the full staff object is available.
    """

    if not leave_type:
        return Decimal("0.0")

    # ------------------------------------------------------------------
    # Without a staff object we cannot safely determine the school's
    # StaffGradeLeavePolicy.
    #
    # Therefore this helper falls back to legacy grade/default logic.
    # ------------------------------------------------------------------

    if staff_grade:

        leave_name = (
            getattr(leave_type, "name", "")
            or getattr(leave_type, "code", "")
            or ""
        ).strip().lower()

        category = (
            getattr(
                leave_type,
                "category",
                "",
            )
            or ""
        ).upper()

        # --------------------------------------------------------------
        # Legacy annual entitlement
        # --------------------------------------------------------------

        if category == "ANNUAL" or "annual" in leave_name:

            value = getattr(
                staff_grade,
                "annual_leave_days",
                None,
            )

            if value is not None:
                return _decimal(value)

        # --------------------------------------------------------------
        # Legacy sick entitlement
        # --------------------------------------------------------------

        if category == "SICK" or "sick" in leave_name:

            value = getattr(
                staff_grade,
                "sick_leave_days",
                None,
            )

            if value is not None:
                return _decimal(value)

    # ------------------------------------------------------------------
    # LeaveType default
    # ------------------------------------------------------------------

    default_days = getattr(
        leave_type,
        "default_days",
        None,
    )

    if default_days is not None:
        return _decimal(default_days)

    return Decimal("0.0")


# ============================================================================
# STAFF-BASED ENTITLEMENT
# ============================================================================

def get_staff_leave_entitlement(staff, leave_type):
    """
    Return the effective leave entitlement for a staff member.

    This is the preferred helper for new code.

    Priority:

        1. StaffGradeLeavePolicy
        2. Legacy StaffGrade fields
        3. LeaveType.default_days
    """

    if not staff or not leave_type:
        return Decimal("0.0")

    # ------------------------------------------------------------------
    # 1. StaffGradeLeavePolicy
    # ------------------------------------------------------------------

    policy = get_staff_grade_leave_policy(
        staff,
        leave_type,
    )

    if policy:
        return _decimal(
            getattr(
                policy,
                "entitlement_days",
                0,
            )
        )

    # ------------------------------------------------------------------
    # 2 + 3. Existing fallback system
    # ------------------------------------------------------------------

    return get_default_leave_days(
        getattr(
            staff,
            "staff_grade",
            None,
        ),
        leave_type,
    )


# ============================================================================
# POLICY DETAILS
# ============================================================================

def get_staff_leave_policy_details(staff, leave_type):
    """
    Return a structured representation of the effective leave policy.

    Useful for:
        - HR dashboards
        - Staff profile pages
        - Leave forms
        - APIs
        - AI School Copilot / AI HR Assistant

    Example:
        {
            "source": "STAFF_GRADE_POLICY",
            "entitlement_days": Decimal("21.0"),
            "is_paid": True,
            "allow_carryover": False,
            "max_carryover_days": Decimal("0.0"),
        }
    """

    if not staff or not leave_type:
        return {
            "source": "NONE",
            "entitlement_days": Decimal("0.0"),
            "is_paid": True,
            "allow_carryover": False,
            "max_carryover_days": Decimal("0.0"),
        }

    policy = get_staff_grade_leave_policy(
        staff,
        leave_type,
    )

    # ------------------------------------------------------------------
    # Grade-specific policy
    # ------------------------------------------------------------------

    if policy:

        return {
            "source": "STAFF_GRADE_POLICY",

            "entitlement_days": _decimal(
                policy.entitlement_days
            ),

            "is_paid": bool(
                policy.is_paid
            ),

            "allow_carryover": bool(
                policy.allow_carryover
            ),

            "max_carryover_days": _decimal(
                policy.max_carryover_days
            ),

            "staff_grade": getattr(
                policy.staff_grade,
                "name",
                "",
            ),

            "leave_type": getattr(
                policy.leave_type,
                "name",
                "",
            ),

            "policy_id": str(
                policy.pk
            ),
        }

    # ------------------------------------------------------------------
    # Legacy StaffGrade
    # ------------------------------------------------------------------

    entitlement = get_default_leave_days(
        getattr(
            staff,
            "staff_grade",
            None,
        ),
        leave_type,
    )

    grade = getattr(
        staff,
        "staff_grade",
        None,
    )

    category = (
        getattr(
            leave_type,
            "category",
            "",
        )
        or ""
    ).upper()

    if grade and category in {"ANNUAL", "SICK"}:

        return {
            "source": "LEGACY_STAFF_GRADE",

            "entitlement_days": entitlement,

            "is_paid": True,

            "allow_carryover": False,

            "max_carryover_days": Decimal("0.0"),

            "staff_grade": getattr(
                grade,
                "name",
                "",
            ),

            "leave_type": getattr(
                leave_type,
                "name",
                "",
            ),

            "policy_id": None,
        }

    # ------------------------------------------------------------------
    # LeaveType default
    # ------------------------------------------------------------------

    return {
        "source": "LEAVE_TYPE_DEFAULT",

        "entitlement_days": entitlement,

        "is_paid": True,

        "allow_carryover": False,

        "max_carryover_days": Decimal("0.0"),

        "staff_grade": getattr(
            grade,
            "name",
            "",
        ) if grade else "",

        "leave_type": getattr(
            leave_type,
            "name",
            "",
        ),

        "policy_id": None,
    }