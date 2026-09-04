from core.pagination import paginate_queryset
# staff/views.py
from datetime import datetime, date, timedelta
from decimal import Decimal
import secrets
import string
import calendar

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Prefetch
from django.db.models import Sum, Count, Q

from accounts.models import User
from .models import *
from django.core.exceptions import ValidationError

from academics.models import SchoolClass, Subject, TeacherAssignment, ClassSubject, TeacherClassAssignment
from academics.services.class_teacher_sync import assign_class_teacher

# Import leave services
from staff.services.leave_service import *
from .services.payroll_service import *

from decimal import Decimal

from staff.services.salary_service import *
from django.urls import reverse
import time

import logging

logger = logging.getLogger(__name__)


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def _generate_username(first_name, last_name):
    base = f"{first_name[0]}{last_name}".lower().replace(' ', '')
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


def _generate_temp_password():
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(10))


def _generate_staff_id(school):
    prefix = school.subdomain[:4].upper()
    count = StaffProfile.objects.filter(school=school).count() + 1
    return f"{prefix}-STAFF-{count:04d}"


def _get_staff_leave_balance(staff, leave_type, start_date=None):
    """
    Return the StaffLeaveBalance for the leave request period.

    Uses the centralized leave service so entitlement and balance
    initialization remain consistent throughout the application.
    """

    if not staff or not leave_type:
        return None

    if start_date is None:
        start_date = timezone.localdate()

    period_start, period_end = get_current_leave_period(
        year=start_date.year
    )

    return get_leave_balance(
        staff=staff,
        leave_type=leave_type,
        period_start=period_start,
        period_end=period_end,
    )


def _get_role_for_position(position):
    role_map = {
        'SCHOOL_ADMIN': 'SCHOOL_ADMIN',
        'BURSAR': 'BURSAR',
        'REGISTRAR': 'REGISTRAR',
        'HOD': 'HOD',
        'SECRETARY': 'SECRETARY',
        'TEACHER': 'TEACHER',
        'IT_SUPPORT': 'SCHOOL_ADMIN',
        'LIBRARIAN': 'SCHOOL_ADMIN',
    }
    return role_map.get(position, 'TEACHER')

# ============================================================
# TEACHER PROFILE SYNCHRONIZATION
# ============================================================

def _ensure_teacher_profile(staff):
    """
    Ensure that a TEACHER StaffProfile has a corresponding
    academic Teacher profile.

    StaffProfile = HR employee record.
    Teacher      = academic/teaching record.

    The two records are linked through the same User account.

    This function is intentionally idempotent:
        - If Teacher exists -> return it.
        - If Teacher does not exist -> create it.
        - Calling it repeatedly is safe.
    """

    if not staff:
        return None

    if staff.staff_position != "TEACHER":
        return None

    if not staff.user_id:
        return None

    school = staff.school

    if not school:
        return None

    # --------------------------------------------------------
    # Existing Teacher profile
    # --------------------------------------------------------

    teacher = (
        Teacher.objects
        .filter(
            user_id=staff.user_id,
        )
        .first()
    )

    if teacher:

        # Keep the academic profile synchronized with HR.
        update_fields = []

        if teacher.school_id != school.id:
            teacher.school = school
            update_fields.append("school")

        desired_staff_number = staff.staff_id

        if (
            desired_staff_number
            and teacher.staff_number != desired_staff_number
        ):
            teacher.staff_number = desired_staff_number
            update_fields.append("staff_number")

        department_name = None

        if staff.department_id:
            department_name = getattr(
                staff.department,
                "name",
                None,
            )

        if teacher.department != department_name:
            teacher.department = department_name
            update_fields.append("department")

        if not teacher.is_active and staff.is_active:
            teacher.is_active = True
            update_fields.append("is_active")

        if update_fields:
            teacher.save(
                update_fields=update_fields
            )

        return teacher

    # --------------------------------------------------------
    # Create missing Teacher profile
    # --------------------------------------------------------

    staff_number = (
        staff.staff_id
        or f"TEACHER-{staff.pk}"
    )

    department_name = None

    if staff.department_id:
        department_name = getattr(
            staff.department,
            "name",
            None,
        )

    teacher = Teacher.objects.create(
        school=school,
        user=staff.user,
        staff_number=staff_number,
        department=department_name,
        is_active=staff.is_active,
    )

    return teacher


def _sync_teacher_profile_for_staff(staff):
    """
    Synchronize a staff member with the academic Teacher model.

    If the staff member is no longer a teacher, their academic
    Teacher profile is deactivated rather than deleted.

    This protects existing TeacherAssignment records.
    """

    if not staff:
        return None

    if staff.staff_position == "TEACHER":

        teacher = _ensure_teacher_profile(
            staff
        )

        if teacher:

            should_be_active = bool(
                staff.is_active
            )

            if teacher.is_active != should_be_active:

                teacher.is_active = (
                    should_be_active
                )

                teacher.save(
                    update_fields=[
                        "is_active",
                    ]
                )

        return teacher

    # --------------------------------------------------------
    # Staff changed from TEACHER to another position.
    #
    # Do NOT delete the Teacher record because existing
    # TeacherAssignment rows may depend on it.
    # --------------------------------------------------------

    teacher = (
        Teacher.objects
        .filter(
            user_id=staff.user_id,
        )
        .first()
    )

    if teacher and teacher.is_active:

        teacher.is_active = False

        teacher.save(
            update_fields=[
                "is_active",
            ]
        )

    return teacher


def _get_active_teachers_for_school(school):
    """
    Return all active academic Teacher profiles for a school.

    IMPORTANT:
    Existing schools may contain TEACHER StaffProfiles created
    before the Teacher profile synchronization was introduced.

    Therefore this function repairs those missing Teacher rows
    automatically before returning the queryset.

    This makes the teacher assignment screens self-healing.
    """

    if not school:
        return Teacher.objects.none()

    # --------------------------------------------------------
    # Repair missing Teacher profiles.
    # --------------------------------------------------------

    teacher_staff = (
        StaffProfile.objects
        .filter(
            school=school,
            staff_position="TEACHER",
            is_active=True,
        )
        .select_related(
            "user",
            "department",
        )
    )

    for staff in teacher_staff:

        _ensure_teacher_profile(
            staff
        )

    # --------------------------------------------------------
    # Return the actual academic teachers.
    # --------------------------------------------------------

    return (
        Teacher.objects
        .filter(
            school=school,
            is_active=True,
            user__is_active=True,
        )
        .select_related(
            "user",
        )
        .prefetch_related(
            "subjects",
        )
        .order_by(
            "user__last_name",
            "user__first_name",
        )
    )


def _calculate_payroll_for_staff(staff, payroll_period):
    """
    Backwards-compatible wrapper around the central
    payroll calculation engine.
    """

    from .services.payroll_service import (
        calculate_staff_payroll,
    )

    return calculate_staff_payroll(
        staff=staff,
        payroll_period=payroll_period,
    )


# ============================================================
# STAFF MANAGEMENT VIEWS
# ============================================================

@login_required
def staff_list(request):
    # Allow BURSAR, REGISTRAR, SECRETARY to view staff list (read-only)
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR', 'REGISTRAR', 'SECRETARY']:
        messages.error(request, "You don't have permission to view staff.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    staff_members = StaffProfile.objects.filter(
        school=school
    ).select_related('user', 'staff_grade').order_by('user__last_name')

    context = {
        'staff_members': paginate_queryset(staff_members, request),
        'can_edit': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
        'can_delete': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
        'active_tab': 'staff'
    }
    return render(request, 'staff/staff_list.html', context)


# ============================================================
# STAFF CREATE
# ============================================================


@login_required
def staff_create(request):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
    ]:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": "Permission denied.",
                },
                status=403,
            )
        messages.error(request, "You don't have permission to create staff.")
        return redirect('staff:staff_list')

    school = request.user.school

    if not school:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": "Your account is not assigned to a school.",
                },
                status=400,
            )
        messages.error(request, "Your account is not assigned to a school.")
        return redirect('staff:staff_list')

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    if request.method == "GET":

        grades = (
            StaffGrade.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("level", "name")
        )

        departments = (
            Department.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        return render(
            request,
            "staff/staff_form_modal.html",
            {
                "mode": "create",
                "staff_positions": (
                    StaffProfile.STAFF_POSITION_CHOICES
                ),
                "grades": grades,
                "departments": departments,
                "action_url": "staff:staff_create",
            },
        )

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    first_name = request.POST.get(
        "first_name",
        "",
    ).strip()

    last_name = request.POST.get(
        "last_name",
        "",
    ).strip()

    email = request.POST.get(
        "email",
        "",
    ).strip()

    phone_number = request.POST.get(
        "phone_number",
        "",
    ).strip()

    staff_position = request.POST.get(
        "staff_position",
        "",
    ).strip()

    staff_grade_id = request.POST.get(
        "staff_grade",
        "",
    ).strip()

    department_id = request.POST.get(
        "department",
        "",
    ).strip()

    employment_type = request.POST.get(
        "employment_type",
        "PERMANENT",
    ).strip()

    employment_date = request.POST.get(
        "employment_date",
        "",
    ).strip()

    profile_picture = request.FILES.get(
        "profile_picture"
    )

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    if not all(
        [
            first_name,
            last_name,
            email,
            staff_position,
        ]
    ):
        error_msg = "First name, last name, email, and staff position are required."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": error_msg,
                },
                status=400,
            )
        messages.error(request, error_msg)
        return redirect('staff:staff_list')

    if staff_position not in dict(
        StaffProfile.STAFF_POSITION_CHOICES
    ):
        error_msg = "Invalid staff position."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": error_msg,
                },
                status=400,
            )
        messages.error(request, error_msg)
        return redirect('staff:staff_list')

    try:

        with transaction.atomic():

            # ------------------------------------------------
            # Generate account details
            # ------------------------------------------------

            username = _generate_username(
                first_name,
                last_name,
            )

            temp_password = (
                _generate_temp_password()
            )

            staff_id = _generate_staff_id(
                school
            )

            mapped_role = (
                _get_role_for_position(
                    staff_position
                )
            )

            # ------------------------------------------------
            # Create User
            # ------------------------------------------------

            user = User.objects.create_user(
                username=username,
                password=temp_password,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone_number=phone_number,
                role=mapped_role,
                school=school,
            )

            # ------------------------------------------------
            # Grade
            # ------------------------------------------------

            staff_grade = None

            if staff_grade_id:

                staff_grade = get_object_or_404(
                    StaffGrade,
                    id=staff_grade_id,
                    school=school,
                    is_active=True,
                )

            # ------------------------------------------------
            # Department
            # ------------------------------------------------

            department = None

            if department_id:

                department = get_object_or_404(
                    Department,
                    id=department_id,
                    school=school,
                    is_active=True,
                )

            # ------------------------------------------------
            # Create StaffProfile
            # ------------------------------------------------

            staff = StaffProfile.objects.create(
                school=school,
                user=user,
                staff_id=staff_id,
                staff_position=staff_position,
                staff_grade=staff_grade,
                department=department,
                employment_type=employment_type,
                profile_picture=profile_picture,
                default_password=temp_password,
                has_changed_password=False,
                employment_date=(
                    employment_date
                    if employment_date
                    else None
                ),
            )

            # ------------------------------------------------
            # IMPORTANT:
            # If this is a teacher, create the academic
            # Teacher profile automatically.
            # ------------------------------------------------

            teacher = None

            if staff_position == "TEACHER":

                teacher = _ensure_teacher_profile(
                    staff
                )

                if not teacher:
                    raise ValueError(
                        "Unable to create the teacher academic profile."
                    )

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        success_msg = (
            f"{first_name} {last_name} "
            f"added as {staff_position}."
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": True,
                    "message": success_msg,
                    "username": username,
                    "password": temp_password,
                    "staff_id": staff_id,
                    "grade": (
                        staff_grade.name
                        if staff_grade
                        else None
                    ),
                    "teacher_profile_created": bool(
                        teacher
                    ),
                }
            )

        messages.success(request, success_msg)
        return redirect('staff:staff_list')

    except Exception as exc:

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=400,
            )

        messages.error(request, f"Error creating staff: {str(exc)}")
        return redirect('staff:staff_list')


@login_required
def staff_detail(request, staff_id):
    school = request.user.school
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER', 'BURSAR', 'REGISTRAR', 'SECRETARY']:
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard:dashboard')

    staff = get_object_or_404(
        StaffProfile.objects.select_related('user', 'staff_grade', 'department'),
        id=staff_id,
        school=school
    )
    is_default_password = not staff.has_changed_password

    # Only SUPER_ADMIN and SCHOOL_ADMIN can see login credentials
    can_view_credentials = request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN']

    # FIXED: Use LeaveRequest instead of Leave
    leaves = LeaveRequest.objects.filter(
        staff=staff
    ).select_related('leave_type').order_by('-start_date')[:5]

    pending_leaves = LeaveRequest.objects.filter(
        staff=staff,
        status='PENDING'
    ).count()

    # Get latest payroll run
    latest_payroll = PayrollRun.objects.filter(
        staff=staff
    ).select_related('payroll_period').order_by('-created_at').first()

    # Get assigned classes (if teacher)
    assigned_classes = []
    if staff.staff_position == 'TEACHER':
        try:
            teacher = Teacher.objects.get(user=staff.user)
            assigned_classes = TeacherAssignment.objects.filter(
                teacher=teacher,
                is_active=True
            ).select_related('school_class', 'subject')[:10]
        except Teacher.DoesNotExist:
            pass

    # Get leave balances
    leave_balances = StaffLeaveBalance.objects.filter(
        school=school,
        staff=staff
    ).select_related('leave_type')

    context = {
        'staff': staff,
        'is_default_password': is_default_password,
        'default_password': staff.default_password if is_default_password and staff.default_password else None,
        'username': staff.user.username,
        'leaves': leaves,
        'pending_leaves': pending_leaves,
        'latest_payroll': latest_payroll,
        'assigned_classes': assigned_classes,
        'leave_balances': leave_balances,
        'can_view_credentials': can_view_credentials,
        'active_tab': 'staff'
    }
    return render(request, 'staff/staff_detail.html', context)


# ============================================================
# STAFF EDIT
# ============================================================


