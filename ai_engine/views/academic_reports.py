import csv
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.html import escape
from django.views.decorators.http import require_GET

from ai_engine.services.copilot_context import allowed_students
from ai_engine.services.permissions import get_ai_permissions
from assessments.models import TerminalResult
from school.models import AcademicTerm


def _report_queryset(request, school):
    """Build a school- and user-scoped queryset of completed terminal results."""
    student_ids = allowed_students(request.user, school).values_list('pk', flat=True)
    queryset = TerminalResult.objects.filter(
        school=school,
        student_id__in=student_ids,
        status='COMPLETE',
        final_score__isnull=False,
    ).select_related('student__user', 'school_class', 'academic_term')

    term_id = (request.GET.get('term') or '').strip()
    class_id = (request.GET.get('class_id') or '').strip()
    subject = (request.GET.get('subject') or '').strip()

    terms = AcademicTerm.objects.filter(
        academic_year__school=school
    ).select_related('academic_year').order_by('-start_date')
    active_term = terms.filter(academic_year__is_active=True, is_active=True).first()
    selected_term = active_term or terms.first()
    if term_id:
        try:
            selected_term = terms.filter(pk=term_id).first() or selected_term
        except (TypeError, ValueError, ValidationError):
            pass
    if selected_term:
        queryset = queryset.filter(academic_term=selected_term)
    if class_id:
        try:
            queryset = queryset.filter(school_class_id=class_id)
            # Force validation now so malformed query parameters never break the page.
            queryset.query
        except (TypeError, ValueError, ValidationError):
            class_id = ''
    if subject:
        queryset = queryset.filter(subject=subject)

    return queryset, terms, selected_term


def _safe_csv_cell(value):
    """Prevent spreadsheet formula injection in exported user-controlled text."""
    value = '' if value is None else str(value)
    if value.startswith(('=', '+', '-', '@', '\t', '\r')):
        return "'" + value
    return value


@login_required
@require_GET
def academic_performance_reports(request):
    school = getattr(request.user, 'school', None)
    permissions = get_ai_permissions(request.user)
    if not school or not permissions.can_view_risk:
        messages.error(request, 'You do not have permission to view academic performance reports.')
        return redirect('dashboard:dashboard')

    results, terms, selected_term = _report_queryset(request, school)
    summary = results.aggregate(
        average=Avg('final_score'),
        result_count=Count('pk'),
        student_count=Count('student_id', distinct=True),
        subject_count=Count('subject', distinct=True),
        below_50=Count('pk', filter=Q(final_score__lt=50)),
    )
    classes = results.order_by('school_class__name').values_list(
        'school_class_id', 'school_class__name'
    ).distinct()
    subjects = results.order_by('subject').values_list('subject', flat=True).distinct()
    rows = results.order_by('school_class__name', 'student__user__last_name', 'student__user__first_name', 'subject')[:300]

    context = {
        'terms': terms,
        'selected_term': selected_term,
        'classes': classes,
        'subjects': subjects,
        'selected_class': (request.GET.get('class_id') or '').strip(),
        'selected_subject': (request.GET.get('subject') or '').strip(),
        'summary': summary,
        'rows': rows,
        'truncated': summary['result_count'] > 300,
        'today': date.today(),
    }
    return render(request, 'ai_engine/academic_performance_reports.html', context)


@login_required
@require_GET
def export_academic_performance_csv(request):
    school = getattr(request.user, 'school', None)
    permissions = get_ai_permissions(request.user)
    if not school or not permissions.can_view_risk:
        return HttpResponse('Permission denied.', status=403, content_type='text/plain')

    results, terms, selected_term = _report_queryset(request, school)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="academic-performance-report.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['School', 'Academic term', 'Class', 'Student', 'Subject', 'Final score', 'Grade', 'Remark'])
    for result in results.order_by('school_class__name', 'student__user__last_name', 'student__user__first_name', 'subject').iterator(chunk_size=500):
        user = result.student.user
        student_name = user.get_full_name().strip() or user.get_username()
        writer.writerow([
            _safe_csv_cell(getattr(school, 'name', '')),
            _safe_csv_cell(str(selected_term) if selected_term else ''),
            _safe_csv_cell(result.school_class.name),
            _safe_csv_cell(student_name),
            _safe_csv_cell(result.subject),
            _safe_csv_cell(result.final_score),
            _safe_csv_cell(result.grade),
            _safe_csv_cell(result.remark),
        ])
    return response


@login_required
@require_GET
def export_academic_performance_print(request):
    """Create a printable report; uses the project's configured PDF exporter."""
    school = getattr(request.user, 'school', None)
    permissions = get_ai_permissions(request.user)
    if not school or not permissions.can_view_risk:
        return HttpResponse('Permission denied.', status=403, content_type='text/plain')

    results, terms, selected_term = _report_queryset(request, school)
    summary = results.aggregate(average=Avg('final_score'), result_count=Count('pk'), student_count=Count('student_id', distinct=True))
    body_rows = []
    for result in results.order_by('school_class__name', 'student__user__last_name', 'student__user__first_name', 'subject').iterator(chunk_size=500):
        user = result.student.user
        name = user.get_full_name().strip() or user.get_username()
        body_rows.append(
            '<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                escape(result.school_class.name), escape(name), escape(result.subject),
                escape(str(result.final_score)), escape(result.grade or '-'),
            )
        )
    term_label = escape(str(selected_term) if selected_term else 'No term selected')
    school_name = escape(getattr(school, 'name', 'School'))
    average = '{:.2f}'.format(summary['average']) if summary['average'] is not None else 'N/A'
    document = '''<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:Arial,sans-serif;color:#202938;font-size:10pt;margin:28px}
    h1{font-size:20pt;margin-bottom:4px;color:#26364a} .muted{color:#65758b}
    .stats{margin:18px 0;padding:12px;background:#f3f6fa}
    table{width:100%;border-collapse:collapse;margin-top:16px}th,td{border:1px solid #dce3eb;padding:7px;text-align:left}
    th{background:#eef2f7}tr:nth-child(even){background:#fafbfd}
    </style></head><body><h1>Academic Performance Report</h1>
    <div>{school}</div><p class="muted">Academic term: {term}</p>
    <div class="stats">Results: {count} &nbsp; | &nbsp; Students: {students} &nbsp; | &nbsp; Average: {average}%</div>
    <table><thead><tr><th>Class</th><th>Student</th><th>Subject</th><th>Score</th><th>Grade</th></tr></thead>
    <tbody>{rows}</tbody></table><p class="muted">Generated {generated}. Only completed results visible to your account are included.</p>
    </body></html>'''.format(
        school=school_name, term=term_label, count=summary['result_count'],
        students=summary['student_count'], average=average,
        rows=''.join(body_rows), generated=date.today().isoformat(),
    )
    try:
        from ai_engine.services.export_service import ExportService
        return ExportService._generate_pdf(document, 'academic-performance-report.pdf')
    except Exception:
        # Keep a usable print/export path even if the optional PDF renderer is unavailable.
        response = HttpResponse(document, content_type='text/html; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="academic-performance-report.html"'
        return response
