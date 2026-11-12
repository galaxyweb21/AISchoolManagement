from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.pagination import paginate_queryset
from staff.models import StaffProfile

from .face_service import FACE_RECOGNITION_AVAILABLE, FaceRecognitionService
from .models import Attendance, StaffAttendance, StaffFaceProfile, StaffAttendanceSettings
from .staff_face_utils import DuplicateStaffFaceError, find_duplicate_staff_face, save_staff_face
from .forms import StaffAttendanceSettingsForm


STAFF_ATTENDANCE_ROLES = {"SUPER_ADMIN", "SCHOOL_ADMIN", "ADMIN", "BURSAR", "HOD", "ATTENDANCE_OFFICER"}


def _role(user):
    return str(getattr(user, "role", "") or "").strip().upper()


def _school(request):
    return getattr(request.user, "school", None)


def _can_manage(user):
    return bool(getattr(user, "is_superuser", False)) or _role(user) in STAFF_ATTENDANCE_ROLES


def _staff_queryset(school):
    return (
        StaffProfile.objects
        .filter(school=school, is_active=True)
        .select_related("user", "department", "staff_grade")
        .order_by("user__last_name", "user__first_name", "staff_id")
    )


def _staff_name(staff):
    name = staff.user.get_full_name().strip() if getattr(staff, "user", None) else ""
    return name or staff.staff_id


def _attendance_date(request):
    value = request.GET.get("date") or request.POST.get("date")
    return parse_date(value) if value else timezone.localdate()



def _json_or_form_data(request):
    """Read JSON requests and normal HTML form submissions safely."""
    if request.content_type and "application/json" in request.content_type.lower():
        try:
            import json
            return json.loads(request.body.decode("utf-8") or "{}"), None
        except (TypeError, ValueError, UnicodeDecodeError):
            return None, JsonResponse({"success": False, "error": "Invalid JSON data."}, status=400)
    return request.POST, None


def _valid_target_date(value):
    return parse_date(str(value or "")) or timezone.localdate()


def _attendance_conflict(record):
    return JsonResponse({
        "success": False,
        "already_marked": True,
        "error": (
            f"Attendance has already been recorded for this staff member "
            f"({record.get_status_display()}). Further attendance marking is disabled."
        ),
        "status": record.status,
        "check_in": record.check_in.isoformat() if record.check_in else None,
        "check_out": record.check_out.isoformat() if record.check_out else None,
    }, status=409)


def _attendance_policy_error(school, user, target_date, status=None, checkout=False):
    """Enforce configured hours for attendance officers; admins retain override ability."""
    role = _role(user)
    if getattr(user, 'is_superuser', False) or role in {'SUPER_ADMIN', 'SCHOOL_ADMIN'}:
        return None
    settings_obj = StaffAttendanceSettings.objects.filter(school=school).first()
    if not settings_obj or not settings_obj.enforce_time_windows:
        return None
    if target_date != timezone.localdate():
        return 'Attendance officers can only mark attendance for today. Ask a school administrator to correct a past date.'
    now_time = timezone.localtime().time().replace(tzinfo=None)
    if checkout:
        if now_time < settings_obj.school_end:
            return 'Staff sign-out is available from the configured school closing time.'
        return None
    if status in {'PRESENT', 'LATE'}:
        if not (settings_obj.check_in_start <= now_time <= settings_obj.check_in_end):
            return 'Check-in is closed. Attendance officers can mark Present/Late only during the configured check-in window.'
    elif status in {'ABSENT', 'EXCUSED'}:
        if now_time <= settings_obj.check_in_end:
            return 'Absent/Excused marking becomes available after the check-in window closes.'
    return None