@login_required
def staff_edit(request, staff_id):

    # Only SUPER_ADMIN and SCHOOL_ADMIN can edit staff
    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
    ]:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": "Permission denied.",
                },
                status=403,
            )
        messages.error(request, "You don't have permission to edit staff.")
        return redirect('staff:staff_list')

    school = request.user.school

    if not school:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": "Your account is not assigned to a school.",
                },
                status=400,
            )
        messages.error(request, "Your account is not assigned to a school.")
        return redirect('staff:staff_list')

    staff = get_object_or_404(
        StaffProfile.objects.select_related(
            "user",
            "staff_grade",
            "department",
        ),
        id=staff_id,
        school=school,
    )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    if request.method == "GET":

        grades = (
            StaffGrade.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by(
                "level",
                "name",
            )
        )

        departments = (
            Department.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        return render(
            request,
            "staff/staff_form_modal.html",
            {
                "mode": "edit",
                "staff": staff,
                "grades": grades,
                "departments": departments,
                "staff_positions": (
                    StaffProfile.STAFF_POSITION_CHOICES
                ),
                "action_url": "staff:staff_edit",
            },
        )

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    first_name = request.POST.get(
        "first_name",
        "",
    ).strip()

    last_name = request.POST.get(
        "last_name",
        "",
    ).strip()

    email = request.POST.get(
        "email",
        "",
    ).strip()

    phone_number = request.POST.get(
        "phone_number",
        "",
    ).strip()

    staff_position = request.POST.get(
        "staff_position",
        "",
    ).strip()

    staff_grade_id = request.POST.get(
        "staff_grade",
        "",
    ).strip()

    department_id = request.POST.get(
        "department",
        "",
    ).strip()

    employment_type = request.POST.get(
        "employment_type",
        "PERMANENT",
    ).strip()

    profile_picture = request.FILES.get(
        "profile_picture"
    )

    if not all(
        [
            first_name,
            last_name,
            email,
            staff_position,
        ]
    ):
        error_msg = "First name, last name, email, and staff position are required."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": error_msg,
                },
                status=400,
            )
        messages.error(request, error_msg)
        return redirect('staff:staff_list')

    if staff_position not in dict(
        StaffProfile.STAFF_POSITION_CHOICES
    ):
        error_msg = "Invalid staff position."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": error_msg,
                },
                status=400,
            )
        messages.error(request, error_msg)
        return redirect('staff:staff_list')

    try:

        with transaction.atomic():

            # ------------------------------------------------
            # User account
            # ------------------------------------------------

            staff.user.first_name = (
                first_name
            )

            staff.user.last_name = (
                last_name
            )

            staff.user.email = email

            staff.user.phone_number = (
                phone_number
            )

            staff.user.role = (
                _get_role_for_position(
                    staff_position
                )
            )

            staff.user.save(
                update_fields=[
                    "first_name",
                    "last_name",
                    "email",
                    "phone_number",
                    "role",
                ]
            )

            # ------------------------------------------------
            # Grade
            # ------------------------------------------------

            staff_grade = None

            if staff_grade_id:

                staff_grade = get_object_or_404(
                    StaffGrade,
                    id=staff_grade_id,
                    school=school,
                    is_active=True,
                )

            # ------------------------------------------------
            # Department
            # ------------------------------------------------

            department = None

            if department_id:

                department = get_object_or_404(
                    Department,
                    id=department_id,
                    school=school,
                    is_active=True,
                )

            # ------------------------------------------------
            # Staff profile
            # ------------------------------------------------

            staff.staff_position = (
                staff_position
            )

            staff.staff_grade = (
                staff_grade
            )

            staff.department = (
                department
            )

            staff.employment_type = (
                employment_type
            )

            if profile_picture:
                staff.profile_picture = (
                    profile_picture
                )

            staff.save(
                update_fields=[
                    "staff_position",
                    "staff_grade",
                    "department",
                    "employment_type",
                    "profile_picture",
                ]
            )

            # ------------------------------------------------
            # Synchronize Teacher profile
            # ------------------------------------------------

            teacher = (
                _sync_teacher_profile_for_staff(
                    staff
                )
            )

        success_msg = "Staff details updated successfully."

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": True,
                    "message": success_msg,
                    "teacher_profile_synced": bool(
                        teacher
                    ),
                }
            )

        messages.success(request, success_msg)
        return redirect('staff:staff_list')

    except Exception as exc:

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=400,
            )

        messages.error(request, f"Error updating staff: {str(exc)}")
        return redirect('staff:staff_list')



@login_required
def staff_delete(request, staff_id):
    # Only SUPER_ADMIN and SCHOOL_ADMIN can delete staff
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
        messages.error(request, "You don't have permission to delete staff.")
        return redirect('staff:staff_list')

    school = request.user.school

    if not school:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "School not found."}, status=400)
        messages.error(request, "School not found.")
        return redirect('staff:staff_list')

    staff = get_object_or_404(StaffProfile, id=staff_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/staff_delete_modal.html', {
            'staff': staff,
            'action_url': 'staff:staff_delete'
        })

    staff_name = staff.user.get_full_name()
    staff.delete()

    success_msg = f"Staff '{staff_name}' deleted successfully."

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': success_msg})

    messages.success(request, success_msg)
    return redirect('staff:staff_list')


# ============================================================
# TOGGLE STAFF ACTIVE
# ============================================================

@login_required
@require_POST
def toggle_staff_active(request, staff_id):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
    ]:
        messages.error(
            request,
            "You don't have permission to do this.",
        )

        return redirect(
            "staff:staff_detail",
            staff_id=staff_id,
        )

    school = request.user.school

    staff = get_object_or_404(
        StaffProfile,
        id=staff_id,
        school=school,
    )

    with transaction.atomic():

        staff.is_active = not staff.is_active

        staff.save(
            update_fields=[
                "is_active",
            ]
        )

        # ----------------------------------------------------
        # Keep academic Teacher profile synchronized.
        # ----------------------------------------------------

        teacher = (
            Teacher.objects
            .filter(
                user_id=staff.user_id,
            )
            .first()
        )

        if teacher:

            teacher.is_active = (
                staff.is_active
                and staff.staff_position == "TEACHER"
            )

            teacher.save(
                update_fields=[
                    "is_active",
                ]
            )

    messages.success(
        request,
        (
            f"{staff.user.get_full_name()} marked "
            f"{'active' if staff.is_active else 'inactive'}."
        ),
    )

    return redirect(
        "staff:staff_detail",
        staff_id=staff.id,
    )


# ============================================================
# DEPARTMENT VIEWS
# ============================================================

@login_required
def department_list(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to view departments.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    departments = Department.objects.filter(school=school).order_by('name')

    context = {
        'departments': paginate_queryset(departments, request),
        'active_tab': 'hr'
    }
    return render(request, 'staff/hr/department_list.html', context)


@login_required
def department_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        staff_members = StaffProfile.objects.filter(school=school, is_active=True).select_related('user')
        return render(request, 'staff/hr/department_form_modal.html', {
            'mode': 'create',
            'staff_members': staff_members,
            'action_url': 'staff:department_create'
        })

    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    hod_id = request.POST.get('hod', '').strip()

    if not name:
        return JsonResponse({'success': False, 'error': "Department name is required."})

    try:
        hod = None
        if hod_id:
            hod = get_object_or_404(StaffProfile, id=hod_id, school=school)

        department = Department.objects.create(
            school=school,
            name=name,
            description=description,
            hod=hod,
        )
        return JsonResponse({
            'success': True,
            'message': f"Department '{name}' created successfully with code '{department.code}'.",
            'code': department.code
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def department_edit(request, department_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    department = get_object_or_404(Department, id=department_id, school=school)

    if request.method == 'GET':
        staff_members = StaffProfile.objects.filter(school=school, is_active=True).select_related('user')
        return render(request, 'staff/hr/department_form_modal.html', {
            'mode': 'edit',
            'department': department,
            'staff_members': staff_members,
            'action_url': 'staff:department_edit'
        })

    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    hod_id = request.POST.get('hod', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not name:
        return JsonResponse({'success': False, 'error': "Department name is required."})

    hod = None
    if hod_id:
        hod = get_object_or_404(StaffProfile, id=hod_id, school=school)

    department.name = name
    department.description = description
    department.hod = hod
    department.is_active = is_active
    department.save()

    return JsonResponse({'success': True, 'message': f"Department '{name}' updated successfully."})


@login_required
def department_delete(request, department_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    department = get_object_or_404(Department, id=department_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/hr/department_delete_modal.html', {
            'department': department,
            'action_url': 'staff:department_delete'
        })

    if StaffProfile.objects.filter(school=school, department=department).exists():
        return JsonResponse({
            'success': False,
            'error': "This department has staff members assigned. Please reassign them first."
        })

    department.delete()
    return JsonResponse({'success': True, 'message': "Department deleted successfully."})


# ============================================================
# STAFF GRADE VIEWS
# ============================================================

@login_required
def staff_grade_list(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to view staff grades.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    grades = StaffGrade.objects.filter(school=school).order_by('level')

    context = {
        'grades': paginate_queryset(grades, request),
        'active_tab': 'hr'
    }
    return render(request, 'staff/hr/staff_grade_list.html', context)


@login_required
def staff_grade_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        return render(request, 'staff/hr/staff_grade_form_modal.html', {
            'mode': 'create',
            'action_url': 'staff:staff_grade_create'
        })

    name = request.POST.get('name', '').strip()
    grade_type = request.POST.get('grade_type', 'TEACHING').strip()
    level = request.POST.get('level', '').strip()
    base_salary = request.POST.get('base_salary', '').strip()
    annual_leave_days = request.POST.get('annual_leave_days', '21').strip()
    sick_leave_days = request.POST.get('sick_leave_days', '10').strip()
    description = request.POST.get('description', '').strip()

    if not all([name, level, base_salary]):
        return JsonResponse({'success': False, 'error': "Name, level, and base salary are required."})

    try:
        grade = StaffGrade.objects.create(
            school=school,
            name=name,
            grade_type=grade_type,
            level=level,
            base_salary=base_salary,
            annual_leave_days=annual_leave_days,
            sick_leave_days=sick_leave_days,
            description=description,
        )
        return JsonResponse({
            'success': True,
            'message': f"Grade '{name}' created successfully with code '{grade.code}'.",
            'code': grade.code
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def staff_grade_edit(request, grade_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    grade = get_object_or_404(StaffGrade, id=grade_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/hr/staff_grade_form_modal.html', {
            'mode': 'edit',
            'grade': grade,
            'action_url': 'staff:staff_grade_edit'
        })

    name = request.POST.get('name', '').strip()
    grade_type = request.POST.get('grade_type', 'TEACHING').strip()
    level = request.POST.get('level', '').strip()
    base_salary = request.POST.get('base_salary', '').strip()
    annual_leave_days = request.POST.get('annual_leave_days', '21').strip()
    sick_leave_days = request.POST.get('sick_leave_days', '10').strip()
    description = request.POST.get('description', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not all([name, level, base_salary]):
        return JsonResponse({'success': False, 'error': "Name, level, and base salary are required."})

    grade.name = name
    grade.grade_type = grade_type
    grade.level = level
    grade.base_salary = base_salary
    grade.annual_leave_days = annual_leave_days
    grade.sick_leave_days = sick_leave_days
    grade.description = description
    grade.is_active = is_active
    grade.save()

    return JsonResponse({'success': True, 'message': f"Grade '{name}' updated successfully."})


@login_required
def staff_grade_delete(request, grade_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    grade = get_object_or_404(StaffGrade, id=grade_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/hr/staff_grade_delete_modal.html', {
            'grade': grade,
            'action_url': 'staff:staff_grade_delete'
        })

    if StaffProfile.objects.filter(school=school, staff_grade=grade).exists():
        return JsonResponse({
            'success': False,
            'error': "This grade is currently assigned to staff members. Please reassign them first."
        })

    grade.delete()
    return JsonResponse({'success': True, 'message': f"Grade deleted successfully."})


# ============================================================
# TEACHER ASSIGNMENT LIST
# ============================================================

@login_required
def teacher_assignment_list(request, class_id=None,):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "HOD",
    ]:
        messages.error(
            request,
            "You don't have permission to view teacher assignments.",
        )

        return redirect("dashboard:dashboard")

    school = request.user.school

    teachers = _get_active_teachers_for_school(
        school
    )

    assignments = (
        TeacherAssignment.objects
        .filter(
            school=school,
            is_active=True,
        )
        .select_related(
            "teacher__user",
            "school_class",
            "subject",
        )
        .order_by(
            "school_class__name",
            "subject__name",
            "teacher__user__last_name",
            "teacher__user__first_name",
        )
    )

    if class_id:

        assignments = assignments.filter(
            school_class_id=class_id
        )

    classes = (
        SchoolClass.objects
        .filter(
            school=school,
            is_active=True,
        )
        .order_by("name")
    )

    context = {
        "assignments": paginate_queryset(assignments, request),
        "classes": classes,
        "teachers": teachers,
        "selected_class": class_id,
        "active_tab": "academics",
    }

    return render(
        request,
        "staff/assignments/teacher_assignment_list.html",
        context,
    )


# ============================================================
# TEACHER ASSIGNMENT CREATE
# ============================================================

@login_required
def teacher_assignment_create(request):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "HOD",
    ]:
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    school = request.user.school

    if not school:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Your account is not assigned "
                    "to a school."
                ),
            },
            status=400,
        )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    if request.method == "GET":

        teachers = (
            _get_active_teachers_for_school(
                school
            )
        )

        classes = (
            SchoolClass.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        subjects = (
            Subject.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        return render(
            request,
            "staff/assignments/teacher_assignment_form_modal.html",
            {
                "mode": "create",
                "teachers": teachers,
                "classes": classes,
                "subjects": subjects,
                "action_url": (
                    "staff:teacher_assignment_create"
                ),
            },
        )

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    teacher_id = request.POST.get(
        "teacher",
        "",
    ).strip()

    class_id = request.POST.get(
        "school_class",
        "",
    ).strip()

    subject_id = request.POST.get(
        "subject",
        "",
    ).strip()

    periods_per_week = request.POST.get(
        "periods_per_week",
        "4",
    ).strip()

    is_primary = (
        request.POST.get(
            "is_primary"
        )
        == "on"
    )

    if not all(
        [
            teacher_id,
            class_id,
            subject_id,
        ]
    ):
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Teacher, Class, and Subject "
                    "are required."
                ),
            },
            status=400,
        )

    try:

        teacher = get_object_or_404(
            Teacher,
            id=teacher_id,
            school=school,
            is_active=True,
            user__is_active=True,
        )

        school_class = get_object_or_404(
            SchoolClass,
            id=class_id,
            school=school,
            is_active=True,
        )

        subject = get_object_or_404(
            Subject,
            id=subject_id,
            school=school,
            is_active=True,
        )

        # ----------------------------------------------------
        # Duplicate protection
        # ----------------------------------------------------

        existing = (
            TeacherAssignment.objects
            .filter(
                school=school,
                teacher=teacher,
                school_class=school_class,
                subject=subject,
            )
            .first()
        )

        if existing:

            if not existing.is_active:

                existing.is_active = True
                existing.periods_per_week = (
                    periods_per_week
                )
                existing.is_primary = (
                    is_primary
                )
                existing.assigned_by = (
                    request.user
                )

                existing.save()

                teacher.subjects.add(
                    subject
                )

                return JsonResponse(
                    {
                        "success": True,
                        "message": (
                            "The existing teacher assignment "
                            "was reactivated successfully."
                        ),
                        "assignment_id": str(
                            existing.id
                        ),
                    }
                )

            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "This teacher is already assigned "
                        "to this subject in this class."
                    ),
                },
                status=400,
            )

        # ----------------------------------------------------
        # Create assignment
        # ----------------------------------------------------

        assignment = (
            TeacherAssignment.objects.create(
                school=school,
                teacher=teacher,
                school_class=school_class,
                subject=subject,
                periods_per_week=periods_per_week,
                is_primary=is_primary,
                is_active=True,
                assigned_by=request.user,
            )
        )

        # ----------------------------------------------------
        # Keep teacher qualification list synchronized.
        # ----------------------------------------------------

        teacher.subjects.add(
            subject
        )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    f"{teacher.user.get_full_name()} "
                    f"assigned to {subject.name} "
                    f"for {school_class.name} successfully."
                ),
                "assignment_id": str(
                    assignment.id
                ),
            }
        )

    except Exception as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )


# ============================================================
# TEACHER ASSIGNMENT EDIT
# ============================================================

