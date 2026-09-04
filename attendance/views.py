# attendance/views.py

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.dateparse import parse_date
from django.utils.timezone import localdate
from django.views.decorators.http import require_POST

from students.models import Student
from academics.models import SchoolClass
from staff.models import Teacher

from .models import Attendance
from .face_service import FaceRecognitionService


# ============================================================
# ROLE CONFIGURATION
# ============================================================

ADMIN_ROLES = {
    "SUPER_ADMIN",
    "SCHOOL_ADMIN",
    "ADMIN",
}


# ============================================================
# SCHOOL / USER HELPERS
# ============================================================

def get_user_school(request):
    """
    Return the school belonging to the logged-in user.
    """
    return getattr(request.user, "school", None)


def get_user_role(user):
    """
    Safely return the normalized user role.
    """
    role = getattr(user, "role", None)

    if not role:
        return ""

    return str(role).strip().upper()


def is_admin_user(user):
    """
    Administrators have school-wide attendance access.
    """
    return (
        bool(getattr(user, "is_superuser", False))
        or get_user_role(user) in ADMIN_ROLES
    )


def is_teacher_user(user):
    """
    Only users whose actual account role is TEACHER
    can use classroom-teacher attendance access.
    """
    return get_user_role(user) == "TEACHER"


def get_teacher_profile(user):
    """
    Return the active Teacher profile for the logged-in user.
    """
    try:
        return (
            Teacher.objects
            .select_related("user", "school")
            .get(
                user=user,
                is_active=True,
            )
        )
    except Teacher.DoesNotExist:
        return None


# ============================================================
# CLASS TEACHER ACCESS
# ============================================================

def get_class_teacher_class_ids(user, school):
    """
    Return ONLY the classrooms for which this teacher is the
    classroom / homeroom / class teacher.

    IMPORTANT:

    This function deliberately DOES NOT use:

        - TeacherAssignment
        - subject assignments
        - timetable entries
        - subject rosters

    Attendance is based ONLY on the teacher's classroom
    assignment.

    The project uses Teacher.homerooms for classroom scope.
    A defensive TeacherClassAssignment fallback is included
    so older assignment records can still work.
    """

    empty_queryset = (
        SchoolClass.objects
        .none()
        .values_list("id", flat=True)
    )

    if not school:
        return empty_queryset

    # Only actual TEACHER users can receive classroom access.
    if not is_teacher_user(user):
        return empty_queryset

    teacher = get_teacher_profile(user)

    if not teacher:
        return empty_queryset

    class_ids = set()

    # --------------------------------------------------------
    # PRIMARY SOURCE:
    # Teacher.homerooms
    #
    # This is the classroom/class-teacher relationship.
    # --------------------------------------------------------

    try:
        homerooms = getattr(teacher, "homerooms", None)

        if homerooms is not None:
            homeroom_ids = (
                homerooms
                .filter(
                    school=school,
                )
                .values_list(
                    "id",
                    flat=True,
                )
            )

            class_ids.update(homeroom_ids)

    except Exception:
        pass

    # --------------------------------------------------------
    # FALLBACK:
    # TeacherClassAssignment
    #
    # This is ONLY used as a classroom assignment source.
    # We never use TeacherAssignment here.
    # --------------------------------------------------------

    if not class_ids:
        try:
            from academics.models import TeacherClassAssignment

            fallback_ids = (
                TeacherClassAssignment.objects
                .filter(
                    school=school,
                    teacher=teacher,
                    is_active=True,
                    school_class__school=school,
                )
                .values_list(
                    "school_class_id",
                    flat=True,
                )
            )

            class_ids.update(fallback_ids)

        except Exception:
            pass

    if not class_ids:
        return empty_queryset

    return (
        SchoolClass.objects
        .filter(
            school=school,
            id__in=class_ids,
        )
        .values_list(
            "id",
            flat=True,
        )
    )


def get_class_teacher_classes(user, school):
    """
    Return the actual SchoolClass queryset assigned to the
    teacher as classroom teacher.

    This is useful for displaying the teacher's assigned
    classroom(s) in the tracker.
    """

    class_ids = get_class_teacher_class_ids(
        user,
        school,
    )

    return (
        SchoolClass.objects
        .filter(
            school=school,
            id__in=class_ids,
        )
        .order_by(
            "name",
        )
    )