@login_required
def face_attendance_kiosk(request):
    """Shared camera interface with independent student and staff attendance records."""
    role = _role(request.user)
    if not (getattr(request.user, "is_superuser", False) or role in {"SUPER_ADMIN", "SCHOOL_ADMIN", "ADMIN"}):
        return HttpResponseForbidden("The unified face attendance kiosk is available to school administrators only.")
    school = _school(request)
    if not school:
        messages.error(request, "Your account is not associated with a school.")
        return redirect("dashboard")
    selected_date = timezone.localdate()
    # Hydrate the kiosk from the database so its totals and recent records
    # survive refreshes and are not merely counts held in browser memory.
    student_records = list(
        Attendance.objects.filter(school=school, date=selected_date)
        .select_related("student__user", "student__school_class")
        .order_by("student__user__last_name", "student__user__first_name")
    )
    staff_records = list(
        StaffAttendance.objects.filter(school=school, date=selected_date)
        .select_related("staff__user")
        .order_by("staff__user__last_name", "staff__user__first_name")
    )
    initial_students = [{
        "id": str(record.student_id),
        "name": record.student.user.get_full_name().strip() or record.student.admission_number,
        "meta": "{} · {}".format(
            getattr(record.student.school_class, "name", "Class not recorded") or "Class not recorded",
            record.student.admission_number,
        ),
        "status": record.status,
        "created": False,
    } for record in student_records]
    initial_staff = [{
        "id": str(record.staff_id),
        "name": _staff_name(record.staff),
        "meta": record.staff.staff_id or "",
        "status": record.status,
        "created": False,
    } for record in staff_records]
    return render(request, "attendance/face_attendance_kiosk.html", {
        "selected_date": selected_date,
        "face_recognition_available": FACE_RECOGNITION_AVAILABLE,
        "student_capture_url_name": "attendance:api_capture_attendance",
        "staff_capture_url_name": "attendance:api_staff_live_capture",
        "initial_students": initial_students,
        "initial_staff": initial_staff,
        "student_saved_count": len(student_records),
        "staff_saved_count": len(staff_records),
    })

@login_required
def staff_attendance_settings(request):
    if _role(request.user) not in {'SUPER_ADMIN', 'SCHOOL_ADMIN'} and not getattr(request.user, 'is_superuser', False):
        return HttpResponseForbidden('Only school administrators can configure staff attendance hours.')
    school = _school(request)
    if not school:
        messages.error(request, 'Your account is not associated with a school.')
        return redirect('dashboard')
    settings_obj, _ = StaffAttendanceSettings.objects.get_or_create(school=school)
    if request.method == 'POST':
        form = StaffAttendanceSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Staff attendance hours saved.')
            return redirect('attendance:staff_attendance_settings')
    else:
        form = StaffAttendanceSettingsForm(instance=settings_obj)
    return render(request, 'attendance/staff_attendance_settings.html', {'form': form, 'settings_obj': settings_obj})


@login_required
def staff_attendance_self_service(request):
    """Allow staff to view today's own record and sign out without seeing others."""
    school = _school(request)
    if not school:
        messages.error(request, 'Your account is not associated with a school.')
        return redirect('dashboard')
    staff = StaffProfile.objects.filter(user=request.user, school=school, is_active=True).select_related('user').first()
    if not staff:
        return HttpResponseForbidden('Your account does not have an active staff profile.')
    today = timezone.localdate()
    record = StaffAttendance.objects.filter(school=school, staff=staff, date=today).first()
    settings_obj = StaffAttendanceSettings.objects.filter(school=school).first()
    return render(request, 'attendance/staff_attendance_self_service.html', {
        'staff_member': staff,
        'record': record,
        'today': today,
        'settings_obj': settings_obj,
    })


@login_required
@require_POST
def api_staff_self_checkout(request):
    school = _school(request)
    if not school:
        return JsonResponse({'success': False, 'error': 'Your account is not associated with a school.'}, status=403)
    staff = StaffProfile.objects.filter(user=request.user, school=school, is_active=True).first()
    if not staff:
        return JsonResponse({'success': False, 'error': 'Your account does not have an active staff profile.'}, status=403)
    today = timezone.localdate()
    policy_error = _attendance_policy_error(school, request.user, today, checkout=True)
    if policy_error:
        return JsonResponse({'success': False, 'error': policy_error}, status=403)
    with transaction.atomic():
        record = StaffAttendance.objects.select_for_update().filter(
            school=school, staff=staff, date=today
        ).first()
        if not record:
            return JsonResponse({'success': False, 'error': 'Your attendance has not been recorded today. Please contact the attendance officer.'}, status=400)
        if record.status not in {'PRESENT', 'LATE'}:
            return JsonResponse({'success': False, 'error': 'Only staff marked Present or Late can sign out.'}, status=400)
        if record.check_out:
            return JsonResponse({'success': False, 'already_checked_out': True, 'error': 'You have already signed out today.', 'check_out': record.check_out.isoformat()}, status=409)
        record.check_out = timezone.now()
        record.save(update_fields=['check_out', 'updated_at'])
    return JsonResponse({'success': True, 'check_out': record.check_out.isoformat(), 'message': 'Your sign-out has been recorded.'})