@login_required
def teacher_assignment_edit(request, assignment_id,):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "HOD",
    ]:
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    school = request.user.school

    assignment = get_object_or_404(
        TeacherAssignment.objects.select_related(
            "teacher__user",
            "school_class",
            "subject",
        ),
        id=assignment_id,
        school=school,
    )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    if request.method == "GET":

        teachers = (
            _get_active_teachers_for_school(
                school
            )
        )

        classes = (
            SchoolClass.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        subjects = (
            Subject.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        return render(
            request,
            "staff/assignments/teacher_assignment_form_modal.html",
            {
                "mode": "edit",
                "assignment": assignment,
                "teachers": teachers,
                "classes": classes,
                "subjects": subjects,
                "action_url": (
                    "staff:teacher_assignment_edit"
                ),
            },
        )

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    teacher_id = request.POST.get(
        "teacher",
        "",
    ).strip()

    class_id = request.POST.get(
        "school_class",
        "",
    ).strip()

    subject_id = request.POST.get(
        "subject",
        "",
    ).strip()

    periods_per_week = request.POST.get(
        "periods_per_week",
        "4",
    ).strip()

    is_primary = (
        request.POST.get(
            "is_primary"
        )
        == "on"
    )

    is_active = (
        request.POST.get(
            "is_active"
        )
        == "on"
    )

    if not all(
        [
            teacher_id,
            class_id,
            subject_id,
        ]
    ):
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Teacher, Class, and Subject "
                    "are required."
                ),
            },
            status=400,
        )

    try:

        teacher = get_object_or_404(
            Teacher,
            id=teacher_id,
            school=school,
            is_active=True,
            user__is_active=True,
        )

        school_class = get_object_or_404(
            SchoolClass,
            id=class_id,
            school=school,
            is_active=True,
        )

        subject = get_object_or_404(
            Subject,
            id=subject_id,
            school=school,
            is_active=True,
        )

        duplicate = (
            TeacherAssignment.objects
            .filter(
                school=school,
                teacher=teacher,
                school_class=school_class,
                subject=subject,
            )
            .exclude(
                id=assignment.id
            )
            .exists()
        )

        if duplicate:

            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "This teacher is already assigned "
                        "to this subject in this class."
                    ),
                },
                status=400,
            )

        assignment.teacher = teacher
        assignment.school_class = school_class
        assignment.subject = subject
        assignment.periods_per_week = (
            periods_per_week
        )
        assignment.is_primary = (
            is_primary
        )
        assignment.is_active = (
            is_active
        )

        assignment.save()

        # Keep qualification list synchronized.
        if is_active:

            teacher.subjects.add(
                subject
            )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    "Teacher assignment updated successfully."
                ),
            }
        )

    except Exception as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )


@login_required
def teacher_assignment_delete(request, assignment_id):
    """
    Delete a teacher-subject-class assignment.
    """
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    assignment = get_object_or_404(TeacherAssignment, id=assignment_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/assignments/teacher_assignment_delete_modal.html', {
            'assignment': assignment,
            'action_url': 'staff:teacher_assignment_delete'
        })

    assignment.delete()
    return JsonResponse({'success': True, 'message': "Assignment deleted successfully."})


# ============================================================
# TEACHER ASSIGNMENT BULK CREATE
# ============================================================

@login_required
def teacher_assignment_bulk_create(request):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "HOD",
    ]:
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    school = request.user.school

    if not school:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Your account is not assigned "
                    "to a school."
                ),
            },
            status=400,
        )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    if request.method == "GET":

        teachers = (
            _get_active_teachers_for_school(
                school
            )
        )

        classes = (
            SchoolClass.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        subjects = (
            Subject.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by("name")
        )

        return render(
            request,
            "staff/assignments/teacher_assignment_bulk_modal.html",
            {
                "teachers": teachers,
                "classes": classes,
                "subjects": subjects,
                "action_url": (
                    "staff:teacher_assignment_bulk_create"
                ),
            },
        )

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    class_id = request.POST.get(
        "school_class",
        "",
    ).strip()

    subject_ids = request.POST.getlist(
        "subjects",
        [],
    )

    teacher_id = request.POST.get(
        "teacher",
        "",
    ).strip()

    periods_per_week = request.POST.get(
        "periods_per_week",
        "4",
    ).strip()

    if not class_id:
        return JsonResponse(
            {
                "success": False,
                "error": "Please select a class.",
            },
            status=400,
        )

    if not teacher_id:
        return JsonResponse(
            {
                "success": False,
                "error": "Please select a teacher.",
            },
            status=400,
        )

    if not subject_ids:
        return JsonResponse(
            {
                "success": False,
                "error": "Please select at least one subject.",
            },
            status=400,
        )

    try:

        teacher = get_object_or_404(
            Teacher,
            id=teacher_id,
            school=school,
            is_active=True,
            user__is_active=True,
        )

        school_class = get_object_or_404(
            SchoolClass,
            id=class_id,
            school=school,
            is_active=True,
        )

        subjects = Subject.objects.filter(
            school=school,
            is_active=True,
            id__in=subject_ids,
        )

        created = 0
        reactivated = 0
        skipped = 0

        for subject in subjects:

            assignment = (
                TeacherAssignment.objects
                .filter(
                    school=school,
                    teacher=teacher,
                    school_class=school_class,
                    subject=subject,
                )
                .first()
            )

            if assignment:

                if not assignment.is_active:

                    assignment.is_active = True
                    assignment.periods_per_week = (
                        periods_per_week
                    )
                    assignment.assigned_by = (
                        request.user
                    )

                    assignment.save()

                    reactivated += 1

                else:

                    skipped += 1

            else:

                TeacherAssignment.objects.create(
                    school=school,
                    teacher=teacher,
                    school_class=school_class,
                    subject=subject,
                    periods_per_week=periods_per_week,
                    is_active=True,
                    assigned_by=request.user,
                )

                created += 1

            # Keep qualification list synchronized.
            teacher.subjects.add(
                subject
            )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    f"Created {created} assignment(s), "
                    f"reactivated {reactivated}, "
                    f"skipped {skipped} existing assignment(s)."
                ),
                "created": created,
                "reactivated": reactivated,
                "skipped": skipped,
            }
        )

    except Exception as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )


# ============================================================
# TEACHER ASSIGNMENT CLASS VIEW
# ============================================================

@login_required
def teacher_assignment_class_view(request, class_id,):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "HOD",
        "TEACHER",
    ]:
        messages.error(
            request,
            "You don't have permission to view this.",
        )

        return redirect("dashboard:dashboard")

    school = request.user.school

    school_class = get_object_or_404(
        SchoolClass,
        id=class_id,
        school=school,
    )

    assignments = (
        TeacherAssignment.objects
        .filter(
            school=school,
            school_class=school_class,
            is_active=True,
        )
        .select_related(
            "teacher__user",
            "subject",
        )
        .order_by(
            "subject__name",
            "teacher__user__last_name",
        )
    )

    class_subjects = (
        ClassSubject.objects
        .filter(
            school=school,
            school_class=school_class,
            is_active=True,
        )
        .select_related(
            "subject",
        )
        .order_by(
            "subject__name",
        )
    )

    return render(
        request,
        "staff/assignments/teacher_assignment_class_view.html",
        {
            "school_class": school_class,
            "assignments": paginate_queryset(assignments, request),
            "class_subjects": class_subjects,
            "active_tab": "academics",
        },
    )


# ============================================================
# CLASS / ROOM TEACHER ASSIGNMENT
# ============================================================

@login_required
def class_teacher_assign(
    request,
    class_id,
):

    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "HOD",
    ]:
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    school = request.user.school

    school_class = get_object_or_404(
        SchoolClass,
        id=class_id,
        school=school,
    )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    if request.method == "GET":

        teachers = (
            _get_active_teachers_for_school(
                school
            )
        )

        return render(
            request,
            "staff/assignments/class_teacher_form_modal.html",
            {
                "school_class": school_class,
                "teachers": teachers,
                "action_url": (
                    "staff:class_teacher_assign"
                ),
            },
        )

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    teacher_id = request.POST.get(
        "teacher",
        "",
    ).strip()

    uses_single_class_teacher = (
        request.POST.get(
            "uses_single_class_teacher"
        )
        == "on"
    )

    if not teacher_id:

        return JsonResponse(
            {
                "success": False,
                "error": "Please select a teacher.",
            },
            status=400,
        )

    try:

        teacher = get_object_or_404(
            Teacher,
            id=teacher_id,
            school=school,
            is_active=True,
            user__is_active=True,
        )

        result = assign_class_teacher(
            school_class,
            teacher,
            uses_single_class_teacher=(
                uses_single_class_teacher
            ),
            assigned_by=request.user,
        )

        message = (
            f"{teacher.user.get_full_name()} "
            f"assigned as class teacher for "
            f"{school_class.name}."
        )

        if uses_single_class_teacher:

            created_count = len(
                result.get(
                    "created",
                    [],
                )
            )

            deactivated_count = result.get(
                "deactivated",
                0,
            )

            if created_count:

                message += (
                    f" Automatically assigned to "
                    f"{created_count} subject(s) already "
                    f"on this class."
                )

            if deactivated_count:

                message += (
                    f" Removed the previous class teacher's "
                    f"{deactivated_count} auto-assigned "
                    f"subject(s)."
                )

        return JsonResponse(
            {
                "success": True,
                "message": message,
            }
        )

    except Exception as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )


# ============================================================
# SALARY STRUCTURE VIEWS
# ============================================================

@login_required
def salary_structure_list(request):
    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "BURSAR",
    ]:
        messages.error(
            request,
            "You don't have permission to view salary structures.",
        )
        return redirect("dashboard:dashboard")

    school = request.user.school

    structures = (
        SalaryStructure.objects
            .filter(
            school=school,
        )
            .select_related(
            "staff",
            "staff__user",
            "staff_grade",
        )
            .order_by(
            "-effective_date",
            "staff__user__last_name",
            "staff__user__first_name",
        )
    )

    return render(
        request,
        "staff/payroll/salary_structure_list.html",
        {
            "structures": paginate_queryset(structures, request),
            "active_tab": "payroll",
        },
    )


# ============================================================
# CREATE SALARY STRUCTURE
# ============================================================

@login_required
def salary_structure_create(request):
    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "BURSAR",
    ]:
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    school = request.user.school

    if not school:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Your account is not assigned to a school."
                ),
            },
            status=400,
        )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    if request.method == "GET":
        staff_members = (
            StaffProfile.objects
                .filter(
                school=school,
                is_active=True,
            )
                .select_related(
                "user",
                "staff_grade",
            )
                .order_by(
                "user__last_name",
                "user__first_name",
            )
        )

        grades = (
            StaffGrade.objects
                .filter(
                school=school,
                is_active=True,
            )
                .order_by(
                "name",
            )
        )

        return render(
            request,
            "staff/payroll/salary_structure_form_modal.html",
            {
                "mode": "create",
                "staff_members": staff_members,
                "grades": grades,
                "action_url": (
                    "staff:salary_structure_create"
                ),
            },
        )

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    staff_id = (
        request.POST.get(
            "staff",
            "",
        )
            .strip()
    )

    basic_salary = (
        request.POST.get(
            "basic_salary",
            "",
        )
            .strip()
    )

    frequency = (
        request.POST.get(
            "frequency",
            SalaryStructure.FREQUENCY_MONTHLY,
        )
            .strip()
    )

    effective_date = (
        request.POST.get(
            "effective_date",
            "",
        )
            .strip()
    )

    effective_to = (
        request.POST.get(
            "effective_to",
            "",
        )
            .strip()
    )

    # ---------------------------------------------------------
    # REQUIRED VALIDATION
    # ---------------------------------------------------------

    if not staff_id:
        return JsonResponse(
            {
                "success": False,
                "error": "Please select a staff member.",
            },
            status=400,
        )

    if not basic_salary:
        return JsonResponse(
            {
                "success": False,
                "error": "Basic salary is required.",
            },
            status=400,
        )

    if not effective_date:
        return JsonResponse(
            {
                "success": False,
                "error": "Effective date is required.",
            },
            status=400,
        )

    # ---------------------------------------------------------
    # VALIDATE STAFF
    # ---------------------------------------------------------

    staff = get_object_or_404(
        StaffProfile.objects.select_related(
            "staff_grade",
            "user",
        ),
        pk=staff_id,
        school=school,
        is_active=True,
    )

    # ---------------------------------------------------------
    # STAFF GRADE
    #
    # The employee's current StaffProfile grade is authoritative
    # for classification.
    # ---------------------------------------------------------

    grade = getattr(
        staff,
        "staff_grade",
        None,
    )

    # ---------------------------------------------------------
    # CREATE
    # ---------------------------------------------------------

    try:

        from staff.services.salary_service import (
            create_salary_structure,
        )

        structure = create_salary_structure(
            staff=staff,
            staff_grade=grade,
            basic_salary=basic_salary,
            frequency=frequency,
            effective_date=effective_date,
            effective_to=effective_to or None,
            is_active=True,
        )

        return JsonResponse(
            {
                "success": True,
                "message": (
                    "Employee salary structure "
                    "created successfully."
                ),
                "id": str(
                    structure.pk
                ),
            }
        )


    except Exception as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )


# ============================================================
# EDIT SALARY STRUCTURE
# ============================================================

@login_required
def salary_structure_edit(
        request,
        structure_id,
):
    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "BURSAR",
    ]:
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    school = request.user.school

    structure = get_object_or_404(
        SalaryStructure.objects.select_related(
            "staff",
            "staff__user",
            "staff_grade",
        ),
        pk=structure_id,
        school=school,
    )

    # ---------------------------------------------------------
    # GET
    # ---------------------------------------------------------

    if request.method == "GET":

        staff_members = (
            StaffProfile.objects
                .filter(
                school=school,
                is_active=True,
            )
                .select_related(
                "user",
                "staff_grade",
            )
                .order_by(
                "user__last_name",
                "user__first_name",
            )
        )

        # -----------------------------------------------------
        # IMPORTANT:
        # If the existing salary structure belongs to a staff
        # member who has since become inactive, include that
        # employee so the edit form doesn't lose its selection.
        # -----------------------------------------------------

        if (
                structure.staff_id
                and structure.staff
                and not structure.staff.is_active
        ):
            staff_members = (
                StaffProfile.objects
                    .filter(
                    models.Q(
                        school=school,
                        is_active=True,
                    )
                    |
                    models.Q(
                        pk=structure.staff_id,
                    )
                )
                    .select_related(
                    "user",
                    "staff_grade",
                )
                    .order_by(
                    "user__last_name",
                    "user__first_name",
                )
            )

        grades = (
            StaffGrade.objects
                .filter(
                school=school,
                is_active=True,
            )
                .order_by(
                "name",
            )
        )

        return render(
            request,
            "staff/payroll/salary_structure_form_modal.html",
            {
                "mode": "edit",
                "structure": structure,
                "staff_members": staff_members,
                "grades": grades,
                "action_url": (
                    "staff:salary_structure_edit"
                ),
            },
        )

    # ---------------------------------------------------------
    # POST
    # ---------------------------------------------------------

    staff_id = (
        request.POST.get(
            "staff",
            "",
        )
            .strip()
    )

    basic_salary = (
        request.POST.get(
            "basic_salary",
            "",
        )
            .strip()
    )

    frequency = (
        request.POST.get(
            "frequency",
            SalaryStructure.FREQUENCY_MONTHLY,
        )
            .strip()
    )

    effective_date = (
        request.POST.get(
            "effective_date",
            "",
        )
            .strip()
    )

    effective_to = (
        request.POST.get(
            "effective_to",
            "",
        )
            .strip()
    )

    is_active = (
            request.POST.get(
                "is_active",
            )
            == "on"
    )

    # ---------------------------------------------------------
    # REQUIRED VALIDATION
    # ---------------------------------------------------------

    if not staff_id:
        return JsonResponse(
            {
                "success": False,
                "error": "Please select a staff member.",
            },
            status=400,
        )

    if not basic_salary:
        return JsonResponse(
            {
                "success": False,
                "error": "Basic salary is required.",
            },
            status=400,
        )

    if not effective_date:
        return JsonResponse(
            {
                "success": False,
                "error": "Effective date is required.",
            },
            status=400,
        )

    # ---------------------------------------------------------
    # VALIDATE STAFF
    # ---------------------------------------------------------

    staff = get_object_or_404(
        StaffProfile.objects.select_related(
            "staff_grade",
            "user",
        ),
        pk=staff_id,
        school=school,
        is_active=True,
    )

    # ---------------------------------------------------------
    # STAFF GRADE
    # ---------------------------------------------------------

    grade = getattr(
        staff,
        "staff_grade",
        None,
    )

    # ---------------------------------------------------------
    # UPDATE
    # ---------------------------------------------------------

    try:

        structure.staff = staff

        structure.staff_grade = grade

        structure.basic_salary = basic_salary

        structure.frequency = frequency

        structure.effective_date = effective_date

        structure.effective_to = (
                effective_to
                or None
        )

        structure.is_active = is_active

        structure.full_clean()

        structure.save()

        return JsonResponse(
            {
                "success": True,
                "message": (
                    "Employee salary structure "
                    "updated successfully."
                ),
            }
        )


    except Exception as exc:

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )


# ============================================================
# DELETE SALARY STRUCTURE
# ============================================================

@login_required
def salary_structure_delete(
        request,
        structure_id,
):
    if request.user.role not in [
        "SUPER_ADMIN",
        "SCHOOL_ADMIN",
        "BURSAR",
    ]:
        return JsonResponse(
            {
                "success": False,
                "error": "Permission denied.",
            },
            status=403,
        )

    school = request.user.school

    structure = get_object_or_404(
        SalaryStructure,
        id=structure_id,
        school=school,
    )

    if request.method == "GET":
        return render(
            request,
            "staff/payroll/salary_structure_delete_modal.html",
            {
                "structure": structure,
                "action_url": (
                    "staff:salary_structure_delete"
                ),
            },
        )

    structure.delete()

    return JsonResponse(
        {
            "success": True,
            "message": (
                "Salary structure deleted successfully."
            ),
        }
    )


# ============================================================
# ALLOWANCE VIEWS
# ============================================================

@login_required
def allowance_list(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to view allowances.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    allowances = Allowance.objects.filter(school=school).order_by('name')

    # Calculate stats in the view
    active_allowances = [a for a in allowances if a.is_active]
    percentage_allowances = [a for a in allowances if a.is_percentage]
    taxable_allowances = [a for a in allowances if a.taxable]

    context = {
        'allowances': paginate_queryset(allowances, request),
        'active_count': len(active_allowances),
        'percentage_count': len(percentage_allowances),
        'taxable_count': len(taxable_allowances),
        'active_tab': 'payroll'
    }
    return render(request, 'staff/payroll/allowance_list.html', context)


@login_required
def allowance_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        allowance_types = Allowance.ALLOWANCE_TYPE_CHOICES
        return render(request, 'staff/payroll/allowance_form_modal.html', {
            'mode': 'create',
            'allowance_types': allowance_types,
            'action_url': 'staff:allowance_create'
        })

    name = request.POST.get('name', '').strip()
    allowance_type = request.POST.get('allowance_type', 'OTHER').strip()
    amount = request.POST.get('amount', '').strip()
    is_percentage = request.POST.get('is_percentage') == 'on'
    taxable = request.POST.get('taxable') == 'on'
    description = request.POST.get('description', '').strip()

    if not all([name, amount]):
        return JsonResponse({'success': False, 'error': "Name and amount are required."})

    try:
        allowance = Allowance.objects.create(
            school=school,
            name=name,
            allowance_type=allowance_type,
            amount=amount,
            is_percentage=is_percentage,
            taxable=taxable,
            description=description,
        )
        return JsonResponse({'success': True, 'message': f"Allowance '{name}' created successfully."})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def allowance_edit(request, allowance_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    allowance = get_object_or_404(Allowance, id=allowance_id, school=school)

    if request.method == 'GET':
        allowance_types = Allowance.ALLOWANCE_TYPE_CHOICES
        return render(request, 'staff/payroll/allowance_form_modal.html', {
            'mode': 'edit',
            'allowance': allowance,
            'allowance_types': allowance_types,
            'action_url': 'staff:allowance_edit'
        })

    name = request.POST.get('name', '').strip()
    allowance_type = request.POST.get('allowance_type', 'OTHER').strip()
    amount = request.POST.get('amount', '').strip()
    is_percentage = request.POST.get('is_percentage') == 'on'
    taxable = request.POST.get('taxable') == 'on'
    description = request.POST.get('description', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not all([name, amount]):
        return JsonResponse({'success': False, 'error': "Name and amount are required."})

    allowance.name = name
    allowance.allowance_type = allowance_type
    allowance.amount = amount
    allowance.is_percentage = is_percentage
    allowance.taxable = taxable
    allowance.description = description
    allowance.is_active = is_active
    allowance.save()

    return JsonResponse({'success': True, 'message': f"Allowance '{name}' updated successfully."})


@login_required
def allowance_delete(request, allowance_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    allowance = get_object_or_404(Allowance, id=allowance_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/payroll/allowance_delete_modal.html', {
            'allowance': allowance,
            'action_url': 'staff:allowance_delete'
        })

    allowance.delete()
    return JsonResponse({'success': True, 'message': "Allowance deleted successfully."})


# ==========================================================
# STAFF ALLOWANCE ASSIGNMENTS
# ==========================================================


@login_required
def staff_allowance_list(request):
    """
    Display all allowance assignments for staff in the
    current school with pagination.

    Only active staff are shown because payroll applies
    salary/allowances only to active staff.
    """

    if request.user.role not in [
        'SUPER_ADMIN',
        'SCHOOL_ADMIN',
        'BURSAR',
    ]:
        messages.error(
            request,
            "You don't have permission to manage staff allowances."
        )
        return redirect('dashboard:dashboard')

    school = getattr(request.user, 'school', None)

    if not school:
        messages.error(
            request,
            "Your account is not linked to a school."
        )
        return redirect('dashboard:dashboard')

    # Build the queryset
    staff_allowances = (
        StaffAllowance.objects
        .filter(
            school=school,
            staff__is_active=True,
        )
        .select_related(
            'staff',
            'staff__user',
            'staff__staff_grade',
            'allowance',
        )
        .order_by(
            'staff__user__last_name',
            'staff__user__first_name',
            'allowance__name',
        )
    )

    # Add pagination
    page_obj = paginate_queryset(staff_allowances, request)
    paginator = page_obj.paginator

    return render(
        request,
        'staff/payroll/staff_allowance_list.html',
        {
            'staff_allowances': page_obj.object_list,
            'page_obj': page_obj,
            'paginator': paginator,
            'total_count': paginator.count,
            'active_tab': 'payroll',
        }
    )



@login_required
def staff_allowance_create(request):
    """
    Assign an existing Allowance to a staff member.

    This is the assignment that the payroll engine reads.
    """

    if request.user.role not in [
        'SUPER_ADMIN',
        'SCHOOL_ADMIN',
        'BURSAR',
    ]:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Permission denied.'
                },
                status=403
            )
        messages.error(request, "You don't have permission to assign allowances.")
        return redirect('staff:staff_allowance_list')

    school = getattr(request.user, 'school', None)

    if not school:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Your account is not linked to a school.'
                },
                status=400
            )
        messages.error(request, "Your account is not linked to a school.")
        return redirect('staff:staff_allowance_list')

    # ------------------------------------------------------
    # GET
    # ------------------------------------------------------

    if request.method == 'GET':

        staff_members = (
            StaffProfile.objects
            .filter(
                school=school,
                is_active=True,
            )
            .select_related(
                'user',
                'staff_grade',
            )
            .order_by(
                'user__last_name',
                'user__first_name',
            )
        )

        allowances = (
            Allowance.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by('name')
        )

        return render(
            request,
            'staff/payroll/staff_allowance_form_modal.html',
            {
                'mode': 'create',
                'staff_members': staff_members,
                'allowances': allowances,
                'action_url': 'staff:staff_allowance_create',
            }
        )

    # ------------------------------------------------------
    # POST
    # ------------------------------------------------------

    staff_id = request.POST.get(
        'staff',
        ''
    ).strip()

    allowance_id = request.POST.get(
        'allowance',
        ''
    ).strip()

    amount = request.POST.get(
        'amount',
        ''
    ).strip()

    is_active = (
        request.POST.get('is_active')
        == 'on'
    )

    if not staff_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Please select a staff member.'
                }
            )
        messages.error(request, "Please select a staff member.")
        return redirect('staff:staff_allowance_list')

    if not allowance_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Please select an allowance.'
                }
            )
        messages.error(request, "Please select an allowance.")
        return redirect('staff:staff_allowance_list')

    try:

        staff = get_object_or_404(
            StaffProfile,
            id=staff_id,
            school=school,
            is_active=True,
        )

        allowance = get_object_or_404(
            Allowance,
            id=allowance_id,
            school=school,
            is_active=True,
        )

        # --------------------------------------------------
        # Prevent duplicate assignment
        # --------------------------------------------------

        existing = (
            StaffAllowance.objects
            .filter(
                school=school,
                staff=staff,
                allowance=allowance,
            )
            .first()
        )

        if existing:
            error_msg = (
                f"{allowance.name} is already assigned "
                f"to {staff.user.get_full_name()}."
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse(
                    {
                        'success': False,
                        'error': error_msg
                    }
                )
            messages.error(request, error_msg)
            return redirect('staff:staff_allowance_list')

        # --------------------------------------------------
        # Amount
        #
        # Blank means use the allowance's configured amount.
        # --------------------------------------------------

        if amount:
            assignment_amount = amount
        else:
            assignment_amount = None  # Let the model use default

        staff_allowance = StaffAllowance.objects.create(
            school=school,
            staff=staff,
            allowance=allowance,
            amount=assignment_amount,
            is_active=is_active,
        )

        success_msg = (
            f"{allowance.name} assigned successfully "
            f"to {staff.user.get_full_name()}."
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': True,
                    'message': success_msg,
                    'staff_allowance_id': str(
                        staff_allowance.id
                    ),
                }
            )

        messages.success(request, success_msg)
        return redirect('staff:staff_allowance_list')

    except Exception as exc:

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': str(exc),
                },
                status=400
            )

        messages.error(request, f"Error: {str(exc)}")
        return redirect('staff:staff_allowance_list')



@login_required
def staff_allowance_edit(request, staff_allowance_id,):
    """
    Edit an existing staff allowance assignment.
    """

    if request.user.role not in [
        'SUPER_ADMIN',
        'SCHOOL_ADMIN',
        'BURSAR',
    ]:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Permission denied.'
                },
                status=403
            )
        messages.error(request, "You don't have permission to edit staff allowances.")
        return redirect('staff:staff_allowance_list')

    school = getattr(
        request.user,
        'school',
        None,
    )

    if not school:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Your account is not linked to a school.'
                },
                status=400
            )
        messages.error(request, "Your account is not linked to a school.")
        return redirect('staff:staff_allowance_list')

    staff_allowance = get_object_or_404(
        StaffAllowance.objects.select_related(
            'staff',
            'staff__user',
            'allowance',
        ),
        id=staff_allowance_id,
        school=school,
    )

    # ------------------------------------------------------
    # GET
    # ------------------------------------------------------

    if request.method == 'GET':

        staff_members = (
            StaffProfile.objects
            .filter(
                school=school,
                is_active=True,
            )
            .select_related(
                'user',
                'staff_grade',
            )
            .order_by(
                'user__last_name',
                'user__first_name',
            )
        )

        allowances = (
            Allowance.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by('name')
        )

        return render(
            request,
            'staff/payroll/staff_allowance_form_modal.html',
            {
                'mode': 'edit',
                'staff_allowance': staff_allowance,
                'staff_members': staff_members,
                'allowances': allowances,
                'action_url': 'staff:staff_allowance_edit',
            }
        )

    # ------------------------------------------------------
    # POST
    # ------------------------------------------------------

    staff_id = request.POST.get(
        'staff',
        ''
    ).strip()

    allowance_id = request.POST.get(
        'allowance',
        ''
    ).strip()

    amount = request.POST.get(
        'amount',
        ''
    ).strip()

    is_active = (
        request.POST.get('is_active')
        == 'on'
    )

    if not staff_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Please select a staff member.'
                }
            )
        messages.error(request, "Please select a staff member.")
        return redirect('staff:staff_allowance_list')

    if not allowance_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Please select an allowance.'
                }
            )
        messages.error(request, "Please select an allowance.")
        return redirect('staff:staff_allowance_list')

    try:

        staff = get_object_or_404(
            StaffProfile,
            id=staff_id,
            school=school,
            is_active=True,
        )

        allowance = get_object_or_404(
            Allowance,
            id=allowance_id,
            school=school,
            is_active=True,
        )

        # --------------------------------------------------
        # Check duplicate assignment
        # --------------------------------------------------

        duplicate = (
            StaffAllowance.objects
            .filter(
                school=school,
                staff=staff,
                allowance=allowance,
            )
            .exclude(
                id=staff_allowance.id
            )
            .exists()
        )

        if duplicate:
            error_msg = (
                f"{allowance.name} is already assigned "
                f"to this staff member."
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse(
                    {
                        'success': False,
                        'error': error_msg
                    }
                )
            messages.error(request, error_msg)
            return redirect('staff:staff_allowance_list')

        # --------------------------------------------------
        # Amount - keep as None to use default
        # --------------------------------------------------

        if amount:
            assignment_amount = amount
        else:
            assignment_amount = None

        staff_allowance.staff = staff
        staff_allowance.allowance = allowance
        staff_allowance.amount = assignment_amount
        staff_allowance.is_active = is_active

        staff_allowance.save()

        success_msg = (
            f"{allowance.name} assignment updated "
            f"successfully."
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': True,
                    'message': success_msg
                }
            )

        messages.success(request, success_msg)
        return redirect('staff:staff_allowance_list')

    except Exception as exc:

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': str(exc),
                },
                status=400
            )

        messages.error(request, f"Error: {str(exc)}")
        return redirect('staff:staff_allowance_list')