def teacher_can_access_student(user, student, school):
    """
    Server-side attendance authorization.

    ADMIN:
        Can access any active student in their school.

    TEACHER:
        Can access a student ONLY when that student's
        school_class is one of the teacher's assigned
        classroom/homeroom classes.

    SUBJECT ASSIGNMENTS ARE NOT USED.
    """

    if not school or not student:
        return False

    # Tenant boundary.
    if student.school_id != school.id:
        return False

    # School administrators have school-wide access.
    if is_admin_user(user):
        return True

    # Everyone else must be a classroom teacher.
    if not is_teacher_user(user):
        return False

    # Student must belong to a classroom.
    if not student.school_class_id:
        return False

    class_ids = get_class_teacher_class_ids(
        user,
        school,
    )

    return class_ids.filter(
        pk=student.school_class_id
    ).exists()


def get_attendance_students(user, school):
    """
    Return the attendance roster for the current user.

    ADMIN:
        All active students in the school.

    CLASS TEACHER:
        All active students belonging to the teacher's
        assigned classroom(s).

    IMPORTANT:
        No subject roster is involved.
    """

    if not school:
        return Student.objects.none()

    base_queryset = (
        Student.objects
        .filter(
            school=school,
            is_active=True,
        )
        .select_related(
            "user",
            "grade_level",
            "school_class",
        )
        .order_by(
            "school_class__name",
            "user__last_name",
            "user__first_name",
        )
    )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if is_admin_user(user):
        return base_queryset

    # --------------------------------------------------------
    # CLASSROOM TEACHER
    # --------------------------------------------------------

    if is_teacher_user(user):
        class_ids = get_class_teacher_class_ids(
            user,
            school,
        )

        return base_queryset.filter(
            school_class_id__in=class_ids
        )

    # --------------------------------------------------------
    # NO ATTENDANCE ACCESS
    # --------------------------------------------------------

    return Student.objects.none()


# ============================================================
# DATE HELPER
# ============================================================

def get_attendance_date(request):
    """
    Safely resolve the requested attendance date.
    """
    date_str = request.GET.get("date") or request.POST.get("date")

    if not date_str:
        return localdate()

    parsed = parse_date(date_str)

    return parsed or localdate()


# ============================================================
# ATTENDANCE TRACKER
# ============================================================

@login_required
def attendance_tracker(request):
    """
    Daily classroom attendance tracker.

    CLASS TEACHER:
        Sees all active students in assigned classroom(s).

    ADMIN:
        Sees all active students in the school.

    SUBJECT TEACHERS:
        Do NOT receive attendance students simply because
        they teach a subject to that class.
    """

    school = get_user_school(request)

    # --------------------------------------------------------
    # NO SCHOOL
    # --------------------------------------------------------

    if not school:
        return render(
            request,
            "attendance/tracker.html",
            {
                "students": Student.objects.none(),
                "selected_date": localdate(),
                "has_face_recognition": False,
                "is_teacher": False,
                "is_class_teacher": False,
                "is_admin": False,
                "assigned_classes": SchoolClass.objects.none(),
                "attendance_access_error": (
                    "Your account is not associated with a school."
                ),
            },
        )

    # --------------------------------------------------------
    # ROLE ACCESS
    # --------------------------------------------------------

    is_admin = is_admin_user(
        request.user
    )

    is_teacher = is_teacher_user(
        request.user
    )

    # A teacher is considered a valid attendance teacher only
    # if they actually have classroom assignments.
    assigned_classes = (
        get_class_teacher_classes(
            request.user,
            school,
        )
        if is_teacher
        else SchoolClass.objects.none()
    )

    is_class_teacher = (
        is_teacher
        and assigned_classes.exists()
    )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    selected_date = get_attendance_date(
        request
    )

    # --------------------------------------------------------
    # STUDENTS
    # --------------------------------------------------------

    students_queryset = get_attendance_students(
        request.user,
        school,
    )

    students = list(
        students_queryset
    )

    # --------------------------------------------------------
    # ATTENDANCE MAP
    # --------------------------------------------------------

    student_ids = [
        student.id
        for student in students
    ]

    attendance_map = {}

    if student_ids:
        attendance_map = dict(
            Attendance.objects
            .filter(
                school=school,
                date=selected_date,
                student_id__in=student_ids,
            )
            .values_list(
                "student_id",
                "status",
            )
        )

    for student in students:
        student.current_attendance_status = (
            attendance_map.get(
                student.id,
                "UNMARKED",
            )
        )

    # --------------------------------------------------------
    # ACCESS MESSAGE
    # --------------------------------------------------------

    attendance_access_error = None

    if is_teacher and not is_class_teacher:
        attendance_access_error = (
            "You are registered as a teacher, but you are not "
            "currently assigned as a classroom teacher. "
            "Attendance access is available only to assigned "
            "classroom teachers."
        )

    elif not is_admin and not is_teacher:
        attendance_access_error = (
            "You do not have permission to take classroom attendance."
        )

    # --------------------------------------------------------
    # CONTEXT
    # --------------------------------------------------------

    context = {
        "students": students,
        "selected_date": selected_date,

        "has_face_recognition": any(
            bool(
                getattr(
                    student,
                    "face_registered",
                    False,
                )
            )
            for student in students
        ),

        "is_teacher": is_teacher,
        "is_class_teacher": is_class_teacher,
        "is_admin": is_admin,

        "assigned_classes": assigned_classes,

        "attendance_access_error": attendance_access_error,
    }

    return render(
        request,
        "attendance/tracker.html",
        context,
    )