@login_required
def staff_attendance_dashboard(request):
    if not _can_manage(request.user):
        messages.error(request, "You do not have permission to manage staff attendance.")
        return redirect("dashboard")

    school = _school(request)
    if not school:
        messages.error(request, "Your account is not associated with a school.")
        return redirect("dashboard")

    selected_date = _attendance_date(request) or timezone.localdate()
    staff_qs = _staff_queryset(school)
    records = {
        row.staff_id: row
        for row in StaffAttendance.objects.filter(
            school=school, date=selected_date, staff_id__in=staff_qs.values("id")
        ).select_related("staff__user")
    }

    rows = []
    face_ids = set(
        _staff_queryset(school).filter(face_registered=True, face_encoding__isnull=False).values_list("id", flat=True)
    )
    # Include legacy registrations created by the first staff-face implementation.
    face_ids.update(StaffFaceProfile.objects.filter(
        school=school, is_active=True, encoding__isnull=False
    ).values_list("staff_id", flat=True))
    for staff in staff_qs:
        row = records.get(staff.id)
        staff.current_attendance = row.status if row else "UNMARKED"
        staff.current_record = row
        staff.face_registered = staff.id in face_ids
        rows.append(staff)

    page = paginate_queryset(rows, request, default=25)
    summary_qs = StaffAttendance.objects.filter(school=school, date=selected_date, staff_id__in=staff_qs.values("id"))
    summary = {
        "present": summary_qs.filter(status="PRESENT").count(),
        "late": summary_qs.filter(status="LATE").count(),
        "absent": summary_qs.filter(status="ABSENT").count(),
        "excused": summary_qs.filter(status="EXCUSED").count(),
        "unmarked": max(0, len(rows) - summary_qs.count()),
    }

    return render(request, "attendance/staff_attendance.html", {
        "staff_page": page,
        "selected_date": selected_date,
        "summary": summary,
        "face_recognition_available": FACE_RECOGNITION_AVAILABLE,
        "can_use_unified_kiosk": bool(getattr(request.user, "is_superuser", False)) or _role(request.user) in {"SUPER_ADMIN", "SCHOOL_ADMIN", "ADMIN"},
        "staff_total": len(rows),
    })


@login_required
@require_POST
def api_staff_toggle_attendance(request):
    if not _can_manage(request.user):
        return JsonResponse({"success": False, "error": "You do not have permission to manage staff attendance."}, status=403)
    school = _school(request)
    if not school:
        return JsonResponse({"success": False, "error": "Your account is not associated with a school."}, status=403)

    data, error = _json_or_form_data(request)
    if error:
        return error
    staff_id = data.get("staff_id")
    status = str(data.get("status") or "PRESENT").strip().upper()
    date_value = _valid_target_date(data.get("date"))
    if not staff_id:
        return JsonResponse({"success": False, "error": "A staff member is required."}, status=400)
    if status not in dict(StaffAttendance.STATUS_CHOICES):
        return JsonResponse({"success": False, "error": "Invalid attendance status."}, status=400)
    policy_error = _attendance_policy_error(school, request.user, date_value, status=status)
    if policy_error:
        return JsonResponse({"success": False, "error": policy_error}, status=403)

    staff = get_object_or_404(_staff_queryset(school), id=staff_id)
    with transaction.atomic():
        existing = StaffAttendance.objects.select_for_update().filter(
            school=school, staff=staff, date=date_value
        ).first()
        if existing:
            return _attendance_conflict(existing)
        try:
            with transaction.atomic():
                record = StaffAttendance.objects.create(
                    school=school, staff=staff, date=date_value,
                    status=status, method="MANUAL", marked_by=request.user,
                    remarks="Marked manually.",
                    check_in=timezone.now() if status in {"PRESENT", "LATE"} else None,
                    check_out=None,
                )
        except IntegrityError:
            existing = StaffAttendance.objects.filter(
                school=school, staff=staff, date=date_value
            ).first()
            if existing:
                return _attendance_conflict(existing)
            raise

    return JsonResponse({
        "success": True, "created": True, "staff_id": str(staff.id),
        "staff_name": _staff_name(staff), "status": record.status,
        "method": record.method,
        "check_in": record.check_in.isoformat() if record.check_in else None,
        "check_out": None,
        "message": f"Attendance marked as {record.get_status_display()}.",
    })