@login_required
def staff_allowance_delete(request, staff_allowance_id,):
    """
    Delete a staff allowance assignment.
    """

    if request.user.role not in [
        'SUPER_ADMIN',
        'SCHOOL_ADMIN',
        'BURSAR',
    ]:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Permission denied.'
                },
                status=403
            )
        messages.error(request, "You don't have permission to delete staff allowances.")
        return redirect('staff:staff_allowance_list')

    school = getattr(
        request.user,
        'school',
        None,
    )

    if not school:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {
                    'success': False,
                    'error': 'Your account is not linked to a school.'
                },
                status=400
            )
        messages.error(request, "Your account is not linked to a school.")
        return redirect('staff:staff_allowance_list')

    staff_allowance = get_object_or_404(
        StaffAllowance.objects.select_related(
            'staff',
            'staff__user',
            'allowance',
        ),
        id=staff_allowance_id,
        school=school,
    )

    if request.method == 'GET':

        return render(
            request,
            'staff/payroll/staff_allowance_delete_modal.html',
            {
                'staff_allowance': staff_allowance,
                'action_url': 'staff:staff_allowance_delete',
            }
        )

    staff_name = (
        staff_allowance.staff.user.get_full_name()
        or staff_allowance.staff.user.username
    )

    allowance_name = (
        staff_allowance.allowance.name
    )

    staff_allowance.delete()

    success_msg = (
        f"{allowance_name} was removed from "
        f"{staff_name}."
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(
            {
                'success': True,
                'message': success_msg
            }
        )

    messages.success(request, success_msg)
    return redirect('staff:staff_allowance_list')


@login_required
@require_POST
def staff_allowance_toggle_active(
        request,
        staff_allowance_id,
):
    """
    Activate/deactivate a staff allowance assignment.

    Payroll only uses active assignments.
    """

    if request.user.role not in [
        'SUPER_ADMIN',
        'SCHOOL_ADMIN',
        'BURSAR',
    ]:
        return JsonResponse(
            {
                'success': False,
                'error': 'Permission denied.'
            },
            status=403
        )

    school = getattr(
        request.user,
        'school',
        None,
    )

    staff_allowance = get_object_or_404(
        StaffAllowance,
        id=staff_allowance_id,
        school=school,
    )

    staff_allowance.is_active = (
        not staff_allowance.is_active
    )

    staff_allowance.save(
        update_fields=[
            'is_active',
        ]
    )

    status_text = (
        'activated'
        if staff_allowance.is_active
        else 'deactivated'
    )

    return JsonResponse(
        {
            'success': True,
            'is_active': (
                staff_allowance.is_active
            ),
            'message': (
                f"Staff allowance {status_text} successfully."
            ),
        }
    )


# ==========================================================
# STAFF-SPECIFIC ALLOWANCES
# ==========================================================

@login_required
def staff_allowance_staff_list(
        request,
        staff_id,
):
    """
    Display allowances assigned to one staff member.
    """

    if request.user.role not in [
        'SUPER_ADMIN',
        'SCHOOL_ADMIN',
        'BURSAR',
    ]:
        messages.error(
            request,
            "You don't have permission to manage allowances."
        )
        return redirect('dashboard:dashboard')

    school = getattr(
        request.user,
        'school',
        None,
    )

    staff = get_object_or_404(
        StaffProfile.objects.select_related(
            'user',
            'staff_grade',
        ),
        id=staff_id,
        school=school,
    )

    staff_allowances = (
        StaffAllowance.objects
        .filter(
            school=school,
            staff=staff,
        )
        .select_related(
            'allowance',
        )
        .order_by(
            'allowance__name',
        )
    )

    return render(
        request,
        'staff/payroll/staff_allowance_list.html',
        {
            'staff': staff,
            'staff_allowances': paginate_queryset(staff_allowances, request),
            'active_tab': 'payroll',
        }
    )


@login_required
def staff_allowance_staff_create(
        request,
        staff_id,
):
    """
    Assign an allowance directly to one staff member.
    """

    if request.user.role not in [
        'SUPER_ADMIN',
        'SCHOOL_ADMIN',
        'BURSAR',
    ]:
        return JsonResponse(
            {
                'success': False,
                'error': 'Permission denied.'
            },
            status=403
        )

    school = getattr(
        request.user,
        'school',
        None,
    )

    staff = get_object_or_404(
        StaffProfile.objects.select_related(
            'user',
        ),
        id=staff_id,
        school=school,
        is_active=True,
    )

    if request.method == 'GET':

        allowances = (
            Allowance.objects
            .filter(
                school=school,
                is_active=True,
            )
            .order_by(
                'name',
            )
        )

        return render(
            request,
            'staff/payroll/staff_allowance_form_modal.html',
            {
                'mode': 'create',
                'staff': staff,
                'staff_members': [staff],
                'allowances': allowances,
                'action_url': 'staff:staff_allowance_staff_create',
            }
        )

    allowance_id = request.POST.get(
        'allowance_id',
        ''
    ).strip()

    amount = request.POST.get(
        'amount',
        ''
    ).strip()

    is_active = (
        request.POST.get('is_active')
        == 'on'
    )

    if not allowance_id:
        return JsonResponse(
            {
                'success': False,
                'error': 'Please select an allowance.'
            }
        )

    try:

        allowance = get_object_or_404(
            Allowance,
            id=allowance_id,
            school=school,
            is_active=True,
        )

        if (
            StaffAllowance.objects
            .filter(
                school=school,
                staff=staff,
                allowance=allowance,
            )
            .exists()
        ):
            return JsonResponse(
                {
                    'success': False,
                    'error': (
                        f"{allowance.name} is already "
                        f"assigned to this staff member."
                    )
                }
            )

        assignment_amount = (
            amount
            if amount
            else allowance.amount
        )

        staff_allowance = (
            StaffAllowance.objects.create(
                school=school,
                staff=staff,
                allowance=allowance,
                amount=assignment_amount,
                is_active=is_active,
            )
        )

        return JsonResponse(
            {
                'success': True,
                'message': (
                    f"{allowance.name} assigned successfully "
                    f"to {staff.user.get_full_name()}."
                ),
                'staff_allowance_id': str(
                    staff_allowance.id
                ),
            }
        )

    except Exception as exc:

        return JsonResponse(
            {
                'success': False,
                'error': str(exc),
            },
            status=400
        )


# ============================================================
# DEDUCTION VIEWS
# ============================================================

@login_required
def deduction_list(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to view deductions.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    deductions = Deduction.objects.filter(school=school).order_by('name')

    # Calculate stats in the view
    active_deductions = [d for d in deductions if d.is_active]
    mandatory_deductions = [d for d in deductions if d.is_mandatory]
    percentage_deductions = [d for d in deductions if d.is_percentage]

    context = {
        'deductions': paginate_queryset(deductions, request),
        'active_count': len(active_deductions),
        'mandatory_count': len(mandatory_deductions),
        'percentage_count': len(percentage_deductions),
        'active_tab': 'payroll'
    }
    return render(request, 'staff/payroll/deduction_list.html', context)


@login_required
def deduction_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        deduction_types = Deduction.DEDUCTION_TYPE_CHOICES
        return render(request, 'staff/payroll/deduction_form_modal.html', {
            'mode': 'create',
            'deduction_types': deduction_types,
            'action_url': 'staff:deduction_create'
        })

    name = request.POST.get('name', '').strip()
    deduction_type = request.POST.get('deduction_type', 'OTHER').strip()
    amount = request.POST.get('amount', '').strip()
    is_percentage = request.POST.get('is_percentage') == 'on'
    is_mandatory = request.POST.get('is_mandatory') == 'on'
    description = request.POST.get('description', '').strip()

    if not all([name, amount]):
        return JsonResponse({'success': False, 'error': "Name and amount are required."})

    try:
        deduction = Deduction.objects.create(
            school=school,
            name=name,
            deduction_type=deduction_type,
            amount=amount,
            is_percentage=is_percentage,
            is_mandatory=is_mandatory,
            description=description,
        )
        return JsonResponse({'success': True, 'message': f"Deduction '{name}' created successfully."})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def deduction_edit(request, deduction_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    deduction = get_object_or_404(Deduction, id=deduction_id, school=school)

    if request.method == 'GET':
        deduction_types = Deduction.DEDUCTION_TYPE_CHOICES
        return render(request, 'staff/payroll/deduction_form_modal.html', {
            'mode': 'edit',
            'deduction': deduction,
            'deduction_types': deduction_types,
            'action_url': 'staff:deduction_edit'
        })

    name = request.POST.get('name', '').strip()
    deduction_type = request.POST.get('deduction_type', 'OTHER').strip()
    amount = request.POST.get('amount', '').strip()
    is_percentage = request.POST.get('is_percentage') == 'on'
    is_mandatory = request.POST.get('is_mandatory') == 'on'
    description = request.POST.get('description', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not all([name, amount]):
        return JsonResponse({'success': False, 'error': "Name and amount are required."})

    deduction.name = name
    deduction.deduction_type = deduction_type
    deduction.amount = amount
    deduction.is_percentage = is_percentage
    deduction.is_mandatory = is_mandatory
    deduction.description = description
    deduction.is_active = is_active
    deduction.save()

    return JsonResponse({'success': True, 'message': f"Deduction '{name}' updated successfully."})


@login_required
def deduction_delete(request, deduction_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    deduction = get_object_or_404(Deduction, id=deduction_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/payroll/deduction_delete_modal.html', {
            'deduction': deduction,
            'action_url': 'staff:deduction_delete'
        })

    deduction.delete()
    return JsonResponse({'success': True, 'message': "Deduction deleted successfully."})


# ============================================================
# PAYROLL VIEWS
# ============================================================

@login_required
def payroll_dashboard(request):
    """
    Payroll Dashboard.

    Features:
    - School-isolated payroll data.
    - Displays ALL payslip records belonging to the school.
    - Independent pagination for payroll periods and payslips.
    - Never uses .first() for payslips.
    - Preserves the other pagination parameter while navigating.
    - Uses select_related to avoid unnecessary database queries.
    """

    school = getattr(request.user, "school", None)

    # ============================================================
    # EMPTY / NO SCHOOL
    # ============================================================

    if not school:
        return render(
            request,
            "staff/payroll/payroll_dashboard.html",
            {
                "total_staff": 0,
                "total_payroll_runs": 0,
                "current_period": None,

                "recent_periods": [],
                "period_page_obj": None,
                "period_paginator": None,
                "period_page_range": [],

                "latest_payslips": [],
                "payslip_page_obj": None,
                "payslip_paginator": None,
                "payslip_page_range": [],

                "total_payslips": 0,
            },
        )

    # ============================================================
    # STAFF
    # ============================================================

    total_staff = (
        StaffProfile.objects
        .filter(
            school=school,
            is_active=True,
        )
        .count()
    )

    # ============================================================
    # PAYROLL RUNS
    # ============================================================

    total_payroll_runs = (
        PayrollRun.objects
        .filter(
            school=school,
        )
        .count()
    )

    # ============================================================
    # CURRENT PAYROLL PERIOD
    # ============================================================

    current_period = (
        PayrollPeriod.objects
        .filter(
            school=school,
            status__in=[
                "OPEN",
                "PROCESSING",
            ],
        )
        .order_by(
            "-period_end",
            "-created_at",
        )
        .first()
    )

    # ============================================================
    # PAYROLL PERIODS
    # ============================================================

    period_queryset = (
        PayrollPeriod.objects
        .filter(
            school=school,
        )
        .order_by(
            "-period_end",
            "-created_at",
            "-id",
        )
    )

    period_paginator = Paginator(
        period_queryset,
        10,
    )

    period_page_number = request.GET.get(
        "period_page",
        1,
    )

    try:
        period_page_obj = period_paginator.page(
            period_page_number
        )
    except PageNotAnInteger:
        period_page_obj = period_paginator.page(1)
    except EmptyPage:
        period_page_obj = period_paginator.page(
            period_paginator.num_pages or 1
        )

    recent_periods = list(
        period_page_obj.object_list
    )

    # ============================================================
    # PERIOD PAGE RANGE
    # ============================================================

    if period_paginator.num_pages:
        period_page_range = list(
            period_paginator.get_elided_page_range(
                number=period_page_obj.number,
                on_each_side=2,
                on_ends=1,
            )
        )
    else:
        period_page_range = []

    # ============================================================
    # PAYSLIPS
    # ============================================================
    #
    # IMPORTANT:
    # We query Payslip directly.
    #
    # We do NOT use:
    #     .first()
    #
    # We do NOT use:
    #     values(...)
    #
    # We do NOT use:
    #     distinct() to collapse payslips.
    #
    # Every Payslip row belonging to this school remains
    # an individual result.
    # ============================================================

    payslip_queryset = (
        Payslip.objects
        .filter(
            school=school,
            payroll_run__school=school,
        )
        .select_related(
            "payroll_run",
            "payroll_run__staff",
            "payroll_run__staff__user",
            "payroll_run__payroll_period",
        )
        .order_by(
            "-generated_at",
            "-id",
        )
    )

    # ============================================================
    # TOTAL PAYSLIPS
    # ============================================================

    total_payslips = payslip_queryset.count()

    # ============================================================
    # PAYSLIP PAGINATION
    # ============================================================

    payslip_paginator = Paginator(
        payslip_queryset,
        10,
    )

    payslip_page_number = request.GET.get(
        "payslip_page",
        1,
    )

    try:
        payslip_page_obj = payslip_paginator.page(
            payslip_page_number
        )
    except PageNotAnInteger:
        payslip_page_obj = payslip_paginator.page(1)
    except EmptyPage:
        payslip_page_obj = payslip_paginator.page(
            payslip_paginator.num_pages or 1
        )

    latest_payslips = list(
        payslip_page_obj.object_list
    )

    # ============================================================
    # PAYSLIP PAGE RANGE
    # ============================================================

    if payslip_paginator.num_pages:
        payslip_page_range = list(
            payslip_paginator.get_elided_page_range(
                number=payslip_page_obj.number,
                on_each_side=2,
                on_ends=1,
            )
        )
    else:
        payslip_page_range = []

    # ============================================================
    # RENDER
    # ============================================================

    return render(
        request,
        "staff/payroll/payroll_dashboard.html",
        {
            # Staff
            "total_staff": total_staff,

            # Payroll
            "total_payroll_runs": total_payroll_runs,

            # Current period
            "current_period": current_period,

            # Period pagination
            "recent_periods": recent_periods,
            "period_page_obj": period_page_obj,
            "period_paginator": period_paginator,
            "period_page_range": period_page_range,

            # Payslip pagination
            "latest_payslips": latest_payslips,
            "payslip_page_obj": payslip_page_obj,
            "payslip_paginator": payslip_paginator,
            "payslip_page_range": payslip_page_range,

            # Total payslips
            "total_payslips": total_payslips,
        },
    )


@login_required
def payroll_period_list(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to view payroll periods.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    periods = PayrollPeriod.objects.filter(school=school).order_by('-period_end')

    context = {
        'periods': paginate_queryset(periods, request),
        'active_tab': 'payroll'
    }
    return render(request, 'staff/payroll/payroll_period_list.html', context)


@login_required
def payroll_period_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        return render(request, 'staff/payroll/payroll_period_form_modal.html', {
            'mode': 'create',
            'action_url': 'staff:payroll_period_create'
        })

    name = request.POST.get('name', '').strip()
    period_start = request.POST.get('period_start', '').strip()
    period_end = request.POST.get('period_end', '').strip()
    payment_date = request.POST.get('payment_date', '').strip()
    notes = request.POST.get('notes', '').strip()

    if not all([name, period_start, period_end, payment_date]):
        return JsonResponse({'success': False, 'error': "All fields are required."})

    try:
        period = PayrollPeriod.objects.create(
            school=school,
            name=name,
            period_start=period_start,
            period_end=period_end,
            payment_date=payment_date,
            notes=notes,
            created_by=request.user,
            status='DRAFT'
        )
        return JsonResponse({'success': True, 'message': f"Payroll period '{name}' created successfully."})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def payroll_period_detail(request, period_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    period = get_object_or_404(PayrollPeriod, id=period_id, school=school)
    runs = PayrollRun.objects.filter(payroll_period=period).select_related('staff__user')

    total_gross = runs.aggregate(Sum('gross_pay'))['gross_pay__sum'] or Decimal('0.00')
    total_net = runs.aggregate(Sum('net_pay'))['net_pay__sum'] or Decimal('0.00')

    context = {
        'period': period,
        'runs': runs,
        'total_gross': total_gross,
        'total_net': total_net,
        'active_tab': 'payroll'
    }
    return render(request, 'staff/payroll/payroll_period_detail.html', context)


@login_required
@require_POST
def process_payroll(request, period_id):
    """
    Prepare/process payroll for a payroll period with proper error handling.
    """
    from .services.payroll_service import prepare_payroll, PayrollPreparationError
    import time

    started = time.monotonic()

    # ==============================================================
    # AUTHORIZATION
    # ==============================================================

    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to process payroll.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    # ==============================================================
    # LOAD PERIOD
    # ==============================================================

    school = getattr(request.user, "school", None)

    if not school:
        messages.error(request, "Your account is not linked to a school.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    period = get_object_or_404(PayrollPeriod, id=period_id, school=school)

    # ==============================================================
    # CHECK PERIOD STATUS
    # ==============================================================

    if period.status in ('CLOSED', 'APPROVED'):
        messages.error(request,
                       f"This payroll period is {period.get_status_display().lower()} and cannot be processed.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    # ==============================================================
    # PROCESS PAYROLL
    # ==============================================================

    try:
        result = prepare_payroll(
            period=period,
            processed_by=request.user,
        )

        # Check if we got a successful result
        if result and result.get('success', False):
            messages.success(
                request,
                f"Payroll processed successfully for {result.get('prepared_count', 0)} staff members."
            )
        else:
            messages.success(
                request,
                "Payroll processed successfully."
            )

        return redirect('staff:payroll_period_detail', period_id=period_id)

    # ==============================================================
    # EXPECTED PAYROLL PREPARATION ERROR - Show user-friendly message
    # ==============================================================

    except PayrollPreparationError as exc:
        error_message = str(exc)

        # Format the error message for better display in Django messages
        # Replace newlines with <br> for HTML display
        formatted_error = error_message.replace('\n', '<br>')

        messages.error(
            request,
            f"Payroll could not be processed.<br><br>{formatted_error}"
        )

        logger.warning(
            "Payroll preparation failed. "
            "user=%s school=%s period=%s error=%s",
            getattr(request.user, "pk", None),
            getattr(school, "pk", None) if school else None,
            period_id,
            str(exc),
        )

        return redirect('staff:payroll_period_detail', period_id=period_id)

    # ==============================================================
    # UNEXPECTED ERROR
    # ==============================================================

    except Exception as exc:
        logger.exception(
            "Unexpected payroll processing error. "
            "user=%s school=%s period=%s",
            getattr(request.user, "pk", None),
            getattr(school, "pk", None) if school else None,
            period_id,
        )

        messages.error(
            request,
            f"An unexpected error occurred while processing payroll. Please contact support."
        )

        return redirect('staff:payroll_period_detail', period_id=period_id)


@login_required
@require_POST
def approve_payroll(request, period_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    period = get_object_or_404(PayrollPeriod, id=period_id, school=school)

    period.status = 'APPROVED'
    period.approved_by = request.user
    period.approved_at = timezone.now()
    period.save(update_fields=['status', 'approved_by', 'approved_at'])

    return JsonResponse({'success': True, 'message': "Payroll period approved successfully."})


@login_required
@require_POST
def close_payroll(request, period_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    period = get_object_or_404(PayrollPeriod, id=period_id, school=school)

    period.status = 'CLOSED'
    period.save(update_fields=['status'])

    return JsonResponse({'success': True, 'message': "Payroll period closed successfully."})


# ============================================================
# PAYSLIP VIEWS
# ============================================================

@login_required
def payslip_list(request):
    """
    Display ALL payslips belonging to the current user's school.

    Features:
    - School isolation.
    - Every Payslip record is returned.
    - Server-side pagination.
    - No .first().
    - No accidental grouping/collapsing.
    - Safe handling of invalid page numbers.
    """

    school = getattr(request.user, "school", None)

    # ============================================================
    # NO SCHOOL
    # ============================================================

    if not school:
        return render(
            request,
            "staff/payroll/payslip_list.html",
            {
                "payslips": [],
                "page_obj": None,
                "paginator": None,
                "page_range": [],
                "total_payslips": 0,
            },
        )

    # ============================================================
    # ALL SCHOOL PAYSLIPS
    # ============================================================

    payslip_queryset = (
        Payslip.objects
        .filter(
            school=school,
            payroll_run__school=school,
        )
        .select_related(
            "payroll_run",
            "payroll_run__staff",
            "payroll_run__staff__user",
            "payroll_run__payroll_period",
        )
        .order_by(
            "-generated_at",
            "-id",
        )
    )

    # ============================================================
    # TOTAL
    # ============================================================

    total_payslips = payslip_queryset.count()

    # ============================================================
    # PAGINATION
    # ============================================================

    paginator = Paginator(
        payslip_queryset,
        20,
    )

    page_number = request.GET.get(
        "page",
        1,
    )

    try:
        page_obj = paginator.page(
            page_number
        )
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(
            paginator.num_pages or 1
        )

    payslips = list(
        page_obj.object_list
    )

    # ============================================================
    # ELIDED PAGE RANGE
    # ============================================================

    if paginator.num_pages:
        page_range = list(
            paginator.get_elided_page_range(
                number=page_obj.number,
                on_each_side=2,
                on_ends=1,
            )
        )
    else:
        page_range = []

    # ============================================================
    # RENDER
    # ============================================================

    return render(
        request,
        "staff/payroll/payslip_list.html",
        {
            "payslips": payslips,
            "page_obj": page_obj,
            "paginator": paginator,
            "page_range": page_range,
            "total_payslips": total_payslips,
        },
    )


@login_required
def payslip_detail(request, payslip_id):
    school = request.user.school
    payslip = get_object_or_404(
        Payslip.objects.select_related(
            'payroll_run__staff__user',
            'payroll_run__payroll_period'
        ),
        id=payslip_id,
        school=school
    )

    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        if payslip.payroll_run.staff.user != request.user:
            messages.error(request, "You don't have permission to view this payslip.")
            return redirect('staff:payslip_list')

    context = {
        'payslip': payslip,
        'active_tab': 'payroll'
    }
    return render(request, 'staff/payroll/payslip_detail.html', context)


@login_required
def download_payslip(request, payslip_id):
    school = request.user.school
    payslip = get_object_or_404(Payslip, id=payslip_id, school=school)

    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        if payslip.payroll_run.staff.user != request.user:
            messages.error(request, "You don't have permission to download this payslip.")
            return redirect('staff:payslip_list')

    if payslip.pdf_file:
        response = HttpResponse(payslip.pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="payslip_{payslip.id}.pdf"'
        return response

    context = {
        'payslip': payslip,
    }
    return render(request, 'staff/payroll/payslip_print.html', context)


@login_required
@require_POST
def generate_payslip(request, payslip_id):
    """
    Generate or regenerate a single payslip.
    Accepts either a Payslip ID or a PayrollRun ID.
    """
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to generate payslips.")
        return redirect('staff:payroll_period_list')

    school = request.user.school

    # Try to find the payslip directly first
    payslip = None
    payroll_run = None

    try:
        # Try as Payslip ID
        payslip = Payslip.objects.get(id=payslip_id, school=school)
        payroll_run = payslip.payroll_run
    except Payslip.DoesNotExist:
        # Try as PayrollRun ID (the URL param might actually be a run_id)
        try:
            payroll_run = PayrollRun.objects.get(id=payslip_id, school=school)
        except PayrollRun.DoesNotExist:
            messages.error(request, "No payslip or payroll run found with the provided ID.")
            return redirect('staff:payroll_period_list')

    try:
        from .services.payroll_service import PayslipService

        if payslip:
            # Regenerate existing payslip
            generated_payslip = PayslipService.generate(
                payroll_run=payslip.payroll_run,
                generated_by=request.user,
            )
        else:
            # Create new payslip for the run
            # Check if payslip already exists
            existing_payslip = Payslip.objects.filter(payroll_run=payroll_run).first()
            if existing_payslip:
                generated_payslip = PayslipService.generate(
                    payroll_run=payroll_run,
                    generated_by=request.user,
                )
            else:
                # Create new payslip
                generated_payslip = Payslip.objects.create(
                    school=school,
                    payroll_run=payroll_run,
                    generated_by=request.user,
                )
                # Generate the content
                generated_payslip = PayslipService.generate(
                    payroll_run=payroll_run,
                    generated_by=request.user,
                )

        staff_name = payroll_run.staff.user.get_full_name()
        messages.success(request, f'Payslip generated successfully for {staff_name}.')
        return redirect('staff:payslip_detail', payslip_id=generated_payslip.id)

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to generate payslip: {str(e)}")
        messages.error(request, f"Failed to generate payslip: {str(e)}")
        return redirect('staff:payroll_period_list')


@login_required
@require_POST
def generate_bulk_payslips(request, period_id):
    """
    Generate payslips for multiple payroll runs in a period.
    """
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to generate payslips.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    school = request.user.school
    period = get_object_or_404(PayrollPeriod, id=period_id, school=school)

    # Get selected payroll run IDs from POST
    payroll_run_ids = request.POST.get('payroll_run_ids', '')
    if payroll_run_ids:
        payroll_run_ids = payroll_run_ids.split(',')
    else:
        payroll_run_ids = request.POST.getlist('payroll_run_ids')

    if not payroll_run_ids:
        messages.error(request, "Please select at least one staff member.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    from .services.payroll_service import PayslipService

    generated_count = 0
    failed_count = 0
    failed_list = []

    for run_id in payroll_run_ids:
        try:
            payroll_run = PayrollRun.objects.get(id=run_id, payroll_period=period, school=school)

            # Check if payslip exists, if not create it
            payslip, created = Payslip.objects.get_or_create(
                payroll_run=payroll_run,
                defaults={
                    'school': school,
                    'earnings': {},
                    'deductions': {},
                    'generated_by': request.user,
                }
            )

            # Regenerate payslip content
            result = PayslipService.generate(
                payroll_run=payroll_run,
                generated_by=request.user,
            )

            generated_count += 1

        except Exception as e:
            failed_count += 1
            failed_list.append({
                'staff_name': payroll_run.staff.user.get_full_name(),
                'error': str(e)
            })

    if generated_count > 0:
        messages.success(request, f"Successfully generated {generated_count} payslip(s).")

    if failed_count > 0:
        error_messages = [f"{f['staff_name']}: {f['error']}" for f in failed_list]
        messages.warning(request, f"Failed to generate {failed_count} payslip(s): " + ", ".join(error_messages))

    return redirect('staff:payroll_period_detail', period_id=period_id)


@login_required
def bulk_print_payslips(request, period_id):
    """
    Print multiple payslips at once.
    """
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to print payslips.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    school = request.user.school
    period = get_object_or_404(PayrollPeriod, id=period_id, school=school)

    # Get selected payslip IDs from GET
    payslip_ids = request.GET.get('payslip_ids', '')
    if payslip_ids:
        payslip_ids = payslip_ids.split(',')
    else:
        payslip_ids = request.GET.getlist('payslip_ids')

    if not payslip_ids:
        messages.error(request, "Please select at least one payslip to print.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    payslips = Payslip.objects.filter(
        id__in=payslip_ids,
        school=school,
        payroll_run__payroll_period=period
    ).select_related(
        'payroll_run__staff__user',
        'payroll_run__payroll_period'
    )

    if not payslips:
        messages.error(request, "No payslips found to print.")
        return redirect('staff:payroll_period_detail', period_id=period_id)

    # Render the bulk print template
    return render(request, 'staff/payroll/payslip_bulk_print.html', {
        'payslips': payslips,
        'period': period,
        'school': school,
    })


@login_required
@require_POST
def generate_payslip_from_run(request, run_id):
    """
    Generate a payslip from a PayrollRun ID.
    """
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']:
        messages.error(request, "You don't have permission to generate payslips.")
        return redirect('staff:payroll_period_list')

    school = request.user.school

    try:
        payroll_run = PayrollRun.objects.get(id=run_id, school=school)
    except PayrollRun.DoesNotExist:
        messages.error(request, "Payroll run not found.")
        return redirect('staff:payroll_period_list')

    try:
        from .services.payroll_service import PayslipService

        # Check if payslip already exists
        existing_payslip = Payslip.objects.filter(payroll_run=payroll_run).first()

        if existing_payslip:
            # Regenerate existing payslip
            generated_payslip = PayslipService.generate(
                payroll_run=payroll_run,
                generated_by=request.user,
            )
        else:
            # Create new payslip
            payslip = Payslip.objects.create(
                school=school,
                payroll_run=payroll_run,
                generated_by=request.user,
            )
            # Generate the content
            generated_payslip = PayslipService.generate(
                payroll_run=payroll_run,
                generated_by=request.user,
            )

        staff_name = payroll_run.staff.user.get_full_name()
        messages.success(request, f'Payslip generated successfully for {staff_name}.')
        return redirect('staff:payslip_detail', payslip_id=generated_payslip.id)

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to generate payslip: {str(e)}")
        messages.error(request, f"Failed to generate payslip: {str(e)}")
        return redirect('staff:payroll_period_detail', period_id=payroll_run.payroll_period.id)


# ============================================================
# LEAVE MANAGEMENT VIEWS
# ============================================================

@login_required
def leave_dashboard(request):
    """Role-aware leave dashboard: self-service for staff, administration for managers."""
    from staff.permissions import (
        can_request_own_leave, can_create_leave_for_staff, can_view_all_leave,
        can_approve_leave, is_hod, is_leave_manager,
    )

    school = getattr(request.user, "school", None)
    if not school:
        messages.error(request, "Your account is not associated with a school.")
        return redirect("dashboard:dashboard")

    try:
        staff = StaffProfile.objects.select_related("user", "department", "staff_grade").get(
            user=request.user, school=school, is_active=True
        )
    except StaffProfile.DoesNotExist:
        staff = None

    today = timezone.localdate()
    leave_types = LeaveType.objects.filter(school=school, is_active=True).order_by("category", "name")

    if can_view_all_leave(request.user):
        scope = Q(school=school)
    elif is_hod(request.user) and staff and staff.department_id:
        scope = Q(school=school, staff__department_id=staff.department_id)
    else:
        scope = Q(school=school, staff=staff) if staff else Q(pk=None)

    base = LeaveRequest.objects.filter(scope).select_related("staff__user", "staff__department", "leave_type")
    pending_requests = base.filter(status="PENDING").order_by("start_date")
    recent_requests = base.exclude(status="DRAFT").order_by("-created_at")[:10]
    total_requests = base.count()
    approved_today = base.filter(status="APPROVED", approved_at__date=today).count()
    on_leave_today = base.filter(
        status__in=["APPROVED", "TAKEN"], start_date__lte=today, end_date__gte=today
    ).order_by("staff__user__last_name")
    approved_count = base.filter(status__in=["APPROVED", "TAKEN"]).count()

    balances = []
    if staff:
        balances = StaffLeaveBalance.objects.filter(school=school, staff=staff).select_related("leave_type")

    context = {
        "leave_types": leave_types,
        "pending_requests": pending_requests,
        "recent_requests": recent_requests,
        "total_requests": total_requests,
        "approved_today": approved_today,
        "approved_count": approved_count,
        "on_leave_today": on_leave_today,
        "balances": balances,
        "staff": staff,
        "is_admin": can_view_all_leave(request.user),
        "is_leave_manager": is_leave_manager(request.user),
        "is_hod": is_hod(request.user),
        "can_request_own_leave": can_request_own_leave(request.user),
        "can_create_leave_for_staff": can_create_leave_for_staff(request.user),
        "can_approve_leave": can_approve_leave(request.user),
        "active_tab": "hr",
    }
    return render(request, "staff/leave/leave_dashboard.html", context)


@login_required
def leave_list(request):
    """Role-aware leave list with tenant and department scoping."""
    from staff.permissions import can_view_all_leave, can_approve_leave, is_hod, is_leave_manager

    school = getattr(request.user, "school", None)
    if not school:
        return JsonResponse({"success": False, "error": "School context is missing."}, status=400)

    try:
        staff = StaffProfile.objects.select_related("department").get(
            user=request.user, school=school, is_active=True
        )
    except StaffProfile.DoesNotExist:
        staff = None

    qs = LeaveRequest.objects.filter(school=school).select_related(
        "staff__user", "staff__department", "leave_type", "approved_by", "rejected_by"
    )

    if can_view_all_leave(request.user):
        pass
    elif is_hod(request.user) and staff and staff.department_id:
        qs = qs.filter(staff__department_id=staff.department_id)
    elif staff:
        qs = qs.filter(staff=staff)
    else:
        qs = qs.none()

    status_filter = request.GET.get("status", "").strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    leave_type_filter = request.GET.get("leave_type", "").strip()
    if leave_type_filter:
        qs = qs.filter(leave_type_id=leave_type_filter)

    date_from = request.GET.get("date_from", "").strip()
    if date_from:
        qs = qs.filter(end_date__gte=date_from)

    date_to = request.GET.get("date_to", "").strip()
    if date_to:
        qs = qs.filter(start_date__lte=date_to)

    search = request.GET.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(staff__user__first_name__icontains=search)
            | Q(staff__user__last_name__icontains=search)
            | Q(staff__staff_id__icontains=search)
            | Q(reason__icontains=search)
        )

    qs = qs.order_by("-created_at")
    page_obj = paginate_queryset(qs, request)
    leave_types = LeaveType.objects.filter(school=school, is_active=True).order_by("category", "name")

    context = {
        "leaves": page_obj,
        "leave_types": leave_types,
        "selected_status": status_filter,
        "selected_leave_type": leave_type_filter,
        "date_from": date_from,
        "date_to": date_to,
        "search": search,
        "is_admin": can_view_all_leave(request.user),
        "is_leave_manager": is_leave_manager(request.user),
        "is_hod": is_hod(request.user),
        "can_approve_leave": can_approve_leave(request.user),
        "active_tab": "hr",
    }
    return render(request, "staff/leave/leave_list.html", context)



@login_required
def leave_request_create(request):
    """Create a leave request for the logged-in staff member, or on behalf of staff for authorized managers."""
    from decimal import Decimal
    from datetime import datetime
    from django.db import transaction
    from staff.permissions import can_request_own_leave, can_create_leave_for_staff, is_leave_manager
    from staff.services.leave_service import get_leave_balance, get_current_leave_period, reserve_leave_days

    school = getattr(request.user, "school", None)
    if not school:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Your account is not associated with a school."}, status=400)
        messages.error(request, "Your account is not associated with a school.")
        return redirect('staff:leave_dashboard')

    can_own = can_request_own_leave(request.user)
    can_delegate = can_create_leave_for_staff(request.user)
    if not can_own and not can_delegate:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "You do not have permission to request leave."}, status=403)
        messages.error(request, "You do not have permission to request leave.")
        return redirect('staff:leave_dashboard')

    if request.method == "GET":
        leave_types = LeaveType.objects.filter(school=school, is_active=True).order_by("category", "name")
        replacement_staff = StaffProfile.objects.filter(
            school=school, is_active=True
        ).exclude(user=request.user).select_related("user", "department", "staff_grade").order_by(
            "user__last_name", "user__first_name"
        )
        staff_options = StaffProfile.objects.none()
        if can_delegate:
            staff_options = StaffProfile.objects.filter(
                school=school, is_active=True
            ).select_related("user", "department", "staff_grade").order_by(
                "user__last_name", "user__first_name"
            )
        return render(request, "staff/leave/leave_request_form_modal.html", {
            "leave_types": leave_types,
            "replacement_staff": replacement_staff,
            "staff_options": staff_options,
            "can_create_leave_for_staff": can_delegate,
            "is_admin": is_leave_manager(request.user),
            "action_url": "staff:leave_request_create",
            "mode": "create",
        })

    if request.method != "POST":
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)
        messages.error(request, "Invalid request method.")
        return redirect('staff:leave_dashboard')

    requested_staff_id = request.POST.get("staff_id", "").strip()
    if requested_staff_id and not can_delegate:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {"success": False, "error": "You cannot create leave for another staff member."},
                status=403
            )
        messages.error(request, "You cannot create leave for another staff member.")
        return redirect('staff:leave_dashboard')

    try:
        current_staff = StaffProfile.objects.select_related("user", "department", "staff_grade").get(
            user=request.user, school=school, is_active=True
        )
    except StaffProfile.DoesNotExist:
        current_staff = None

    if requested_staff_id:
        try:
            staff = StaffProfile.objects.select_related("user", "department", "staff_grade").get(
                id=requested_staff_id, school=school, is_active=True
            )
        except StaffProfile.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"success": False, "error": "Selected staff member was not found."}, status=400)
            messages.error(request, "Selected staff member was not found.")
            return redirect('staff:leave_dashboard')
    else:
        staff = current_staff

    if not staff:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {"success": False, "error": "Please select the staff member for whom the leave is being requested."},
                status=400
            )
        messages.error(request, "Please select the staff member for whom the leave is being requested.")
        return redirect('staff:leave_dashboard')

    leave_type_id = request.POST.get("leave_type", "").strip()
    start_raw = request.POST.get("start_date", "").strip()
    end_raw = request.POST.get("end_date", "").strip()
    reason = request.POST.get("reason", "").strip()
    notes = request.POST.get("notes", "").strip()
    contact_number = request.POST.get("contact_number", "").strip()
    emergency_contact = request.POST.get("emergency_contact", "").strip()
    emergency_phone = request.POST.get("emergency_phone", "").strip()
    replacement_id = request.POST.get("replacement_staff", "").strip()
    supporting_document = request.FILES.get("supporting_document")

    if not all([leave_type_id, start_raw, end_raw, reason]):
        error_msg = "Leave type, start date, end date and reason are required."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        messages.error(request, error_msg)
        return redirect('staff:leave_dashboard')

    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except ValueError:
        error_msg = "Please provide valid leave dates."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        messages.error(request, error_msg)
        return redirect('staff:leave_dashboard')

    if end_date < start_date:
        error_msg = "The end date cannot be before the start date."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        messages.error(request, error_msg)
        return redirect('staff:leave_dashboard')

    if start_date.year != end_date.year:
        error_msg = "A leave request cannot currently cross two calendar years."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        messages.error(request, error_msg)
        return redirect('staff:leave_dashboard')

    leave_type = get_object_or_404(LeaveType, id=leave_type_id, school=school, is_active=True)
    if leave_type.requires_documentation and not supporting_document:
        error_msg = f"Supporting documentation is required for {leave_type.name}."
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": error_msg}, status=400)
        messages.error(request, error_msg)
        return redirect('staff:leave_dashboard')

    replacement = None
    if replacement_id:
        replacement = get_object_or_404(StaffProfile, id=replacement_id, school=school, is_active=True)
        if replacement.id == staff.id:
            error_msg = "A staff member cannot be their own replacement."
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"success": False, "error": error_msg}, status=400)
            messages.error(request, error_msg)
            return redirect('staff:leave_dashboard')

    try:
        with transaction.atomic():
            period_start, period_end = get_current_leave_period(start_date.year)
            balance = get_leave_balance(staff, leave_type, period_start, period_end)

            overlap = LeaveRequest.objects.filter(
                school=school, staff=staff,
                start_date__lte=end_date, end_date__gte=start_date,
                status__in=["PENDING", "APPROVED", "TAKEN"],
            ).exists()
            if overlap:
                raise ValueError(
                    "This staff member already has a pending or approved leave request covering part of these dates.")

            leave = LeaveRequest.objects.create(
                school=school, staff=staff, leave_type=leave_type,
                start_date=start_date, end_date=end_date, status="PENDING",
                reason=reason, notes=notes, contact_number=contact_number,
                emergency_contact=emergency_contact, emergency_phone=emergency_phone,
                replacement_staff=replacement, supporting_document=supporting_document,
            )

            requested_days = Decimal(str(leave.requested_days or 0))
            if requested_days <= 0:
                raise ValueError("The selected leave period must contain at least one working day.")

            balance = reserve_leave_days(
                staff, leave_type, requested_days, period_start, period_end
            )

            auto_approved = not leave_type.requires_approval
            if auto_approved:
                leave.approve(request.user)

            success_msg = (
                "Leave request submitted and automatically approved."
                if auto_approved else "Leave request submitted successfully and is awaiting approval."
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    "success": True,
                    "message": success_msg,
                    "leave_id": str(leave.id),
                    "status": leave.status,
                    "status_display": leave.get_status_display(),
                    "requested_days": str(leave.requested_days),
                    "leave_type": leave_type.name,
                    "staff": staff.user.get_full_name(),
                    "created_for_another_staff": staff.id != getattr(current_staff, "id", None),
                    "balance": {
                        "entitled": str(balance.total_entitled),
                        "carried_over": str(balance.carried_over),
                        "used": str(balance.used),
                        "pending": str(balance.pending),
                        "remaining": str(balance.remaining),
                    },
                })

            messages.success(request, success_msg)
            return redirect('staff:leave_dashboard')

    except ValueError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect('staff:leave_dashboard')
    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                "success": False,
                "error": "Unable to submit the leave request.",
                "detail": str(exc),
            }, status=500)
        messages.error(request, f"Unable to submit the leave request: {str(exc)}")
        return redirect('staff:leave_dashboard')