# ============================================================
# MANUAL ATTENDANCE
# ============================================================

@login_required
@require_POST
def api_toggle_attendance(request):
    """
    Create or update attendance for one student.

    Authorization is always performed on the server.

    A classroom teacher can only mark attendance for students
    belonging to their assigned classroom.
    """

    try:
        data = json.loads(
            request.body or "{}"
        )

    except (json.JSONDecodeError, TypeError):
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid JSON data.",
            },
            status=400,
        )

    student_id = data.get(
        "student_id"
    )

    status = data.get(
        "status"
    )

    date_str = data.get(
        "date"
    )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not student_id or not status:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Missing required parameters."
                ),
            },
            status=400,
        )

    status = str(
        status
    ).strip().upper()

    allowed_statuses = {
        "PRESENT",
        "LATE",
        "ABSENT",
    }

    if status not in allowed_statuses:
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid attendance status.",
            },
            status=400,
        )

    # --------------------------------------------------------
    # SCHOOL
    # --------------------------------------------------------

    school = get_user_school(
        request
    )

    if not school:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Your account is not associated with a school."
                ),
            },
            status=403,
        )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    target_date = (
        parse_date(date_str)
        if date_str
        else localdate()
    )

    if not target_date:
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid attendance date.",
            },
            status=400,
        )

    # --------------------------------------------------------
    # STUDENT
    # --------------------------------------------------------

    student = get_object_or_404(
        Student.objects.select_related(
            "user",
            "school_class",
            "grade_level",
        ),
        id=student_id,
        school=school,
        is_active=True,
    )

    # --------------------------------------------------------
    # CRITICAL SECURITY CHECK
    # --------------------------------------------------------

    if not teacher_can_access_student(
        request.user,
        student,
        school,
    ):
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "You are not authorized to mark attendance "
                    "for this student. Attendance is restricted "
                    "to the student's assigned classroom teacher."
                ),
            },
            status=403,
        )

    # --------------------------------------------------------
    # STUDENT NAME
    # --------------------------------------------------------

    full_name = ""

    if getattr(student, "user", None):
        full_name = (
            student.user
            .get_full_name()
            .strip()
        )

    if not full_name:
        full_name = (
            getattr(
                student,
                "admission_number",
                None,
            )
            or "Student"
        )

    # --------------------------------------------------------
    # SAVE ATTENDANCE
    # --------------------------------------------------------

    attendance, created = (
        Attendance.objects.update_or_create(
            school=school,
            student=student,
            date=target_date,
            defaults={
                "status": status,
                "marked_by": request.user,
                "remarks": (
                    f"Marked manually by "
                    f"{request.user.get_full_name() or request.user.username}"
                ),
            },
        )
    )

    return JsonResponse(
        {
            "success": True,
            "status": attendance.status,
            "student_id": str(student.id),
            "student_name": full_name,
            "created": created,
            "date": target_date.isoformat(),
        }
    )


# ============================================================
# FACE CAPTURE ATTENDANCE
# ============================================================

