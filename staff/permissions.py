"""
Leave authorization helpers.

These helpers intentionally separate:
    - requesting one's own leave
    - creating a request for another staff member
    - viewing/managing requests
    - approving/rejecting requests

Do not use is_staff/is_superuser as the only leave authorization check.
"""


def _role(user):
    return str(getattr(user, "role", "") or "").upper()


def _staff_position(user):
    try:
        return str(user.staff_profile.staff_position or "").upper()
    except Exception:
        return ""


def is_school_admin(user):
    return _role(user) in {"SUPER_ADMIN", "SCHOOL_ADMIN"}


def is_leave_manager(user):
    """People allowed to administer/enter leave requests."""
    return is_school_admin(user) or _role(user) in {"SECRETARY", "HR", "HR_ADMIN"} or _staff_position(user) in {"SECRETARY", "SCHOOL_ADMIN"}


def is_hod(user):
    return _role(user) == "HOD" or _staff_position(user) == "HOD"


def can_request_own_leave(user):
    """Every active staff member with a StaffProfile may request own leave."""
    if not getattr(user, "is_authenticated", False):
        return False
    try:
        profile = user.staff_profile
        return bool(profile and profile.is_active and getattr(profile, "school_id", None))
    except Exception:
        return False


def can_create_leave_for_staff(user):
    return is_leave_manager(user)


def can_view_all_leave(user):
    return is_leave_manager(user)


def can_approve_leave(user, leave_request=None):
    if is_school_admin(user):
        return True

    # HOD approval is limited to staff in the HOD's own department.
    if not is_hod(user):
        return False

    if leave_request is None:
        return True

    try:
        approver_staff = user.staff_profile
        department = leave_request.staff.department
        return bool(
            department and (
                department.hod_id == approver_staff.id
                or leave_request.staff.department_id == approver_staff.department_id
            )
        )
    except Exception:
        return False


def can_reject_leave(user, leave_request=None):
    return can_approve_leave(user, leave_request)


def can_edit_leave(user, leave_request):
    if is_school_admin(user) or is_leave_manager(user):
        return leave_request.status in {"DRAFT", "PENDING"}
    try:
        return (
            leave_request.staff.user_id == user.id
            and leave_request.status in {"DRAFT", "PENDING"}
        )
    except Exception:
        return False


def can_cancel_leave(user, leave_request):
    if is_school_admin(user) or is_leave_manager(user):
        return leave_request.status in {"PENDING", "APPROVED", "TAKEN"}
    try:
        return (
            leave_request.staff.user_id == user.id
            and leave_request.status in {"PENDING", "APPROVED", "TAKEN"}
        )
    except Exception:
        return False