@login_required
@require_POST
def api_staff_checkout(request):
    if not _can_manage(request.user):
        return JsonResponse({"success": False, "error": "You do not have permission to manage staff attendance."}, status=403)
    school = _school(request)
    if not school:
        return JsonResponse({"success": False, "error": "Your account is not associated with a school."}, status=403)

    data, error = _json_or_form_data(request)
    if error:
        return error
    staff_id = data.get("staff_id")
    if not staff_id:
        return JsonResponse({"success": False, "error": "A staff member is required."}, status=400)
    date_value = _valid_target_date(data.get("date"))
    policy_error = _attendance_policy_error(school, request.user, date_value, checkout=True)
    if policy_error:
        return JsonResponse({"success": False, "error": policy_error}, status=403)
    staff = get_object_or_404(_staff_queryset(school), id=staff_id)

    with transaction.atomic():
        record = StaffAttendance.objects.select_for_update().filter(
            school=school, staff=staff, date=date_value
        ).first()
        if not record:
            return JsonResponse({"success": False, "error": "Staff member has not been marked in yet."}, status=400)
        if record.status not in {"PRESENT", "LATE"}:
            return JsonResponse({"success": False, "error": "Only staff marked present or late can sign out."}, status=400)
        if record.check_out:
            return JsonResponse({
                "success": False, "already_checked_out": True,
                "error": "This staff member has already signed out for this date.",
                "check_out": record.check_out.isoformat(),
            }, status=409)
        record.check_out = timezone.now()
        record.save(update_fields=["check_out", "updated_at"])

    return JsonResponse({
        "success": True, "check_out": record.check_out.isoformat(),
        "message": "Staff sign-out recorded successfully.",
    })


@login_required
@require_POST
def api_register_staff_face(request):
    if not _can_manage(request.user):
        return JsonResponse({"success": False, "error": "You do not have permission to register staff faces."}, status=403)
    school = _school(request)
    if not school:
        return JsonResponse({"success": False, "error": "Your account is not associated with a school."}, status=403)
    if not FACE_RECOGNITION_AVAILABLE:
        return JsonResponse({"success": False, "error": "Face recognition is not installed on this server. Manual attendance is available; install the optional face-recognition package to enable camera recognition."}, status=503)

    data, error = _json_or_form_data(request)
    if error:
        return error
    if not data.get("staff_id"):
        return JsonResponse({"success": False, "error": "A staff member is required."}, status=400)
    staff = get_object_or_404(_staff_queryset(school), id=data.get("staff_id"))
    image_data = data.get("image")
    if not image_data:
        return JsonResponse({"success": False, "error": "No camera image was provided."}, status=400)
    if not isinstance(image_data, str) or not image_data.startswith("data:image/"):
        return JsonResponse({"success": False, "error": "The camera image format is invalid. Please capture the image again."}, status=400)

    if str(data.get("face_registration_consent", "")).lower() not in {"1", "true", "on", "yes"}:
        return JsonResponse({"success": False, "error": "Confirm that the staff member has been informed and agrees before registering face-based attendance."}, status=400)
    encoding, message = FaceRecognitionService.encode_face(image_data)
    if not encoding:
        return JsonResponse({"success": False, "error": message}, status=400)

    duplicate = find_duplicate_staff_face(school, encoding, exclude_staff_id=staff.id, tolerance=0.45)
    if duplicate:
        return JsonResponse({
            "success": False, "duplicate_face": True,
            "error": "This face is already registered to {} ({}). Each staff member must have a unique face registration.".format(_staff_name(duplicate), duplicate.staff_id),
        }, status=409)

    use_as_profile_picture = str(data.get("use_as_profile_picture", "")).lower() in {"1", "true", "on", "yes"}
    try:
        save_staff_face(staff, encoding, image_data, request.user, use_as_profile_picture=use_as_profile_picture)
    except DuplicateStaffFaceError as exc:
        return JsonResponse({"success": False, "duplicate_face": True, "error": str(exc)}, status=409)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    message_text = "Staff face registered successfully. The captured image was saved as the face reference photo."
    if use_as_profile_picture:
        message_text += " It was also saved as the staff profile picture."
    return JsonResponse({"success": True, "staff_id": str(staff.id), "staff_name": _staff_name(staff), "message": message_text})