@login_required
@require_POST
def api_capture_attendance(request):
    """
    Capture attendance using facial recognition.

    The face service receives the logged-in user so the service
    can apply its own authorization.

    The tracker itself remains restricted to classroom teachers.
    """

    try:
        data = json.loads(
            request.body or "{}"
        )

    except (json.JSONDecodeError, TypeError):
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid JSON data.",
            },
            status=400,
        )

    # --------------------------------------------------------
    # ACCESS
    # --------------------------------------------------------

    school = get_user_school(
        request
    )

    if not school:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Your account is not associated with a school."
                ),
            },
            status=403,
        )

    # Teachers must actually have a classroom assignment.
    if not is_admin_user(
        request.user
    ):
        if not is_teacher_user(
            request.user
        ):
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Only classroom teachers can use "
                        "attendance face scanning."
                    ),
                },
                status=403,
            )

        if not get_class_teacher_class_ids(
            request.user,
            school,
        ).exists():
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "You are not assigned as a classroom "
                        "teacher and cannot take attendance."
                    ),
                },
                status=403,
            )

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image_data = data.get(
        "image"
    )

    if not image_data:
        return JsonResponse(
            {
                "success": False,
                "error": "No image provided.",
            },
            status=400,
        )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    date_str = data.get(
        "date"
    )

    target_date = (
        parse_date(date_str)
        if date_str
        else localdate()
    )

    if not target_date:
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid attendance date.",
            },
            status=400,
        )

    # --------------------------------------------------------
    # FACE SERVICE
    # --------------------------------------------------------

    try:
        service_result = (
            FaceRecognitionService
            .capture_attendance_from_frame(
                image_data=image_data,
                school_id=school.id,
                date=target_date,
                user=request.user,
            )
        )

        # capture_attendance_from_frame() returns a wrapper dict:
        #   {"success": bool, "students": {...}, "recognized_students": int, ...}
        # Make sure we always have that shape before reading it, in
        # case the service ever returns None/unexpected data.
        if not isinstance(service_result, dict):
            service_result = {}

        if not service_result.get("success", True):
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        service_result.get("error")
                        or service_result.get("message")
                        or "Face recognition failed."
                    ),
                },
                status=400,
            )

        # This is the actual per-student dict, keyed by student id —
        # NOT the wrapper. Sending the wrapper itself here was the
        # bug: the browser ended up with data.students.students
        # instead of data.students, so every recognized entry
        # rendered as "Unknown Student" with no class.
        students = service_result.get("students") or {}

        return JsonResponse(
            {
                "success": True,
                "recognized_students": len(students),
                "students": students,
                "date": target_date.isoformat(),
            }
        )

    except Exception as exc:
        print(
            "Error in api_capture_attendance:",
            exc,
        )

        return JsonResponse(
            {
                "success": False,
                "error": str(exc),
            },
            status=400,
        )


# ============================================================
# FACE REGISTRATION
# ============================================================

@login_required
@require_POST
def api_register_face(request):
    """
    Register a student's face.

    Only:
        - administrators
        - classroom teachers assigned to the student's class

    can register a face.
    """

    try:
        data = json.loads(
            request.body or "{}"
        )

    except (json.JSONDecodeError, TypeError):
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid JSON data.",
            },
            status=400,
        )

    student_id = data.get(
        "student_id"
    )

    image_data = data.get(
        "image"
    )

    if not student_id or not image_data:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Missing required parameters."
                ),
            },
            status=400,
        )

    school = get_user_school(
        request
    )

    if not school:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Your account is not associated with a school."
                ),
            },
            status=403,
        )

    student = get_object_or_404(
        Student.objects.select_related(
            "user",
            "school_class",
            "grade_level",
        ),
        id=student_id,
        school=school,
        is_active=True,
    )

    # --------------------------------------------------------
    # SECURITY
    # --------------------------------------------------------

    if not teacher_can_access_student(
        request.user,
        student,
        school,
    ):
        return JsonResponse(
            {
                "success": False,
                "message": (
                    "You are not authorized to register "
                    "a face for this student."
                ),
            },
            status=403,
        )

    # --------------------------------------------------------
    # REGISTER
    # --------------------------------------------------------

    try:
        (
            success,
            message,
            encoding,
        ) = (
            FaceRecognitionService
            .register_student_face(
                student=student,
                image_data=image_data,
                registered_by=request.user,
            )
        )

        return JsonResponse(
            {
                "success": success,
                "message": message,
                "face_registered": success,
            }
        )

    except Exception as exc:
        print(
            "Error in api_register_face:",
            exc,
        )

        return JsonResponse(
            {
                "success": False,
                "message": str(exc),
            },
            status=400,
        )


# ============================================================
# LIVE CAPTURE
# ============================================================

@login_required
@require_POST
def api_live_capture(request):
    """
    Placeholder endpoint for live camera capture.
    """

    school = get_user_school(
        request
    )

    if not school:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Your account is not associated with a school."
                ),
            },
            status=403,
        )

    if not is_admin_user(
        request.user
    ):
        if not is_teacher_user(
            request.user
        ):
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Only classroom teachers can "
                        "use live attendance capture."
                    ),
                },
                status=403,
            )

        if not get_class_teacher_class_ids(
            request.user,
            school,
        ).exists():
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "You are not assigned as a classroom teacher."
                    ),
                },
                status=403,
            )

    return JsonResponse(
        {
            "success": True,
            "message": (
                "Live capture endpoint ready."
            ),
        }
    )