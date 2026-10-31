"""School-scoped staff attendance reports and CSV export."""
import csv
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from staff.models import StaffProfile
from .models import StaffAttendance
from .staff_views import STAFF_ATTENDANCE_ROLES, _role, _school


def _can_manage(user):
    return bool(getattr(user, "is_superuser", False)) or _role(user) in STAFF_ATTENDANCE_ROLES


def _report_filters(request):
    today = timezone.localdate()
    start = parse_date(request.GET.get("date_from", "")) or (today - timedelta(days=29))
    end = parse_date(request.GET.get("date_to", "")) or today
    if start > end:
        start, end = end, start

    qs = StaffAttendance.objects.filter(
        school=_school(request), date__range=(start, end)
    ).select_related("staff__user", "staff__department", "marked_by").order_by(
        "-date", "staff__user__last_name", "staff__user__first_name"
    )

    status = str(request.GET.get("status", "")).strip().upper()
    if status in dict(StaffAttendance.STATUS_CHOICES):
        qs = qs.filter(status=status)
    else:
        status = ""

    department_id = str(request.GET.get("department", "")).strip()
    if department_id:
        try:
            department_id = str(uuid.UUID(department_id))
            qs = qs.filter(staff__department_id=department_id)
        except (ValueError, TypeError, AttributeError):
            department_id = ""

    staff_id = str(request.GET.get("staff", "")).strip()
    if staff_id:
        try:
            staff_id = str(uuid.UUID(staff_id))
            qs = qs.filter(staff_id=staff_id)
        except (ValueError, TypeError, AttributeError):
            staff_id = ""

    search = str(request.GET.get("q", "")).strip()[:100]
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(staff__staff_id__icontains=search)
            | Q(staff__user__first_name__icontains=search)
            | Q(staff__user__last_name__icontains=search)
            | Q(staff__user__email__icontains=search)
        )

    return qs, start, end, status, department_id, staff_id, search


@login_required
def staff_attendance_reports(request):
    if not _can_manage(request.user):
        messages.error(request, "You do not have permission to view staff attendance reports.")
        return redirect("dashboard")
    school = _school(request)
    if not school:
        messages.error(request, "Your account is not associated with a school.")
        return redirect("dashboard")

    records, start, end, status, department_id, staff_id, search = _report_filters(request)
    summary = {
        "total": records.count(),
        "present": records.filter(status="PRESENT").count(),
        "late": records.filter(status="LATE").count(),
        "absent": records.filter(status="ABSENT").count(),
        "excused": records.filter(status="EXCUSED").count(),
    }
    page = Paginator(records, 20).get_page(request.GET.get("page"))

    department_options = [
        {"id": department_id_value, "name": name}
        for department_id_value, name in StaffProfile.objects.filter(school=school)
        .exclude(department__isnull=True)
        .values_list("department_id", "department__name")
        .distinct().order_by("department__name")
    ]
    staff_options = StaffProfile.objects.filter(school=school, is_active=True).select_related("user").order_by(
        "user__last_name", "user__first_name", "staff_id"
    )
    query = request.GET.copy()
    query.pop("page", None)
    export_url = reverse("attendance:staff_attendance_export_csv")
    if query:
        export_url += "?" + query.urlencode()

    return render(request, "attendance/staff_attendance_reports.html", {
        "records_page": page,
        "date_from": start,
        "date_to": end,
        "selected_status": status,
        "selected_department": department_id,
        "selected_staff": staff_id,
        "search_query": search,
        "department_options": department_options,
        "staff_options": staff_options,
        "summary": summary,
        "export_url": export_url,
        "pagination_query": query.urlencode(),
    })


@login_required
def staff_attendance_export_csv(request):
    if not _can_manage(request.user):
        return HttpResponse("Permission denied.", status=403, content_type="text/plain")
    school = _school(request)
    if not school:
        return HttpResponse("Your account is not associated with a school.", status=403, content_type="text/plain")

    records, start, end, status, department_id, staff_id, search = _report_filters(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")  # Excel-friendly UTF-8 BOM.
    response["Content-Disposition"] = (
        f'attachment; filename="staff-attendance-{start.isoformat()}-to-{end.isoformat()}.csv"'
    )
    writer = csv.writer(response)

    def csv_safe(value):
        value = "" if value is None else str(value)
        # Prevent spreadsheet formula execution for user-editable text fields.
        return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value

    writer.writerow([
        "Staff ID", "Staff Name", "Department", "Date", "Status", "Method",
        "Check In", "Check Out", "Remarks", "Marked By",
    ])
    for record in records.iterator(chunk_size=500):
        staff = record.staff
        name = staff.user.get_full_name().strip() or staff.staff_id
        department = getattr(getattr(staff, "department", None), "name", "")
        check_in = timezone.localtime(record.check_in).strftime("%Y-%m-%d %H:%M:%S") if record.check_in else ""
        check_out = timezone.localtime(record.check_out).strftime("%Y-%m-%d %H:%M:%S") if record.check_out else ""
        marked_by = record.marked_by.get_full_name().strip() if record.marked_by else ""
        writer.writerow([
            csv_safe(staff.staff_id), csv_safe(name), csv_safe(department), record.date.isoformat(),
            record.get_status_display(), record.get_method_display(),
            check_in, check_out, csv_safe(record.remarks), csv_safe(marked_by),
        ])
    return response