@login_required
def leave_request_edit(request, leave_id):
    """Edit only a draft/pending request and keep the leave balance synchronized."""
    from decimal import Decimal
    from datetime import datetime
    from django.db import transaction
    from staff.permissions import can_edit_leave, is_leave_manager
    from staff.services.leave_service import get_leave_balance, get_current_leave_period, release_reserved_leave, \
        reserve_leave_days

    school = getattr(request.user, "school", None)
    leave = get_object_or_404(LeaveRequest.objects.select_related("staff", "leave_type"), id=leave_id, school=school)
    if not can_edit_leave(request.user, leave):
        return JsonResponse({"success": False, "error": "You cannot edit this leave request."}, status=403)

    if request.method == "GET":
        leave_types = LeaveType.objects.filter(school=school, is_active=True).order_by("category", "name")
        replacement_staff = StaffProfile.objects.filter(
            school=school, is_active=True
        ).exclude(id=leave.staff_id).select_related("user", "department")
        staff_options = StaffProfile.objects.filter(school=school, is_active=True).select_related("user",
                                                                                                  "department") if is_leave_manager(
            request.user) else StaffProfile.objects.none()
        return render(request, "staff/leave/leave_request_form_modal.html", {
            "leave": leave, "leave_types": leave_types, "replacement_staff": replacement_staff,
            "staff_options": staff_options, "can_create_leave_for_staff": is_leave_manager(request.user),
            "is_admin": is_leave_manager(request.user), "action_url": "staff:leave_request_edit", "mode": "edit",
        })

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)

    leave_type_id = request.POST.get("leave_type", "").strip()
    start_raw = request.POST.get("start_date", "").strip()
    end_raw = request.POST.get("end_date", "").strip()
    reason = request.POST.get("reason", "").strip()
    notes = request.POST.get("notes", "").strip()
    contact_number = request.POST.get("contact_number", "").strip()
    emergency_contact = request.POST.get("emergency_contact", "").strip()
    emergency_phone = request.POST.get("emergency_phone", "").strip()
    replacement_id = request.POST.get("replacement_staff", "").strip()
    supporting_document = request.FILES.get("supporting_document")

    if not all([leave_type_id, start_raw, end_raw, reason]):
        return JsonResponse({"success": False, "error": "Leave type, dates and reason are required."}, status=400)

    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"success": False, "error": "Please provide valid leave dates."}, status=400)
    if end_date < start_date or start_date.year != end_date.year:
        return JsonResponse(
            {"success": False, "error": "Please provide a valid leave period within one calendar year."}, status=400)

    new_type = get_object_or_404(LeaveType, id=leave_type_id, school=school, is_active=True)
    if new_type.requires_documentation and not (supporting_document or leave.supporting_document):
        return JsonResponse({"success": False, "error": f"Supporting documentation is required for {new_type.name}."},
                            status=400)

    replacement = None
    if replacement_id:
        replacement = get_object_or_404(StaffProfile, id=replacement_id, school=school, is_active=True)
        if replacement.id == leave.staff_id:
            return JsonResponse({"success": False, "error": "A staff member cannot be their own replacement."},
                                status=400)

    try:
        with transaction.atomic():
            old_type = leave.leave_type
            old_start = leave.start_date
            old_days = Decimal(str(leave.requested_days or 0))
            old_period = get_current_leave_period(old_start.year)

            if leave.status == "PENDING" and old_days > 0:
                release_reserved_leave(leave.staff, old_type, old_days, *old_period)

            leave.leave_type = new_type
            leave.start_date = start_date
            leave.end_date = end_date
            leave.reason = reason
            leave.notes = notes
            leave.contact_number = contact_number
            leave.emergency_contact = emergency_contact
            leave.emergency_phone = emergency_phone
            leave.replacement_staff = replacement
            if supporting_document:
                leave.supporting_document = supporting_document
            leave.status = "PENDING"
            leave.save()

            new_days = Decimal(str(leave.requested_days or 0))
            new_period = get_current_leave_period(start_date.year)
            balance = reserve_leave_days(leave.staff, new_type, new_days, *new_period)

        return JsonResponse(
            {"success": True, "message": "Leave request updated successfully.", "leave_id": str(leave.id)})
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"success": False, "error": "Unable to update the leave request.", "detail": str(exc)},
                            status=500)