@login_required
@require_POST
def api_staff_live_capture(request):
    if not _can_manage(request.user):
        return JsonResponse({"success": False, "error": "You do not have permission to use staff face attendance."}, status=403)
    school = _school(request)
    if not school:
        return JsonResponse({"success": False, "error": "Your account is not associated with a school."}, status=403)
    if not FACE_RECOGNITION_AVAILABLE:
        return JsonResponse({"success": False, "error": "Face recognition is not installed on this server. Manual attendance is available."}, status=503)

    data, error = _json_or_form_data(request)
    if error:
        return error
    image_data = data.get("image")
    if not image_data:
        return JsonResponse({"success": False, "error": "No camera image was provided."}, status=400)
    if not isinstance(image_data, str) or not image_data.startswith("data:image/"):
        return JsonResponse({"success": False, "error": "The camera image format is invalid. Please capture the image again."}, status=400)
    target_date = _valid_target_date(data.get("date"))
    policy_error = _attendance_policy_error(school, request.user, target_date, status='PRESENT')
    if policy_error:
        return JsonResponse({"success": False, "error": policy_error}, status=403)

    encodings, message = FaceRecognitionService.encode_faces(image_data)
    if not encodings:
        return JsonResponse({
            "success": True, "recognized": False, "matched": [],
            "message": message or "No faces detected in this frame.",
        })

    staff_members = list(_staff_queryset(school).filter(face_registered=True, face_encoding__isnull=False))
    known = {str(staff.id): staff.face_encoding for staff in staff_members}
    # Preserve registrations created by the earlier StaffFaceProfile flow.
    legacy = list(StaffFaceProfile.objects.filter(
        school=school, is_active=True, encoding__isnull=False, staff__is_active=True
    ).select_related("staff__user"))
    for profile in legacy:
        known.setdefault(str(profile.staff_id), profile.encoding)
        if not any(str(item.id) == str(profile.staff_id) for item in staff_members):
            staff_members.append(profile.staff)
    staff_by_id = {str(item.id): item for item in staff_members}

    matched, seen_ids, ambiguous_frames = [], set(), []
    for face_encoding in encodings:
        matches = FaceRecognitionService.compare_faces_all(known, face_encoding, tolerance=0.50)
        if len(matches) > 1:
            ambiguous_frames.append([
                _staff_name(staff_by_id[item_id]) for item_id, _distance in matches[:3]
                if item_id in staff_by_id
            ])
            continue
        if not matches:
            continue
        staff_id = matches[0][0]
        if staff_id in seen_ids or staff_id not in staff_by_id:
            continue
        seen_ids.add(staff_id)
        staff = staff_by_id[staff_id]
        now = timezone.now()
        try:
            with transaction.atomic():
                record, created = StaffAttendance.objects.get_or_create(
                    school=school, staff=staff, date=target_date,
                    defaults={
                        "status": "PRESENT", "method": "FACE", "check_in": now,
                        "marked_by": request.user,
                        "remarks": "Automatically recorded by face recognition.",
                    },
                )
        except IntegrityError:
            record = StaffAttendance.objects.filter(
                school=school, staff=staff, date=target_date
            ).first()
            created = False
        matched.append({
            "staff_id": str(staff.id), "staff_name": _staff_name(staff),
            "staff_number": staff.staff_id, "status": record.status if record else "UNKNOWN",
            "check_in": record.check_in.isoformat() if record and record.check_in else None,
            "check_out": record.check_out.isoformat() if record and record.check_out else None,
            "created": bool(created), "already_marked": not bool(created),
        })

    created_count = sum(1 for item in matched if item["created"])
    return JsonResponse({
        "success": True, "recognized": bool(matched), "matched": matched,
        "recognized_count": len(matched), "created_count": created_count,
        "ambiguous_count": len(ambiguous_frames),
        "message": (
            "Automatically recorded attendance for {} staff member(s).".format(created_count)
            if created_count else
            "Recognized {} staff member(s); no new attendance was needed.".format(len(matched))
            if matched else
            "No registered staff faces matched this frame."
        ),
    })
