# staff/services/leave_lifecycle.py

from decimal import Decimal
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from staff.models import (
    LeaveRequest,
    StaffLeaveBalance,
    LeaveLedger,
)


class LeaveLifecycleService:
    """
    Central service for the complete staff leave lifecycle.

    Lifecycle:

        DRAFT
            |
            v
        PENDING
          /   \
         /     \
        v       v
    APPROVED   REJECTED
        |
        v
      TAKEN
        |
        v
    CANCELLED

    Cancellation is also supported from:

        PENDING   -> CANCELLED
        APPROVED  -> CANCELLED
        TAKEN     -> CANCELLED

    ---------------------------------------------------------------
    BALANCE RULES
    ---------------------------------------------------------------

    SUBMIT:

        available -> pending

    APPROVE:

        pending -> used

    REJECT:

        pending -> available

    CANCEL PENDING:

        pending -> available

    CANCEL APPROVED / TAKEN:

        used -> available

    MARK TAKEN:

        No balance change.

    ---------------------------------------------------------------
    IMPORTANT
    ---------------------------------------------------------------

    All balance-changing operations:

        * run inside transaction.atomic()
        * lock the LeaveRequest
        * lock the StaffLeaveBalance
        * create a LeaveLedger audit record

    This prevents double charging or double releasing leave
    when concurrent requests attempt to modify the same record.
    """

    ZERO = Decimal("0.0")

    # ==========================================================
    # INTERNAL HELPERS
    # ==========================================================

    @staticmethod
    def _decimal(value):
        """
        Convert a value safely to Decimal.
        """
        if value is None:
            return LeaveLifecycleService.ZERO

        return Decimal(str(value))

    # ----------------------------------------------------------
    # BALANCE PERIOD
    # ----------------------------------------------------------

    @staticmethod
    def _get_period(leave_request):
        """
        Return the leave balance period.

        The current system uses calendar-year leave balances.
        """

        if not leave_request.start_date:
            raise ValidationError(
                "Leave request must have a start date."
            )

        period_start = leave_request.start_date.replace(
            month=1,
            day=1,
        )

        period_end = leave_request.start_date.replace(
            month=12,
            day=31,
        )

        return period_start, period_end

    # ----------------------------------------------------------
    # GET / CREATE BALANCE
    # ----------------------------------------------------------

    @staticmethod
    def _get_balance(leave_request, lock=True):
        """
        Return the StaffLeaveBalance for this request.

        Creates the balance when it does not exist.

        The balance is scoped by:

            school
            staff
            leave_type
            period_start
            period_end

        Creation is protected against concurrent requests.
        """

        period_start, period_end = (
            LeaveLifecycleService._get_period(leave_request)
        )

        queryset = StaffLeaveBalance.objects

        if lock:
            queryset = queryset.select_for_update()

        balance = queryset.filter(
            school_id=leave_request.school_id,
            staff_id=leave_request.staff_id,
            leave_type_id=leave_request.leave_type_id,
            period_start=period_start,
            period_end=period_end,
        ).first()

        if balance:
            return balance

        # ------------------------------------------------------
        # Calculate entitlement
        # ------------------------------------------------------

        entitlement = LeaveLifecycleService._decimal(
            leave_request.staff.get_leave_entitlement(
                leave_request.leave_type
            )
        )

        # ------------------------------------------------------
        # Safely create missing balance.
        #
        # StaffLeaveBalance has a unique constraint:
        #
        # staff + leave_type + period_start + period_end
        #
        # Another concurrent request may create it first.
        # ------------------------------------------------------

        try:
            with transaction.atomic():
                balance = StaffLeaveBalance.objects.create(
                    school=leave_request.school,
                    staff=leave_request.staff,
                    leave_type=leave_request.leave_type,
                    period_start=period_start,
                    period_end=period_end,
                    total_entitled=entitlement,
                    carried_over=LeaveLifecycleService.ZERO,
                    used=LeaveLifecycleService.ZERO,
                    pending=LeaveLifecycleService.ZERO,
                    remaining=entitlement,
                )
        except IntegrityError:
            balance = StaffLeaveBalance.objects.filter(
                school_id=leave_request.school_id,
                staff_id=leave_request.staff_id,
                leave_type_id=leave_request.leave_type_id,
                period_start=period_start,
                period_end=period_end,
            ).first()

            if not balance:
                raise

        if lock:
            balance = (
                StaffLeaveBalance.objects
                .select_for_update()
                .get(pk=balance.pk)
            )

        return balance

    # ----------------------------------------------------------
    # BALANCE SNAPSHOT
    # ----------------------------------------------------------

    @staticmethod
    def _balance_snapshot(balance):
        """
        Return a JSON-safe representation of the balance.

        Decimal values are converted to strings so they can safely
        be stored inside LeaveLedger JSONField fields.
        """

        return {
            "total_entitled": str(
                balance.total_entitled
                or LeaveLifecycleService.ZERO
            ),
            "carried_over": str(
                balance.carried_over
                or LeaveLifecycleService.ZERO
            ),
            "used": str(
                balance.used
                or LeaveLifecycleService.ZERO
            ),
            "pending": str(
                balance.pending
                or LeaveLifecycleService.ZERO
            ),
            "remaining": str(
                balance.remaining
                or LeaveLifecycleService.ZERO
            ),
        }

    # ----------------------------------------------------------
    # LEDGER
    # ----------------------------------------------------------

    @staticmethod
    def _create_ledger(
        leave_request,
        balance,
        action,
        days,
        performed_by=None,
        notes=None,
        balance_before=None,
    ):
        """
        Create an immutable leave audit entry.
        """

        if balance_before is None:
            balance_before = (
                LeaveLifecycleService._balance_snapshot(
                    balance
                )
            )

        balance.calculate_remaining()

        balance_after = (
            LeaveLifecycleService._balance_snapshot(
                balance
            )
        )

        return LeaveLedger.objects.create(
            school=leave_request.school,
            staff=leave_request.staff,
            leave_type=leave_request.leave_type,
            leave_request=leave_request,
            action=action,
            days=LeaveLifecycleService._decimal(days),
            balance_before=balance_before,
            balance_after=balance_after,
            performed_by=performed_by,
            notes=notes,
        )

    # ----------------------------------------------------------
    # REQUEST VALIDATION
    # ----------------------------------------------------------

    @staticmethod
    def _validate_request(leave_request):
        """
        Validate the school/staff/leave hierarchy and dates.
        """

        if not leave_request.school_id:
            raise ValidationError(
                "Leave request must belong to a school."
            )

        if not leave_request.staff_id:
            raise ValidationError(
                "Leave request must have a staff member."
            )

        if not leave_request.leave_type_id:
            raise ValidationError(
                "Leave request must have a leave type."
            )

        # ------------------------------------------------------
        # Staff must belong to same school
        # ------------------------------------------------------

        if (
            leave_request.staff.school_id
            != leave_request.school_id
        ):
            raise ValidationError(
                "The staff member does not belong to this school."
            )

        # ------------------------------------------------------
        # Leave type must belong to same school
        # ------------------------------------------------------

        if (
            leave_request.leave_type.school_id
            != leave_request.school_id
        ):
            raise ValidationError(
                "The leave type does not belong to this school."
            )

        # ------------------------------------------------------
        # Dates
        # ------------------------------------------------------

        if not leave_request.start_date:
            raise ValidationError(
                "Leave start date is required."
            )

        if not leave_request.end_date:
            raise ValidationError(
                "Leave end date is required."
            )

        if (
            leave_request.start_date
            > leave_request.end_date
        ):
            raise ValidationError(
                "Leave start date cannot be after the end date."
            )

        # ------------------------------------------------------
        # Requested days
        # ------------------------------------------------------

        requested = LeaveLifecycleService._decimal(
            leave_request.requested_days
        )

        if requested <= LeaveLifecycleService.ZERO:
            raise ValidationError(
                "Leave request must contain at least "
                "one working day."
            )

    # ----------------------------------------------------------
    # LOCK REQUEST
    # ----------------------------------------------------------

    @staticmethod
    def _lock_request(leave_request):
        """
        Reload and lock the LeaveRequest.

        This is important because callers may pass an object
        that was loaded before another transaction changed it.
        """

        return (
            LeaveRequest.objects
            .select_for_update()
            .select_related(
                "staff",
                "leave_type",
                "school",
            )
            .get(pk=leave_request.pk)
        )

    # ----------------------------------------------------------
    # REQUESTED DAYS
    # ----------------------------------------------------------

    @staticmethod
    def _get_requested_days(leave_request):
        """
        Return the stored requested leave days.

        Once submitted, this becomes the amount reserved/used
        throughout the lifecycle.
        """

        requested = LeaveLifecycleService._decimal(
            leave_request.requested_days
        )

        if requested <= LeaveLifecycleService.ZERO:
            raise ValidationError(
                "Leave request must contain at least "
                "one working day."
            )

        return requested

    # ==========================================================
    # SUBMIT
    # ==========================================================

    @staticmethod
    @transaction.atomic
    def submit(leave_request, user=None):
        """
        Submit a draft leave request.

        DRAFT -> PENDING

        The requested days are reserved in:

            StaffLeaveBalance.pending
        """

        leave_request = (
            LeaveLifecycleService._lock_request(
                leave_request
            )
        )

        LeaveLifecycleService._validate_request(
            leave_request
        )

        if leave_request.status != "DRAFT":
            raise ValidationError(
                "Only draft leave requests can be submitted."
            )

        # ------------------------------------------------------
        # Recalculate working days while still in DRAFT.
        #
        # This prevents manipulated requested_days values.
        # ------------------------------------------------------

        calculated_days = (
            leave_request.calculate_working_days()
        )

        if calculated_days <= LeaveLifecycleService.ZERO:
            raise ValidationError(
                "The selected leave period contains "
                "no working days."
            )

        leave_request.requested_days = calculated_days

        balance = LeaveLifecycleService._get_balance(
            leave_request,
            lock=True,
        )

        balance.calculate_remaining()

        requested = calculated_days

        # ------------------------------------------------------
        # Check available balance
        # ------------------------------------------------------

        if balance.remaining < requested:
            raise ValidationError(
                "Insufficient leave balance. "
                f"Available: {balance.remaining}, "
                f"Requested: {requested}."
            )

        before = (
            LeaveLifecycleService._balance_snapshot(
                balance
            )
        )

        # ------------------------------------------------------
        # Reserve days
        # ------------------------------------------------------

        balance.pending = (
            LeaveLifecycleService._decimal(
                balance.pending
            )
            + requested
        )

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "pending",
                "remaining",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Change request status
        # ------------------------------------------------------

        leave_request.status = "PENDING"

        leave_request.save(
            update_fields=[
                "requested_days",
                "status",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Audit
        # ------------------------------------------------------

        LeaveLifecycleService._create_ledger(
            leave_request=leave_request,
            balance=balance,
            action="RESERVE",
            days=requested,
            performed_by=user,
            notes=(
                "Leave request submitted for approval."
            ),
            balance_before=before,
        )

        return leave_request

    # ==========================================================
    # APPROVE
    # ==========================================================

    @staticmethod
    @transaction.atomic
    def approve(
        leave_request,
        user,
        note=None,
    ):
        """
        Approve a pending leave request.

        PENDING -> APPROVED

        Balance:

            pending -> used

        Attendance is synchronized after approval.
        """

        if user is None:
            raise ValidationError(
                "An approving user is required."
            )

        leave_request = (
            LeaveLifecycleService._lock_request(
                leave_request
            )
        )

        LeaveLifecycleService._validate_request(
            leave_request
        )

        if leave_request.status != "PENDING":
            raise ValidationError(
                "Only pending leave requests can be approved."
            )

        balance = LeaveLifecycleService._get_balance(
            leave_request,
            lock=True,
        )

        requested = (
            LeaveLifecycleService._get_requested_days(
                leave_request
            )
        )

        balance.pending = LeaveLifecycleService._decimal(
            balance.pending
        )

        # ------------------------------------------------------
        # The requested days MUST already be reserved.
        # ------------------------------------------------------

        if balance.pending < requested:
            raise ValidationError(
                "The requested leave days are not currently "
                "reserved."
            )

        before = (
            LeaveLifecycleService._balance_snapshot(
                balance
            )
        )

        # ------------------------------------------------------
        # pending -> used
        # ------------------------------------------------------

        balance.pending -= requested
        balance.used = (
            LeaveLifecycleService._decimal(
                balance.used
            )
            + requested
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

        # ------------------------------------------------------
        # Update request
        # ------------------------------------------------------

        leave_request.status = "APPROVED"
        leave_request.approved_by = user
        leave_request.approved_at = timezone.now()
        leave_request.approval_note = note

        leave_request.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "approval_note",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Audit
        # ------------------------------------------------------

        LeaveLifecycleService._create_ledger(
            leave_request=leave_request,
            balance=balance,
            action="APPROVE",
            days=requested,
            performed_by=user,
            notes=(
                note
                or "Leave request approved."
            ),
            balance_before=before,
        )

        # ------------------------------------------------------
        # Attendance synchronization
        # ------------------------------------------------------
        #
        # sync_attendance() is intentionally responsible for
        # TeacherAbsence records.
        #
        # If synchronization raises an exception, the entire
        # approval transaction is rolled back.
        # ------------------------------------------------------

        leave_request.sync_attendance()

        return leave_request

    # ==========================================================
    # REJECT
    # ==========================================================

    @staticmethod
    @transaction.atomic
    def reject(
        leave_request,
        user,
        reason=None,
    ):
        """
        Reject a pending leave request.

        PENDING -> REJECTED

        Balance:

            pending -> available
        """

        if user is None:
            raise ValidationError(
                "A rejecting user is required."
            )

        leave_request = (
            LeaveLifecycleService._lock_request(
                leave_request
            )
        )

        LeaveLifecycleService._validate_request(
            leave_request
        )

        if leave_request.status != "PENDING":
            raise ValidationError(
                "Only pending leave requests can be rejected."
            )

        balance = LeaveLifecycleService._get_balance(
            leave_request,
            lock=True,
        )

        requested = (
            LeaveLifecycleService._get_requested_days(
                leave_request
            )
        )

        balance.pending = LeaveLifecycleService._decimal(
            balance.pending
        )

        if balance.pending < requested:
            raise ValidationError(
                "The requested leave days are not currently "
                "reserved."
            )

        before = (
            LeaveLifecycleService._balance_snapshot(
                balance
            )
        )

        # ------------------------------------------------------
        # Release pending reservation
        # ------------------------------------------------------

        balance.pending -= requested

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "pending",
                "remaining",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Update request
        # ------------------------------------------------------

        leave_request.status = "REJECTED"
        leave_request.rejected_by = user
        leave_request.rejected_at = timezone.now()
        leave_request.rejection_reason = reason

        leave_request.save(
            update_fields=[
                "status",
                "rejected_by",
                "rejected_at",
                "rejection_reason",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Audit
        # ------------------------------------------------------

        LeaveLifecycleService._create_ledger(
            leave_request=leave_request,
            balance=balance,
            action="RELEASE",
            days=requested,
            performed_by=user,
            notes=(
                reason
                or "Leave request rejected."
            ),
            balance_before=before,
        )

        return leave_request

    # ==========================================================
    # CANCEL
    # ==========================================================

    @staticmethod
    @transaction.atomic
    def cancel(
        leave_request,
        user,
        reason=None,
    ):
        """
        Cancel a leave request.

        Supported:

            PENDING  -> CANCELLED
            APPROVED -> CANCELLED
            TAKEN    -> CANCELLED

        PENDING:

            pending -> available

        APPROVED / TAKEN:

            used -> available

        Attendance created by the leave request is removed
        safely when necessary.
        """

        if user is None:
            raise ValidationError(
                "A cancelling user is required."
            )

        leave_request = (
            LeaveLifecycleService._lock_request(
                leave_request
            )
        )

        LeaveLifecycleService._validate_request(
            leave_request
        )

        allowed_statuses = {
            "PENDING",
            "APPROVED",
            "TAKEN",
        }

        if leave_request.status not in allowed_statuses:
            raise ValidationError(
                "Only pending, approved, or taken leave "
                "requests can be cancelled."
            )

        balance = LeaveLifecycleService._get_balance(
            leave_request,
            lock=True,
        )

        requested = (
            LeaveLifecycleService._get_requested_days(
                leave_request
            )
        )

        before = (
            LeaveLifecycleService._balance_snapshot(
                balance
            )
        )

        # ======================================================
        # PENDING
        # ======================================================

        if leave_request.status == "PENDING":

            balance.pending = (
                LeaveLifecycleService._decimal(
                    balance.pending
                )
            )

            if balance.pending < requested:
                raise ValidationError(
                    "The requested leave days are not "
                    "currently reserved."
                )

            balance.pending -= requested

            action = "RELEASE"

        # ======================================================
        # APPROVED / TAKEN
        # ======================================================

        else:

            balance.used = (
                LeaveLifecycleService._decimal(
                    balance.used
                )
            )

            if balance.used < requested:
                raise ValidationError(
                    "The leave balance does not contain "
                    "enough used days to reverse this "
                    "approved leave."
                )

            balance.used -= requested

            action = "REVERSE"

        # ------------------------------------------------------
        # Recalculate balance
        # ------------------------------------------------------

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "pending",
                "used",
                "remaining",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Update request
        # ------------------------------------------------------

        leave_request.status = "CANCELLED"
        leave_request.cancelled_by = user
        leave_request.cancelled_at = timezone.now()
        leave_request.cancellation_reason = reason

        leave_request.save(
            update_fields=[
                "status",
                "cancelled_by",
                "cancelled_at",
                "cancellation_reason",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Audit
        # ------------------------------------------------------

        LeaveLifecycleService._create_ledger(
            leave_request=leave_request,
            balance=balance,
            action=action,
            days=requested,
            performed_by=user,
            notes=(
                reason
                or "Leave request cancelled."
            ),
            balance_before=before,
        )

        # ------------------------------------------------------
        # Remove attendance records owned by this request
        # ------------------------------------------------------

        if leave_request.attendance_synced:
            leave_request.unsync_attendance()

        return leave_request

    # ==========================================================
    # MARK AS TAKEN
    # ==========================================================

    @staticmethod
    @transaction.atomic
    def mark_taken(
        leave_request,
        user=None,
    ):
        """
        Mark approved leave as taken.

        APPROVED -> TAKEN

        No balance change occurs.

        The leave was already charged when it was approved.
        """

        leave_request = (
            LeaveLifecycleService._lock_request(
                leave_request
            )
        )

        if leave_request.status != "APPROVED":
            raise ValidationError(
                "Only approved leave requests can be "
                "marked as taken."
            )

        leave_request.status = "TAKEN"

        leave_request.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Ensure attendance exists.
        #
        # The operation is idempotent.
        # ------------------------------------------------------

        if not leave_request.attendance_synced:
            leave_request.sync_attendance()

        return leave_request

    # ==========================================================
    # RELEASE APPROVED / TAKEN LEAVE
    # ==========================================================

    @staticmethod
    @transaction.atomic
    def release_approved_leave(
        leave_request,
        user=None,
        reason=None,
    ):
        """
        Reverse an approved or taken leave.

        APPROVED / TAKEN -> CANCELLED

        Used days are returned to available balance.
        Attendance is removed when synchronized.
        """

        leave_request = (
            LeaveLifecycleService._lock_request(
                leave_request
            )
        )

        if leave_request.status not in {
            "APPROVED",
            "TAKEN",
        }:
            raise ValidationError(
                "Only approved or taken leave can be released."
            )

        balance = LeaveLifecycleService._get_balance(
            leave_request,
            lock=True,
        )

        requested = (
            LeaveLifecycleService._get_requested_days(
                leave_request
            )
        )

        balance.used = (
            LeaveLifecycleService._decimal(
                balance.used
            )
        )

        if balance.used < requested:
            raise ValidationError(
                "Insufficient used leave balance to reverse "
                "this approved leave."
            )

        before = (
            LeaveLifecycleService._balance_snapshot(
                balance
            )
        )

        # ------------------------------------------------------
        # Reverse used leave
        # ------------------------------------------------------

        balance.used -= requested

        balance.calculate_remaining()

        balance.save(
            update_fields=[
                "used",
                "remaining",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Cancel request
        # ------------------------------------------------------

        leave_request.status = "CANCELLED"
        leave_request.cancelled_by = user
        leave_request.cancelled_at = timezone.now()
        leave_request.cancellation_reason = (
            reason
            or "Approved leave reversed."
        )

        leave_request.save(
            update_fields=[
                "status",
                "cancelled_by",
                "cancelled_at",
                "cancellation_reason",
                "updated_at",
            ]
        )

        # ------------------------------------------------------
        # Audit
        # ------------------------------------------------------

        LeaveLifecycleService._create_ledger(
            leave_request=leave_request,
            balance=balance,
            action="REVERSE",
            days=requested,
            performed_by=user,
            notes=(
                reason
                or "Approved leave reversed."
            ),
            balance_before=before,
        )

        # ------------------------------------------------------
        # Attendance
        # ------------------------------------------------------

        if leave_request.attendance_synced:
            leave_request.unsync_attendance()

        return leave_request

    # ==========================================================
    # BACKWARD COMPATIBILITY
    # ==========================================================

    @staticmethod
    @transaction.atomic
    def reverse_approved_leave(
        leave_request,
        user=None,
        reason=None,
    ):
        """
        Backward-compatible alias.

        Existing code may already call:

            reverse_approved_leave()

        The canonical implementation is:

            release_approved_leave()
        """

        return LeaveLifecycleService.release_approved_leave(
            leave_request=leave_request,
            user=user,
            reason=reason,
        )