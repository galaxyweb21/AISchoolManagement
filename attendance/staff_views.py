import base64
import binascii
from datetime import datetime, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.pagination import paginate_queryset
from staff.models import StaffProfile

from .face_service import FACE_RECOGNITION_AVAILABLE, FaceRecognitionService
from .models import StaffAttendance, StaffFaceProfile


STAFF_ATTENDANCE_ROLES = {"SUPER_ADMIN", "SCHOOL_ADMIN", "ADMIN", "BURSAR", "HOD"}


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
    summary_qs = StaffAttendance.objects.filter(school=school, date=selected_date)
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

    data = request.POST if not request.body else None
    if data is None:
        try:
            import json
            data = json.loads(request.body.decode("utf-8") or "{}")
        except (TypeError, ValueError, UnicodeDecodeError):
            return JsonResponse({"success": False, "error": "Invalid JSON data."}, status=400)

    staff_id = data.get("staff_id")
    status = str(data.get("status") or "PRESENT").strip().upper()
    date_value = parse_date(str(data.get("date") or "")) or timezone.localdate()

    if status not in dict(StaffAttendance.STATUS_CHOICES):
        return JsonResponse({"success": False, "error": "Invalid attendance status."}, status=400)

    staff = get_object_or_404(_staff_queryset(school), id=staff_id)
    now = timezone.now()
    defaults = {
        "status": status,
        "method": "MANUAL",
        "marked_by": request.user,
        "remarks": "Marked manually.",
    }
    if status in {"PRESENT", "LATE"}:
        defaults["check_in"] = now
    else:
        defaults["check_in"] = None
        defaults["check_out"] = None

    record, created = StaffAttendance.objects.update_or_create(
        school=school, staff=staff, date=date_value, defaults=defaults
    )
    return JsonResponse({
        "success": True,
        "created": created,
        "staff_id": str(staff.id),
        "staff_name": _staff_name(staff),
        "status": record.status,
        "method": record.method,
        "check_in": record.check_in.isoformat() if record.check_in else None,
    })


@login_required
@require_POST
def api_staff_checkout(request):
    if not _can_manage(request.user):
        return JsonResponse({"success": False, "error": "You do not have permission to manage staff attendance."}, status=403)
    school = _school(request)
    if not school:
        return JsonResponse({"success": False, "error": "Your account is not associated with a school."}, status=403)
    try:
        import json
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON data."}, status=400)
    date_value = parse_date(str(data.get("date") or "")) or timezone.localdate()
    staff = get_object_or_404(_staff_queryset(school), id=data.get("staff_id"))
    record = StaffAttendance.objects.filter(school=school, staff=staff, date=date_value).first()
    if not record:
        return JsonResponse({"success": False, "error": "Staff member has not been marked in yet."}, status=400)
    record.check_out = timezone.now()
    record.save(update_fields=["check_out", "updated_at"])
    return JsonResponse({"success": True, "check_out": record.check_out.isoformat()})


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

    try:
        import json
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON data."}, status=400)

    staff = get_object_or_404(_staff_queryset(school), id=data.get("staff_id"))
    image_data = data.get("image")
    if not image_data:
        return JsonResponse({"success": False, "error": "No camera image was provided."}, status=400)

    encoding, message = FaceRecognitionService.encode_face(image_data)
    if not encoding:
        return JsonResponse({"success": False, "error": message}, status=400)

    profile, _ = StaffFaceProfile.objects.get_or_create(
        school=school, staff=staff,
        defaults={"registered_by": request.user},
    )
    profile.encoding = encoding
    profile.registered_at = timezone.now()
    profile.registered_by = request.user
    profile.is_active = True

    if isinstance(image_data, str) and "," in image_data:
        try:
            header, encoded = image_data.split(",", 1)
            extension = "jpg"
            if "image/png" in header:
                extension = "png"
            elif "image/webp" in header:
                extension = "webp"
            profile.photo.save(
                f"{staff.staff_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.{extension}",
                ContentFile(base64.b64decode(encoded)),
                save=False,
            )
        except (ValueError, binascii.Error):
            pass

    profile.save()
    return JsonResponse({"success": True, "staff_id": str(staff.id), "staff_name": _staff_name(staff), "message": "Staff face registered successfully."})


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

    try:
        import json
        data = json.loads(request.body.decode("utf-8") or "{}")
    except (TypeError, ValueError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON data."}, status=400)

    image_data = data.get("image")
    if not image_data:
        return JsonResponse({"success": False, "error": "No camera image was provided."}, status=400)
    target_date = parse_date(str(data.get("date") or "")) or timezone.localdate()

    encoding, message = FaceRecognitionService.encode_face(image_data)
    if not encoding:
        return JsonResponse({"success": False, "error": message}, status=400)

    staff_members = list(_staff_queryset(school).filter(face_registered=True, face_encoding__isnull=False))
    known = {str(staff.id): staff.face_encoding for staff in staff_members}
    # Backward compatibility for registrations made before face data lived on StaffProfile.
    legacy = list(StaffFaceProfile.objects.filter(
        school=school, is_active=True, encoding__isnull=False, staff__is_active=True
    ).select_related("staff__user"))
    for profile in legacy:
        known.setdefault(str(profile.staff_id), profile.encoding)
        if not any(str(item.id) == str(profile.staff_id) for item in staff_members):
            staff_members.append(profile.staff)
    staff_id = FaceRecognitionService.compare_faces(known, encoding, tolerance=0.50)
    if not staff_id:
        return JsonResponse({"success": True, "recognized": False, "message": "No registered staff member matched this face."})
    staff = next((item for item in staff_members if str(item.id) == str(staff_id)), None)
    if not staff:
        return JsonResponse({"success": True, "recognized": False, "message": "Face matched but staff record could not be loaded."})
    now = timezone.now()
    record, created = StaffAttendance.objects.update_or_create(
        school=school,
        staff=staff,
        date=target_date,
        defaults={
            "status": "PRESENT",
            "method": "FACE",
            "check_in": now,
            "marked_by": request.user,
            "remarks": "Marked by face recognition.",
        },
    )
    return JsonResponse({
        "success": True,
        "recognized": True,
        "created": created,
        "staff_id": str(staff.id),
        "staff_name": _staff_name(staff),
        "staff_number": staff.staff_id,
        "status": record.status,
        "check_in": record.check_in.isoformat() if record.check_in else None,
    })