# staff/views.py - Replace the leave approval, rejection, and cancellation views

@login_required
@require_POST
def leave_approve(request, leave_id):
    """Approve a leave request - handles both AJAX and regular form submissions."""
    from staff.permissions import can_approve_leave

    school = getattr(request.user, "school", None)
    if not school:
        messages.error(request, "Your account is not associated with a school.")
        return redirect('staff:leave_list')

    leave = get_object_or_404(
        LeaveRequest.objects.select_related("staff__user", "staff__department", "leave_type"),
        id=leave_id,
        school=school
    )

    if not can_approve_leave(request.user, leave):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {"success": False, "error": "You do not have permission to approve this leave request."}, status=403)
        messages.error(request, "You do not have permission to approve this leave request.")
        return redirect('staff:leave_detail', leave_id=leave.id)

    try:
        leave.approve(request.user, note=request.POST.get("approval_note", "").strip())

        # Check if AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                "success": True,
                "message": "Leave request approved successfully.",
                "leave_id": str(leave.id),
                "status": leave.status,
                "status_display": leave.get_status_display()
            })

        messages.success(request, "Leave request approved successfully.")

        # Redirect to the referring page or leave list
        referer = request.META.get('HTTP_REFERER')
        if referer and ('leave_detail' in referer or 'leave_dashboard' in referer or 'leave_list' in referer):
            return redirect(referer)
        return redirect('staff:leave_detail', leave_id=leave.id)

    except ValueError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect('staff:leave_detail', leave_id=leave.id)
    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Unable to approve the leave request."}, status=500)
        messages.error(request, "Unable to approve the leave request.")
        return redirect('staff:leave_detail', leave_id=leave.id)


@login_required
@require_POST
def leave_reject(request, leave_id):
    """Reject a leave request - handles both AJAX and regular form submissions."""
    from staff.permissions import can_reject_leave

    school = getattr(request.user, "school", None)
    if not school:
        messages.error(request, "Your account is not associated with a school.")
        return redirect('staff:leave_list')

    leave = get_object_or_404(
        LeaveRequest.objects.select_related("staff__user", "staff__department", "leave_type"),
        id=leave_id,
        school=school
    )

    if not can_reject_leave(request.user, leave):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "You do not have permission to reject this leave request."},
                                status=403)
        messages.error(request, "You do not have permission to reject this leave request.")
        return redirect('staff:leave_detail', leave_id=leave.id)

    reason = request.POST.get("rejection_reason", "").strip()
    if not reason:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Please provide a reason for rejection."}, status=400)
        messages.error(request, "Please provide a reason for rejection.")
        return redirect('staff:leave_detail', leave_id=leave.id)

    try:
        leave.reject(request.user, reason=reason)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                "success": True,
                "message": "Leave request rejected successfully.",
                "leave_id": str(leave.id),
                "status": leave.status,
                "status_display": leave.get_status_display()
            })

        messages.success(request, "Leave request rejected successfully.")
        referer = request.META.get('HTTP_REFERER')
        if referer and ('leave_detail' in referer or 'leave_dashboard' in referer or 'leave_list' in referer):
            return redirect(referer)
        return redirect('staff:leave_detail', leave_id=leave.id)

    except ValueError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect('staff:leave_detail', leave_id=leave.id)
    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Unable to reject the leave request."}, status=500)
        messages.error(request, "Unable to reject the leave request.")
        return redirect('staff:leave_detail', leave_id=leave.id)


