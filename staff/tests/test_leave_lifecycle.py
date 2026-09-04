# staff/tests/test_leave_lifecycle.py

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction

from school.models import School
from staff.models import (
    StaffProfile,
    StaffGrade,
    LeaveType,
    LeaveRequest,
    StaffLeaveBalance,
    LeaveLedger,
)
from staff.services.leave_lifecycle import LeaveLifecycleService, InvalidLeaveTransition
from staff.services.leave_service import (
    get_leave_balance,
    get_current_leave_period,
    reserve_leave_days,
    approve_reserved_leave,
    release_reserved_leave,
    reverse_approved_leave,
    cancel_leave_balance,
)

User = get_user_model()


class LeaveLifecycleTests(TestCase):
    """Comprehensive tests for the leave lifecycle service."""

    def setUp(self):
        # Create a school
        self.school = School.objects.create(
            name="Test School",
            subdomain="test",
            domain="test.local",
        )

        # Create a user and staff profile
        self.user = User.objects.create_user(
            username="staff1",
            password="password123",
            first_name="Test",
            last_name="Staff",
            email="staff@test.com",
            role="TEACHER",
            school=self.school,
        )

        # Create staff grade
        self.staff_grade = StaffGrade.objects.create(
            school=self.school,
            name="Grade 1",
            code="G1",
            level=1,
            base_salary=1000,
            annual_leave_days=21,
            sick_leave_days=10,
        )

        self.staff = StaffProfile.objects.create(
            school=self.school,
            user=self.user,
            staff_id="TST-STAFF-0001",
            staff_position="TEACHER",
            staff_grade=self.staff_grade,
        )

        # Create leave types
        self.annual_leave = LeaveType.objects.create(
            school=self.school,
            name="Annual Leave",
            category="ANNUAL",
            default_days=21,
            requires_approval=True,
        )

        self.sick_leave = LeaveType.objects.create(
            school=self.school,
            name="Sick Leave",
            category="SICK",
            default_days=10,
            requires_approval=True,
        )

        # Create an admin user
        self.admin_user = User.objects.create_user(
            username="admin",
            password="admin123",
            role="SCHOOL_ADMIN",
            school=self.school,
        )

        # Get current period
        self.period_start, self.period_end = get_current_leave_period()

    def test_initial_balance_creation(self):
        """Test that leave balance is created when requested."""
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )

        self.assertIsNotNone(balance)
        self.assertEqual(balance.total_entitled, Decimal('21'))
        self.assertEqual(balance.used, Decimal('0'))
        self.assertEqual(balance.pending, Decimal('0'))
        self.assertEqual(balance.remaining, Decimal('21'))

    def test_reserve_leave_days(self):
        """Test reserving leave days for a pending request."""
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )

        # Reserve 5 days
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        balance.refresh_from_db()
        self.assertEqual(balance.pending, Decimal('5'))
        self.assertEqual(balance.remaining, Decimal('16'))

    def test_reserve_insufficient_balance(self):
        """Test that reserving more days than available raises an error."""
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )

        # Try to reserve more than available
        with self.assertRaises(ValueError) as context:
            reserve_leave_days(
                self.staff,
                self.annual_leave,
                Decimal('30'),
                self.period_start,
                self.period_end,
            )

        self.assertIn("Insufficient leave balance", str(context.exception))

    def test_approve_reserved_leave(self):
        """Test approving a pending leave request."""
        # First reserve leave
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )
        self.assertEqual(balance.pending, Decimal('5'))

        # Create a leave request
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        # Approve the leave
        with transaction.atomic():
            approved = LeaveLifecycleService.approve(leave_request, self.admin_user)

        self.assertEqual(approved.status, 'APPROVED')
        self.assertEqual(approved.approved_by, self.admin_user)
        self.assertIsNotNone(approved.approved_at)

        # Check balance
        balance.refresh_from_db()
        self.assertEqual(balance.pending, Decimal('0'))
        self.assertEqual(balance.used, Decimal('5'))
        self.assertEqual(balance.remaining, Decimal('16'))

    def test_reject_pending_leave(self):
        """Test rejecting a pending leave request."""
        # First reserve leave
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        # Create a leave request
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        # Reject the leave
        with transaction.atomic():
            rejected = LeaveLifecycleService.reject(
                leave_request,
                self.admin_user,
                reason="Not enough coverage"
            )

        self.assertEqual(rejected.status, 'REJECTED')
        self.assertEqual(rejected.rejected_by, self.admin_user)
        self.assertIsNotNone(rejected.rejected_at)
        self.assertEqual(rejected.rejection_reason, "Not enough coverage")

        # Check balance
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )
        self.assertEqual(balance.pending, Decimal('0'))
        self.assertEqual(balance.used, Decimal('0'))
        self.assertEqual(balance.remaining, Decimal('21'))

    def test_cancel_pending_leave(self):
        """Test cancelling a pending leave request."""
        # First reserve leave
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        # Create a leave request
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        # Cancel the leave
        with transaction.atomic():
            cancelled = LeaveLifecycleService.cancel(
                leave_request,
                self.admin_user,
                reason="Changed plans"
            )

        self.assertEqual(cancelled.status, 'CANCELLED')
        self.assertEqual(cancelled.cancelled_by, self.admin_user)
        self.assertIsNotNone(cancelled.cancelled_at)
        self.assertEqual(cancelled.cancellation_reason, "Changed plans")

        # Check balance
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )
        self.assertEqual(balance.pending, Decimal('0'))
        self.assertEqual(balance.used, Decimal('0'))
        self.assertEqual(balance.remaining, Decimal('21'))

    def test_cancel_approved_leave(self):
        """Test cancelling an approved leave request."""
        # First reserve and approve leave
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        with transaction.atomic():
            approved = LeaveLifecycleService.approve(leave_request, self.admin_user)

        self.assertEqual(approved.status, 'APPROVED')

        # Verify balance
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )
        self.assertEqual(balance.used, Decimal('5'))

        # Cancel the approved leave
        with transaction.atomic():
            cancelled = LeaveLifecycleService.cancel(
                leave_request,
                self.admin_user,
                reason="Staff requested cancellation"
            )

        self.assertEqual(cancelled.status, 'CANCELLED')

        # Check balance - should be restored
        balance.refresh_from_db()
        self.assertEqual(balance.used, Decimal('0'))
        self.assertEqual(balance.remaining, Decimal('21'))

    def test_cannot_approve_already_approved(self):
        """Test that an already approved leave cannot be approved again."""
        # Create and approve a leave
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        # Reserve and approve
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        with transaction.atomic():
            approved = LeaveLifecycleService.approve(leave_request, self.admin_user)

        self.assertEqual(approved.status, 'APPROVED')

        # Try to approve again - should be idempotent
        with transaction.atomic():
            result = LeaveLifecycleService.approve(leave_request, self.admin_user)

        self.assertEqual(result.status, 'APPROVED')
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )
        self.assertEqual(balance.used, Decimal('5'))  # Not double-counted

    def test_cannot_approve_rejected_leave(self):
        """Test that a rejected leave cannot be approved."""
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        # Reserve and reject
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        with transaction.atomic():
            rejected = LeaveLifecycleService.reject(
                leave_request,
                self.admin_user,
                reason="Not enough coverage"
            )

        self.assertEqual(rejected.status, 'REJECTED')

        # Try to approve - should raise error
        with self.assertRaises(InvalidLeaveTransition):
            with transaction.atomic():
                LeaveLifecycleService.approve(leave_request, self.admin_user)

    def test_ledger_logging(self):
        """Test that ledger entries are created for lifecycle actions."""
        # Create and approve a leave
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        with transaction.atomic():
            LeaveLifecycleService.approve(leave_request, self.admin_user)

        # Check ledger entries
        ledger_entries = LeaveLedger.objects.filter(leave_request=leave_request)
        self.assertGreater(ledger_entries.count(), 0)

        # Check the last entry is APPROVE
        last_entry = ledger_entries.last()
        self.assertEqual(last_entry.action, 'APPROVE')

    def test_concurrent_approval(self):
        """Test that concurrent approvals don't double-count."""
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Vacation",
            requested_days=Decimal('5'),
        )

        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        # Simulate two concurrent approvals (in reality, the lock prevents issues)
        with transaction.atomic():
            result1 = LeaveLifecycleService.approve(leave_request, self.admin_user)

        self.assertEqual(result1.status, 'APPROVED')

        # Second approval should be idempotent
        with transaction.atomic():
            result2 = LeaveLifecycleService.approve(leave_request, self.admin_user)

        self.assertEqual(result2.status, 'APPROVED')

        # Check balance - should only be deducted once
        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )
        self.assertEqual(balance.used, Decimal('5'))

    def test_full_leave_lifecycle(self):
        """Test the complete leave lifecycle from request to taken."""
        # 1. Create leave request
        leave_request = LeaveRequest.objects.create(
            school=self.school,
            staff=self.staff,
            leave_type=self.annual_leave,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=4),
            status='PENDING',
            reason="Annual vacation",
            requested_days=Decimal('5'),
        )

        # 2. Reserve balance
        reserve_leave_days(
            self.staff,
            self.annual_leave,
            Decimal('5'),
            self.period_start,
            self.period_end,
        )

        balance = get_leave_balance(
            self.staff,
            self.annual_leave,
            self.period_start,
            self.period_end,
        )
        self.assertEqual(balance.pending, Decimal('5'))

        # 3. Approve
        with transaction.atomic():
            approved = LeaveLifecycleService.approve(leave_request, self.admin_user)

        self.assertEqual(approved.status, 'APPROVED')
        balance.refresh_from_db()
        self.assertEqual(balance.pending, Decimal('0'))
        self.assertEqual(balance.used, Decimal('5'))

        # 4. Mark as Taken (manual status change)
        leave_request.status = 'TAKEN'
        leave_request.save()

        # 5. Cancel (after taken)
        with transaction.atomic():
            cancelled = LeaveLifecycleService.cancel(
                leave_request,
                self.admin_user,
                reason="Post-taken cancellation"
            )

        self.assertEqual(cancelled.status, 'CANCELLED')
        balance.refresh_from_db()
        self.assertEqual(balance.used, Decimal('0'))
        self.assertEqual(balance.remaining, Decimal('21'))

        # Check ledger entries
        entries = LeaveLedger.objects.filter(leave_request=leave_request)
        self.assertGreater(entries.count(), 0)