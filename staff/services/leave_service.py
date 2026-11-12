# staff/services/leave_service.py

"""
Centralized Staff Leave Service
================================

Single source of truth for:

    • Leave entitlement
    • Leave balances
    • Leave reservations
    • Leave approvals
    • Leave reversals
    • Leave balance initialization
    • Leave calendar events
    • Attendance synchronization
    • Attendance unsynchronization

Design goals
------------

1. StaffGradeLeavePolicy is the preferred entitlement source.

2. Existing StaffLeaveBalance records are NEVER overwritten.

3. Leave balance operations are transaction-safe.

4. Balance rows are locked during mutations.

5. Approval/rejection/cancellation cannot accidentally create
   duplicate balance movements.

6. Attendance synchronization is request-specific and idempotent.

7. Existing independent TeacherAbsence records are preserved.

8. Calendar functions are read-only.

9. Existing imports and older application code remain compatible.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from staff.models import (
    StaffProfile,
    LeaveType,
    StaffLeaveBalance,
    LeaveLedger,
    LeaveRequest,
    Teacher,
    TeacherAbsence,
)

from staff.services.leave_policy import (
    get_staff_leave_entitlement,
)


# ============================================================================
# CONSTANTS
# ============================================================================

ZERO = Decimal("0.0")


# ============================================================================
# DECIMAL HELPERS
# ============================================================================

def _decimal(value):
    """
    Safely convert a value to Decimal.

    Prevents accidental float arithmetic in leave calculations.
    """

    if value is None:
        return ZERO

    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value))

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return ZERO


def _non_negative(value):
    """
    Never allow a leave balance component to become negative.
    """

    return max(
        ZERO,
        _decimal(value),
    )


# ============================================================================
# VALIDATION
# ============================================================================

def _validate_staff_and_leave_type(
    staff,
    leave_type,
):
    """
    Validate the staff/leave type relationship.

    This prevents accidental cross-school balance manipulation.
    """

    if not staff:
        raise ValueError(
            "A staff member is required."
        )

    if not leave_type:
        raise ValueError(
            "A leave type is required."
        )

    if not getattr(staff, "school_id", None):
        raise ValueError(
            "The staff member must belong to a school."
        )

    if not getattr(leave_type, "school_id", None):
        raise ValueError(
            "The leave type must belong to a school."
        )

    if staff.school_id != leave_type.school_id:
        raise ValueError(
            "The staff member and leave type must belong to the same school."
        )


def _validate_period(
    period_start,
    period_end,
):
    """
    Validate a leave balance period.
    """

    if not period_start or not period_end:
        raise ValueError(
            "A valid leave balance period is required."
        )

    if period_start > period_end:
        raise ValueError(
            "Leave period start cannot be after period end."
        )


# ============================================================================
# LEAVE ENTITLEMENT
# ============================================================================

def get_leave_entitlement(
    staff,
    leave_type,
):
    """
    Return the effective leave entitlement for a staff member.

    Entitlement priority is centralized in leave_policy.py.

    Expected priority:

        StaffGradeLeavePolicy
                ↓
        LeaveType.default_days
                ↓
        legacy StaffGrade values
                ↓
        zero
    """

    if not staff or not leave_type:
        return ZERO

    _validate_staff_and_leave_type(
        staff,
        leave_type,
    )

    return _non_negative(
        get_staff_leave_entitlement(
            staff,
            leave_type,
        )
    )


# ============================================================================
# CURRENT LEAVE PERIOD
# ============================================================================

def get_current_leave_period(
    year=None,
):
    """
    Return the standard calendar-year leave period.

    Current implementation:

        January 1 → December 31

    This can later be upgraded to school-specific HR periods
    without changing the rest of the leave lifecycle.
    """

    try:
        year = int(
            year or date.today().year
        )
    except (
        TypeError,
        ValueError,
    ):
        year = date.today().year

    return (
        date(year, 1, 1),
        date(year, 12, 31),
    )


# ============================================================================
# GET / CREATE LEAVE BALANCE
# ============================================================================

def get_leave_balance(
    staff,
    leave_type,
    period_start,
    period_end,
):
    """
    Get or create a StaffLeaveBalance.

    IMPORTANT:

    Existing balances are NEVER recalculated from the current
    leave policy.

    This protects historical leave records if an administrator
    changes a StaffGradeLeavePolicy later.
    """

    if not staff or not leave_type:
        return None

    _validate_staff_and_leave_type(
        staff,
        leave_type,
    )

    _validate_period(
        period_start,
        period_end,
    )

    entitlement = get_leave_entitlement(
        staff,
        leave_type,
    )

    with transaction.atomic():

        balance, created = (
            StaffLeaveBalance.objects
            .select_for_update()
            .get_or_create(
                school=staff.school,
                staff=staff,
                leave_type=leave_type,
                period_start=period_start,
                period_end=period_end,
                defaults={
                    "total_entitled": entitlement,
                    "used": ZERO,
                    "pending": ZERO,
                    "remaining": entitlement,
                    "carried_over": ZERO,
                },
            )
        )

        # --------------------------------------------------------------
        # Only initialize NEW balances.
        #
        # NEVER overwrite an existing balance.
        # --------------------------------------------------------------

        if created:

            balance.total_entitled = _non_negative(
                balance.total_entitled
            )

            balance.used = _non_negative(
                balance.used
            )

            balance.pending = _non_negative(
                balance.pending
            )

            balance.carried_over = _non_negative(
                balance.carried_over
            )

            balance.calculate_remaining()

            balance.save(
                update_fields=[
                    "total_entitled",
                    "used",
                    "pending",
                    "carried_over",
                    "remaining",
                    "updated_at",
                ]
            )

    return balance


# ============================================================================
# LOCK BALANCE
# ============================================================================

def _locked_balance(
    staff,
    leave_type,
    period_start,
    period_end,
):
    """
    Return a row-locked StaffLeaveBalance.

    All balance mutations should go through public service methods.
    """

    balance = get_leave_balance(
        staff=staff,
        leave_type=leave_type,
        period_start=period_start,
        period_end=period_end,
    )

    if balance is None:
        return None

    return (
        StaffLeaveBalance.objects
        .select_for_update()
        .get(
            pk=balance.pk
        )
    )


# ============================================================================
# RESERVE LEAVE
# ============================================================================

def reserve_leave_days(
    staff,
    leave_type,
    days,
    period_start,
    period_end,
):
    """
    Reserve leave days when a LeaveRequest becomes PENDING.

    Example:

        Entitlement = 21
        Pending     = 0
        Request     = 5

        Result:

        Pending     = 5
        Remaining   = 16
    """

    days = _non_negative(days)

    if days <= ZERO:
        return get_leave_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

    with transaction.atomic():

        balance = _locked_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

        if balance is None:
            raise ValueError(
                "Unable to create the staff leave balance."
            )

        balance.calculate_remaining()

        if balance.remaining < days:
            raise ValueError(
                "Insufficient leave balance. "
                f"Available: {balance.remaining} days."
            )

        balance.pending = (
            _non_negative(balance.pending)
            + days
        )

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "pending",
                "remaining",
                "updated_at",
            ]
        )

        return balance


# ============================================================================
# RELEASE RESERVED LEAVE
# ============================================================================

def release_reserved_leave(
    staff,
    leave_type,
    days,
    period_start,
    period_end,
):
    """
    Release pending leave.

    Used when a pending request is:

        • rejected
        • cancelled before approval

    This does NOT modify used leave.
    """

    days = _non_negative(days)

    if days <= ZERO:
        return get_leave_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

    with transaction.atomic():

        balance = _locked_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

        if balance is None:
            raise ValueError(
                "Unable to locate the staff leave balance."
            )

        if balance.pending < days:
            raise ValueError(
                "Cannot release leave because the reserved "
                f"pending balance is only {balance.pending} days."
            )

        balance.pending = _non_negative(
            balance.pending - days
        )

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "pending",
                "remaining",
                "updated_at",
            ]
        )

        return balance


# ============================================================================
# APPROVE RESERVED LEAVE
# ============================================================================

def approve_reserved_leave(
    staff,
    leave_type,
    days,
    period_start,
    period_end,
):
    """
    Convert pending leave into used leave.

    Before:

        pending = 5
        used    = 0

    After:

        pending = 0
        used    = 5
    """

    days = _non_negative(days)

    if days <= ZERO:
        return get_leave_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

    with transaction.atomic():

        balance = _locked_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

        if balance is None:
            raise ValueError(
                "Unable to locate the staff leave balance."
            )

        if balance.pending < days:
            raise ValueError(
                "Cannot approve leave because the reserved "
                f"pending balance is only {balance.pending} days."
            )

        balance.pending = _non_negative(
            balance.pending - days
        )

        balance.used = (
            _non_negative(balance.used)
            + days
        )

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "pending",
                "used",
                "remaining",
                "updated_at",
            ]
        )

        return balance


# ============================================================================
# REVERSE APPROVED LEAVE
# ============================================================================

def reverse_approved_leave(
    staff,
    leave_type,
    days,
    period_start,
    period_end,
):
    """
    Reverse previously-used leave.

    Used when an approved or taken leave request is cancelled.

    Example:

        used = 5

        cancel 5 days

        used = 0
        remaining increases by 5
    """

    days = _non_negative(days)

    if days <= ZERO:
        return get_leave_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

    with transaction.atomic():

        balance = _locked_balance(
            staff,
            leave_type,
            period_start,
            period_end,
        )

        if balance is None:
            raise ValueError(
                "Unable to locate the staff leave balance."
            )

        if balance.used < days:
            raise ValueError(
                "Cannot reverse leave because the used "
                f"balance is only {balance.used} days."
            )

        balance.used = _non_negative(
            balance.used - days
        )

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "used",
                "remaining",
                "updated_at",
            ]
        )

        return balance


# ============================================================================
# RELEASE APPROVED LEAVE
# ============================================================================

def release_approved_leave(
    staff,
    leave_type,
    days,
    period_start,
    period_end,
):
    """
    Backward-compatible alias for reverse_approved_leave().
    """

    return reverse_approved_leave(
        staff=staff,
        leave_type=leave_type,
        days=days,
        period_start=period_start,
        period_end=period_end,
    )


# ============================================================================
# CANCEL LEAVE BALANCE
# ============================================================================

def cancel_leave_balance(
    staff,
    leave_type,
    days,
    period_start,
    period_end,
    was_approved=False,
):
    """
    Correct the leave balance when a LeaveRequest is cancelled.

    Pending request:

        pending → reduced

    Approved/taken request:

        used → reduced

    Attendance synchronization is handled separately.
    """

    if was_approved:
        return reverse_approved_leave(
            staff=staff,
            leave_type=leave_type,
            days=days,
            period_start=period_start,
            period_end=period_end,
        )

    return release_reserved_leave(
        staff=staff,
        leave_type=leave_type,
        days=days,
        period_start=period_start,
        period_end=period_end,
    )


# ============================================================================
# INITIALIZE STAFF BALANCES
# ============================================================================

def initialize_staff_leave_balances(
    staff,
    year=None,
):
    """
    Create missing leave balances for all active leave types.

    Existing balances remain untouched.
    """

    if not staff:
        return []

    period_start, period_end = (
        get_current_leave_period(year)
    )

    leave_types = (
        LeaveType.objects
        .filter(
            school=staff.school,
            is_active=True,
        )
        .order_by(
            "category",
            "name",
        )
    )

    balances = []

    for leave_type in leave_types:

        balance = get_leave_balance(
            staff=staff,
            leave_type=leave_type,
            period_start=period_start,
            period_end=period_end,
        )

        if balance:
            balances.append(balance)

    return balances


# ============================================================================
# CALENDAR STATUS HELPERS
# ============================================================================

def _get_leave_status_color(status):
    """
    Return a frontend-friendly leave status color.
    """

    return {
        "PENDING": "warning",
        "APPROVED": "success",
        "TAKEN": "success",
        "REJECTED": "danger",
        "CANCELLED": "secondary",
    }.get(
        str(status or "").upper(),
        "primary",
    )


def _get_leave_status_label(status):
    """
    Return a human-readable leave status.
    """

    normalized = str(
        status or ""
    ).upper()

    return {
        "PENDING": "Pending",
        "APPROVED": "Approved",
        "TAKEN": "Taken",
        "REJECTED": "Rejected",
        "CANCELLED": "Cancelled",
    }.get(
        normalized,
        normalized.replace(
            "_",
            " ",
        ).title() or "Unknown",
    )


# ============================================================
# LEAVE CALENDAR HELPERS
# ============================================================

from django.db.models import Q


def get_leave_calendar_events(
    school,
    start_date=None,
    end_date=None,
    staff=None,
):
    """
    Return leave requests suitable for the staff leave calendar.

    Parameters
    ----------
    school:
        School instance. Required.

    start_date:
        Calendar range start date.

    end_date:
        Calendar range end date.

    staff:
        Optional StaffProfile instance.

        If supplied, only leave requests belonging to that
        staff member are returned.

    Important
    ---------
    The staff argument MUST be a StaffProfile instance.

    The school argument is ALWAYS used against the
    LeaveRequest.school field.
    """

    if school is None:
        return LeaveRequest.objects.none()

    queryset = (
        LeaveRequest.objects
        .select_related(
            "school",
            "staff",
            "staff__user",
            "leave_type",
            "replacement_staff",
            "replacement_staff__user",
        )
        .filter(
            school=school
        )
    )

    # --------------------------------------------------------
    # OPTIONAL STAFF FILTER
    # --------------------------------------------------------
    #
    # Do NOT do:
    #
    #     queryset.filter(staff=school)
    #
    # or pass arbitrary objects into staff=.
    #
    # StaffProfile is the expected relation.
    # --------------------------------------------------------

    if staff is not None:

        if isinstance(staff, StaffProfile):
            queryset = queryset.filter(
                staff=staff
            )

        else:
            # Gracefully handle accidental User/StaffProfile IDs
            # without allowing an invalid object into the queryset.

            staff_id = getattr(staff, "pk", None)

            if staff_id:
                queryset = queryset.filter(
                    staff_id=staff_id
                )
            else:
                return LeaveRequest.objects.none()

    # --------------------------------------------------------
    # DATE RANGE
    # --------------------------------------------------------
    #
    # A leave request overlaps the calendar range when:
    #
    # leave.start <= calendar.end
    # AND
    # leave.end >= calendar.start
    #
    # --------------------------------------------------------

    if start_date and end_date:

        queryset = queryset.filter(
            start_date__lte=end_date,
            end_date__gte=start_date,
        )

    elif start_date:

        queryset = queryset.filter(
            end_date__gte=start_date
        )

    elif end_date:

        queryset = queryset.filter(
            start_date__lte=end_date
        )

    # --------------------------------------------------------
    # CALENDAR RELEVANT STATUSES
    # --------------------------------------------------------

    queryset = queryset.filter(
        status__in=[
            "PENDING",
            "APPROVED",
            "TAKEN",
        ]
    )

    return queryset.order_by(
        "start_date",
        "staff__user__last_name",
        "staff__user__first_name",
    )


# ============================================================
# STAFF-SPECIFIC CALENDAR COMPATIBILITY WRAPPER
# ============================================================

def get_leave_calendar_events_for_staff(
    staff,
    start_date=None,
    end_date=None,
):
    """
    Return calendar events for one StaffProfile.

    Compatibility wrapper used by staff-specific calendar
    views and older code.
    """

    if not isinstance(staff, StaffProfile):
        return LeaveRequest.objects.none()

    return get_leave_calendar_events(
        school=staff.school,
        start_date=start_date,
        end_date=end_date,
        staff=staff,
    )


# ============================================================
# SCHOOL-WIDE CALENDAR COMPATIBILITY WRAPPER
# ============================================================

def get_school_leave_calendar_events(
    school,
    start_date=None,
    end_date=None,
):
    """
    Return leave requests for the entire school.
    """

    return get_leave_calendar_events(
        school=school,
        start_date=start_date,
        end_date=end_date,
    )


# ============================================================================
# ATTENDANCE HELPERS
# ============================================================================

def _get_teacher_for_staff(staff):
    """
    Resolve the Teacher record belonging to a StaffProfile.
    """

    if not staff:
        return None

    try:

        from staff.models import Teacher

        return (
            Teacher.objects
            .filter(
                school=staff.school,
                user=staff.user,
                is_active=True,
            )
            .first()
        )

    except Exception:
        return None


def _get_leave_absence_reason(
    leave_request,
):
    """
    Map a leave category to TeacherAbsence reason choices.
    """

    category = (
        getattr(
            getattr(
                leave_request,
                "leave_type",
                None,
            ),
            "category",
            "",
        )
        or ""
    ).upper()

    return {
        "SICK": "SICK",
        "STUDY": "PROFESSIONAL_DEVELOPMENT",
        "PROFESSIONAL_DEVELOPMENT": (
            "PROFESSIONAL_DEVELOPMENT"
        ),
        "CASUAL": "PERSONAL",
        "COMPASSIONATE": "PERSONAL",
        "MATERNITY": "PERSONAL",
        "PATERNITY": "PERSONAL",
        "UNPAID": "OTHER",
        "ANNUAL": "OTHER",
        "OTHER": "OTHER",
    }.get(
        category,
        "OTHER",
    )


def _iter_working_days(
    start_date,
    end_date,
):
    """
    Yield Monday-Friday dates only.
    """

    if (
        not start_date
        or not end_date
        or start_date > end_date
    ):
        return

    current = start_date

    while current <= end_date:

        if current.weekday() < 5:
            yield current

        current += timedelta(
            days=1
        )


def _attendance_marker(
    leave_request,
):
    """
    Unique ownership marker.

    This is critical for safe unsynchronization.
    """

    return (
        f"[LEAVE_REQUEST:"
        f"{leave_request.pk}]"
    )


def _attendance_note(
    leave_request,
):
    """
    Human-readable TeacherAbsence note.
    """

    leave_name = getattr(
        getattr(
            leave_request,
            "leave_type",
            None,
        ),
        "name",
        "Leave",
    )

    reason = (
        getattr(
            leave_request,
            "reason",
            "",
        )
        or ""
    ).strip()

    note = (
        f"{_attendance_marker(leave_request)} "
        f"Leave Request: {leave_name}"
    )

    if reason:
        note += (
            f" — {reason[:200]}"
        )

    return note


# ============================================================================
# ATTENDANCE SYNC
# ============================================================================

def sync_attendance(
    leave_request,
):
    """
    Idempotently synchronize approved/taken leave
    to TeacherAbsence.

    Rules:

        • Pending leave does not create attendance.
        • Rejected leave does not create attendance.
        • Cancelled leave does not create attendance.
        • Repeated calls do not duplicate attendance.
        • Existing independent absence records are preserved.
    """

    if not leave_request:
        return False

    status = str(
        getattr(
            leave_request,
            "status",
            "",
        )
        or ""
    ).upper()

    if status not in {
        "APPROVED",
        "TAKEN",
    }:
        return False

    if getattr(
        leave_request,
        "attendance_synced",
        False,
    ):
        return True

    teacher = _get_teacher_for_staff(
        leave_request.staff
    )

    if not teacher:
        return False

    from staff.models import TeacherAbsence

    marker = _attendance_marker(
        leave_request
    )

    note = _attendance_note(
        leave_request
    )

    reason = _get_leave_absence_reason(
        leave_request
    )

    reported_by = (
        getattr(
            leave_request,
            "approved_by",
            None,
        )
        or getattr(
            leave_request.staff,
            "user",
            None,
        )
    )

    with transaction.atomic():

        for absence_date in _iter_working_days(
            leave_request.start_date,
            leave_request.end_date,
        ):

            absence, created = (
                TeacherAbsence.objects
                .select_for_update()
                .get_or_create(
                    school=leave_request.school,
                    teacher=teacher,
                    date=absence_date,
                    defaults={
                        "reason": reason,
                        "notes": note,
                        "reported_by": reported_by,
                    },
                )
            )

            if not created:

                existing_notes = (
                    absence.notes
                    or ""
                )

                if marker not in existing_notes:

                    absence.notes = (
                        f"{existing_notes}\n{note}"
                        if existing_notes
                        else note
                    )

                    absence.save(
                        update_fields=[
                            "notes",
                        ]
                    )

        leave_request.attendance_synced = True

        leave_request.attendance_synced_at = (
            timezone.now()
        )

        leave_request.save(
            update_fields=[
                "attendance_synced",
                "attendance_synced_at",
                "updated_at",
            ]
        )

    return True


# ============================================================================
# ATTENDANCE UNSYNC
# ============================================================================

def unsync_attendance(
    leave_request,
):
    """
    Idempotently remove only attendance owned by
    this leave request.

    IMPORTANT:

    This function NEVER deletes an absence merely because
    the teacher/date matches.

    It requires the unique:

        [LEAVE_REQUEST:<id>]

    marker.
    """

    if not leave_request:
        return False

    if not getattr(
        leave_request,
        "attendance_synced",
        False,
    ):
        return True

    teacher = _get_teacher_for_staff(
        leave_request.staff
    )

    if not teacher:

        leave_request.attendance_synced = False
        leave_request.attendance_synced_at = None

        leave_request.save(
            update_fields=[
                "attendance_synced",
                "attendance_synced_at",
                "updated_at",
            ]
        )

        return True

    from staff.models import TeacherAbsence

    marker = _attendance_marker(
        leave_request
    )

    with transaction.atomic():

        for absence_date in _iter_working_days(
            leave_request.start_date,
            leave_request.end_date,
        ):

            absence = (
                TeacherAbsence.objects
                .select_for_update()
                .filter(
                    school=leave_request.school,
                    teacher=teacher,
                    date=absence_date,
                )
                .first()
            )

            if not absence:
                continue

            notes = (
                absence.notes
                or ""
            )

            if marker not in notes:
                continue

            lines = [
                line
                for line in notes.splitlines()
                if marker not in line
            ]

            cleaned = "\n".join(
                line
                for line in lines
                if line.strip()
            ).strip()

            if cleaned:

                absence.notes = cleaned

                absence.save(
                    update_fields=[
                        "notes",
                    ]
                )

            else:
                # The absence was created only for this leave request.
                absence.delete()

        leave_request.attendance_synced = False
        leave_request.attendance_synced_at = None

        leave_request.save(
            update_fields=[
                "attendance_synced",
                "attendance_synced_at",
                "updated_at",
            ]
        )

    return True