@login_required
@require_POST
def leave_cancel(request, leave_id):
    """Cancel a leave request - handles both AJAX and regular form submissions."""
    from staff.permissions import can_cancel_leave

    school = getattr(request.user, "school", None)
    if not school:
        messages.error(request, "Your account is not associated with a school.")
        return redirect('staff:leave_list')

    leave = get_object_or_404(
        LeaveRequest.objects.select_related("staff__user", "staff__department", "leave_type"),
        id=leave_id,
        school=school
    )

    if not can_cancel_leave(request.user, leave):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(
                {"success": False, "error": "You can only cancel your own leave request, or a request you manage."},
                status=403)
        messages.error(request, "You can only cancel your own leave request, or a request you manage.")
        return redirect('staff:leave_detail', leave_id=leave.id)

    reason = request.POST.get("cancellation_reason", "").strip()

    try:
        leave.cancel(request.user, reason=reason)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                "success": True,
                "message": "Leave request cancelled successfully.",
                "leave_id": str(leave.id),
                "status": leave.status,
                "status_display": leave.get_status_display()
            })

        messages.success(request, "Leave request cancelled successfully.")
        referer = request.META.get('HTTP_REFERER')
        if referer and ('leave_detail' in referer or 'leave_dashboard' in referer or 'leave_list' in referer):
            return redirect(referer)
        return redirect('staff:leave_detail', leave_id=leave.id)

    except ValueError as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect('staff:leave_detail', leave_id=leave.id)
    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({"success": False, "error": "Unable to cancel the leave request."}, status=500)
        messages.error(request, "Unable to cancel the leave request.")
        return redirect('staff:leave_detail', leave_id=leave.id)


@login_required
def leave_detail(request, leave_id):
    from staff.permissions import can_view_all_leave, is_hod, can_approve_leave, can_cancel_leave, can_edit_leave
    school = getattr(request.user, "school", None)
    leave = get_object_or_404(
        LeaveRequest.objects.select_related(
            "staff__user", "staff__department", "leave_type", "approved_by", "rejected_by", "replacement_staff__user"
        ), id=leave_id, school=school
    )
    try:
        staff = StaffProfile.objects.get(user=request.user, school=school, is_active=True)
    except StaffProfile.DoesNotExist:
        staff = None

    allowed = can_view_all_leave(request.user)
    if not allowed and is_hod(request.user) and staff and staff.department_id:
        allowed = leave.staff.department_id == staff.department_id
    if not allowed and staff:
        allowed = leave.staff_id == staff.id
    if not allowed:
        messages.error(request, "You don't have permission to view this leave request.")
        return redirect("staff:leave_list")

    balance = StaffLeaveBalance.objects.filter(
        school=school, staff=leave.staff, leave_type=leave.leave_type,
        period_start__lte=leave.start_date, period_end__gte=leave.end_date
    ).first()
    return render(request, "staff/leave/leave_detail.html", {
        "leave": leave, "balance": balance,
        "is_admin": can_view_all_leave(request.user),
        "can_approve_this_leave": can_approve_leave(request.user, leave),
        "can_edit_this_leave": can_edit_leave(request.user, leave),
        "can_cancel_this_leave": can_cancel_leave(request.user, leave),
        "active_tab": "hr",
    })


# staff/views.py - Fix the leave_balance view

@login_required
def leave_balance(request):
    """View leave balance for the current user."""
    school = request.user.school

    # Get the user's staff profile
    try:
        staff = StaffProfile.objects.get(user=request.user, school=school)
    except StaffProfile.DoesNotExist:
        # If the user is not a staff member, show an error message
        messages.error(request, "Staff profile not found. Your account is not linked to a staff profile.")
        # Redirect to appropriate dashboard based on role
        if request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
            return redirect('dashboard:dashboard')
        elif request.user.role == 'TEACHER':
            return redirect('dashboard:dashboard')
        else:
            return redirect('dashboard:dashboard')

    balances = StaffLeaveBalance.objects.filter(
        school=school,
        staff=staff
    ).select_related('leave_type')

    # Get leave history
    history = LeaveRequest.objects.filter(
        school=school,
        staff=staff
    ).exclude(status='DRAFT').order_by('-created_at')[:10]

    context = {
        'balances': balances,
        'history': history,
        'staff': staff,
        'is_admin': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
        'active_tab': 'hr',
    }
    return render(request, 'staff/leave/leave_balance.html', context)


@login_required
def leave_type_list(request):
    """List all leave types (admin only)."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to view leave types.")
        # FIXED: Use correct dashboard URL name
        return redirect('dashboard:dashboard')

    school = request.user.school
    leave_types = LeaveType.objects.filter(school=school).order_by('category', 'name')

    context = {
        'leave_types': paginate_queryset(leave_types, request),
        'active_tab': 'hr',
    }
    return render(request, 'staff/leave/leave_type_list.html', context)


@login_required
def leave_type_create(request):
    """Create a new leave type (admin only)."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
        messages.error(request, "You don't have permission to create leave types.")
        return redirect('staff:leave_type_list')

    school = request.user.school

    if request.method == 'GET':
        return render(request, 'staff/leave/leave_type_form_modal.html', {
            'mode': 'create',
            'action_url': 'staff:leave_type_create'
        })

    # POST - Create leave type
    name = request.POST.get('name', '').strip()
    category = request.POST.get('category', 'ANNUAL').strip()
    default_days = request.POST.get('default_days', 21)
    allow_carryover = request.POST.get('allow_carryover') == 'on'
    max_carryover_days = request.POST.get('max_carryover_days', 30)
    requires_approval = request.POST.get('requires_approval') == 'on'
    requires_documentation = request.POST.get('requires_documentation') == 'on'
    description = request.POST.get('description', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not name:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Name is required."})
        messages.error(request, "Name is required.")
        return redirect('staff:leave_type_list')

    try:
        leave_type = LeaveType.objects.create(
            school=school,
            name=name,
            category=category,
            default_days=default_days,
            allow_carryover=allow_carryover,
            max_carryover_days=max_carryover_days,
            requires_approval=requires_approval,
            requires_documentation=requires_documentation,
            description=description,
            is_active=is_active,
        )

        # Check if AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f"Leave type '{name}' created successfully with code '{leave_type.code}'.",
                'code': leave_type.code
            })

        # Regular form submission - redirect with success message
        messages.success(request, f"Leave type '{name}' created successfully with code '{leave_type.code}'.")
        return redirect('staff:leave_type_list')

    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        messages.error(request, f"Error creating leave type: {str(e)}")
        return redirect('staff:leave_type_list')


@login_required
def leave_type_edit(request, leave_type_id):
    """Edit an existing leave type (admin only)."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
        messages.error(request, "You don't have permission to edit leave types.")
        return redirect('staff:leave_type_list')

    school = request.user.school
    leave_type = get_object_or_404(LeaveType, id=leave_type_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/leave/leave_type_form_modal.html', {
            'mode': 'edit',
            'leave_type': leave_type,
            'action_url': 'staff:leave_type_edit'
        })

    # POST - Update leave type
    name = request.POST.get('name', '').strip()
    category = request.POST.get('category', 'ANNUAL').strip()
    default_days = request.POST.get('default_days', 21)
    allow_carryover = request.POST.get('allow_carryover') == 'on'
    max_carryover_days = request.POST.get('max_carryover_days', 30)
    requires_approval = request.POST.get('requires_approval') == 'on'
    requires_documentation = request.POST.get('requires_documentation') == 'on'
    description = request.POST.get('description', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not name:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Name is required."})
        messages.error(request, "Name is required.")
        return redirect('staff:leave_type_list')

    try:
        leave_type.name = name
        leave_type.category = category
        leave_type.default_days = default_days
        leave_type.allow_carryover = allow_carryover
        leave_type.max_carryover_days = max_carryover_days
        leave_type.requires_approval = requires_approval
        leave_type.requires_documentation = requires_documentation
        leave_type.description = description
        leave_type.is_active = is_active
        leave_type.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f"Leave type '{name}' updated successfully."
            })

        messages.success(request, f"Leave type '{name}' updated successfully.")
        return redirect('staff:leave_type_list')

    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        messages.error(request, f"Error updating leave type: {str(e)}")
        return redirect('staff:leave_type_list')


@login_required
def leave_type_toggle_active(request, leave_type_id):
    """Toggle active status for a leave type (admin only)."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
        messages.error(request, "You don't have permission to toggle leave types.")
        return redirect('staff:leave_type_list')

    school = request.user.school
    leave_type = get_object_or_404(LeaveType, id=leave_type_id, school=school)

    if request.method == 'GET':
        return render(request, 'staff/leave/leave_type_toggle_modal.html', {
            'leave_type': leave_type,
            'action_url': 'staff:leave_type_toggle_active'
        })

    try:
        # Toggle the active status
        leave_type.is_active = not leave_type.is_active
        leave_type.save()

        status_text = "activated" if leave_type.is_active else "deactivated"

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f"Leave type '{leave_type.name}' {status_text} successfully.",
                'is_active': leave_type.is_active
            })

        messages.success(request, f"Leave type '{leave_type.name}' {status_text} successfully.")
        return redirect('staff:leave_type_list')

    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)})
        messages.error(request, f"Error toggling leave type: {str(e)}")
        return redirect('staff:leave_type_list')


# ============================================================
# LEAVE CALENDAR VIEWS
# ============================================================

# staff/views.py - Fix the leave_calendar view

@login_required
def leave_calendar(request):
    """View leave calendar."""
    school = request.user.school

    try:
        staff = StaffProfile.objects.get(user=request.user)
    except StaffProfile.DoesNotExist:
        staff = None

    # Get date range from request with proper error handling
    today = timezone.now().date()

    try:
        year = int(request.GET.get('year', today.year))
    except (ValueError, TypeError):
        year = today.year

    try:
        month = int(request.GET.get('month', today.month))
    except (ValueError, TypeError):
        month = today.month

    # Validate month range
    if month < 1:
        month = 1
    elif month > 12:
        month = 12

    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    # Calculate previous and next month/year for navigation
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year

    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year

    # Get calendar events
    from staff.services.leave_service import get_leave_calendar_events

    if request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        events = get_leave_calendar_events(
            school=school,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        from staff.services.leave_service import get_leave_calendar_events_for_staff
        events = get_leave_calendar_events_for_staff(staff, start_date, end_date)

    # Build calendar weeks
    import calendar as cal_module
    cal = cal_module.Calendar(firstweekday=6)  # Sunday first
    month_days = cal.monthdayscalendar(year, month)

    calendar_weeks = []
    for week in month_days:
        week_days = []
        for day in week:
            if day == 0:
                week_days.append({
                    'day': None,
                    'today': False,
                    'weekend': False,
                    'has_events': False,
                    'event_count': 0,
                    'events': []
                })
            else:
                current_date = date(year, month, day)
                day_events = [e for e in events if e.start_date <= current_date <= e.end_date]
                is_today = current_date == today
                is_weekend = current_date.weekday() >= 5

                week_days.append({
                    'day': day,
                    'today': is_today,
                    'weekend': is_weekend,
                    'has_events': len(day_events) > 0,
                    'event_count': len(day_events),
                    'events': day_events
                })
        calendar_weeks.append(week_days)

    # Month name
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    month_name = month_names[month - 1]

    context = {
        'events': events,
        'year': year,
        'month': month,
        'month_name': month_name,
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month,
        'now': today,
        'calendar_weeks': calendar_weeks,
        'start_date': start_date,
        'end_date': end_date,
        'staff': staff,
        'is_admin': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
        'active_tab': 'hr',
    }
    return render(request, 'staff/leave/leave_calendar.html', context)


# ============================================================
# LEAVE ANALYTICS VIEWS
# ============================================================

@login_required
def leave_analytics(request):
    """View leave analytics dashboard."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to view leave analytics.")
        return redirect('dashboard')

    school = request.user.school

    # Generate analytics for the current year
    from staff.services.leave_service import generate_leave_analytics

    # Yearly analytics
    yearly = generate_leave_analytics(school, 'YEAR')

    # Quarterly analytics
    quarterly = []
    for q in range(1, 5):
        analytics = generate_leave_analytics(school, 'QUARTER', quarter=q)
        quarterly.append(analytics)

    # Monthly analytics for current year
    monthly = []
    for m in range(1, 13):
        analytics = generate_leave_analytics(school, 'MONTH', month=m)
        monthly.append(analytics)

    context = {
        'yearly': yearly,
        'quarterly': quarterly,
        'monthly': monthly,
        'active_tab': 'hr',
    }
    return render(request, 'staff/leave/leave_analytics.html', context)


# ============================================================
# LEAVE LEDGER VIEWS
# ============================================================

@login_required
def leave_ledger(request, staff_id=None):
    """View leave ledger for a staff member."""
    school = request.user.school

    if staff_id:
        if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
            messages.error(request, "You don't have permission to view other staff's ledger.")
            return redirect('staff:leave_ledger')

        staff = get_object_or_404(StaffProfile, id=staff_id, school=school)
    else:
        staff = get_object_or_404(StaffProfile, user=request.user, school=school)

    ledger_entries = LeaveLedger.objects.filter(
        school=school,
        staff=staff
    ).select_related('leave_type', 'performed_by').order_by('-created_at')

    context = {
        'staff': staff,
        'ledger_entries': ledger_entries,
        'active_tab': 'hr',
    }
    return render(request, 'staff/leave/leave_ledger.html', context)


# ============================================================
# LEAVE TYPE MANAGEMENT - ENHANCED
# ============================================================

@login_required
def leave_type_grade_policies(request):
    """Manage leave policies by grade."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to manage leave policies.")
        return redirect('dashboard')

    school = request.user.school
    grades = StaffGrade.objects.filter(school=school, is_active=True)
    leave_types = LeaveType.objects.filter(school=school, is_active=True)

    # Get existing policies
    policies = StaffGradeLeavePolicy.objects.filter(
        school=school,
        staff_grade__in=grades,
        leave_type__in=leave_types,
    ).select_related('staff_grade', 'leave_type')

    # Build policy matrix
    policy_matrix = {}
    for grade in grades:
        policy_matrix[grade.id] = {}
        for leave_type in leave_types:
            policy = policies.filter(staff_grade=grade, leave_type=leave_type).first()
            policy_matrix[grade.id][leave_type.id] = policy

    context = {
        'grades': grades,
        'leave_types': leave_types,
        'policy_matrix': policy_matrix,
        'active_tab': 'hr',
    }
    return render(request, 'staff/leave/leave_type_grade_policies.html', context)


@login_required
@require_POST
def leave_type_grade_policy_save(request):
    """Save a grade-level leave policy."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    grade_id = request.POST.get('grade_id')
    leave_type_id = request.POST.get('leave_type_id')
    entitlement_days = request.POST.get('entitlement_days')
    is_paid = request.POST.get('is_paid') == 'on'
    allow_carryover = request.POST.get('allow_carryover') == 'on'
    max_carryover_days = request.POST.get('max_carryover_days', 0)
    is_active = request.POST.get('is_active') == 'on'

    if not all([grade_id, leave_type_id, entitlement_days]):
        return JsonResponse({'success': False, 'error': "All fields are required."})

    try:
        grade = get_object_or_404(StaffGrade, id=grade_id, school=school)
        leave_type = get_object_or_404(LeaveType, id=leave_type_id, school=school)

        policy, created = StaffGradeLeavePolicy.objects.update_or_create(
            school=school,
            staff_grade=grade,
            leave_type=leave_type,
            defaults={
                'entitlement_days': entitlement_days,
                'is_paid': is_paid,
                'allow_carryover': allow_carryover,
                'max_carryover_days': max_carryover_days,
                'is_active': is_active,
            }
        )

        return JsonResponse({
            'success': True,
            'message': "Leave policy saved successfully.",
            'created': created,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ============================================================
# API ENDPOINTS
# ============================================================

@login_required
@require_POST
def staff_mark_password_changed(request):
    try:
        staff = get_object_or_404(StaffProfile, user=request.user)
        staff.has_changed_password = True
        staff.password_changed_at = timezone.now()
        staff.save(update_fields=['has_changed_password', 'password_changed_at'])
        return JsonResponse({'success': True, 'message': 'Password change tracked.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def staff_get_credentials(request, staff_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    staff = get_object_or_404(StaffProfile, id=staff_id, school=school)

    data = {
        'username': staff.user.username,
        'has_changed_password': staff.has_changed_password,
        'default_password': staff.default_password if not staff.has_changed_password else None,
    }
    return JsonResponse({'success': True, 'data': data})
