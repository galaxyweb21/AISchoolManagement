import io
import re
import zipfile
from collections import defaultdict

from django.http import HttpResponse

from ai_engine.models import ReportCard
from ai_engine.services.export_service import ExportService


def _safe_name(value, fallback='Report'):
    value = re.sub(r'[\\/:*?"<>|]+', '-', str(value or '')).strip(' .')
    value = re.sub(r'\s+', ' ', value)
    return value[:120] or fallback


def _pdf_bytes(card):
    response = ExportService.export_report_card_to_pdf(card)
    return bytes(response.content), response.get('Content-Type', 'application/pdf')


def build_class_report_zip(school, term):
    """Build one outer ZIP containing one ZIP per class and one PDF per student."""
    cards = (ReportCard.objects
             .filter(school=school, academic_term=term)
             .select_related('student__user', 'student__school_class', 'student__grade_level')
             .order_by('student__school_class__name', 'student__user__last_name', 'student__user__first_name'))

    groups = defaultdict(list)
    for card in cards.iterator():
        class_name = getattr(getattr(card.student, 'school_class', None), 'name', None) or 'Unassigned Class'
        groups[class_name].append(card)

    if not groups:
        return None, 0, 0

    outer = io.BytesIO()
    student_count = 0
    class_count = 0
    with zipfile.ZipFile(outer, 'w', zipfile.ZIP_DEFLATED) as outer_zip:
        for class_name in sorted(groups, key=str.casefold):
            class_count += 1
            class_buffer = io.BytesIO()
            with zipfile.ZipFile(class_buffer, 'w', zipfile.ZIP_DEFLATED) as class_zip:
                used_names = set()
                for card in groups[class_name]:
                    student = card.student
                    full_name = student.user.get_full_name().strip() or 'Student'
                    admission = getattr(student, 'admission_number', None) or str(student.pk)
                    filename = _safe_name(f'{full_name} - {admission} - {class_name} - Report Card') + '.pdf'
                    # Avoid collisions when two records share the same name/ID.
                    base = filename[:-4]
                    candidate = filename
                    n = 2
                    while candidate.lower() in used_names:
                        candidate = f'{base} ({n}).pdf'
                        n += 1
                    used_names.add(candidate.lower())
                    data, content_type = _pdf_bytes(card)
                    if content_type != 'application/pdf':
                        raise RuntimeError('Report-card PDF generation is unavailable. Please install/configure xhtml2pdf.')
                    class_zip.writestr(candidate, data)
                    student_count += 1
            outer_zip.writestr(_safe_name(class_name, 'Class') + '.zip', class_buffer.getvalue())

    outer.seek(0)
    return outer.getvalue(), class_count, student_count


def report_card_class_zip_response(school, term):
    data, class_count, student_count = build_class_report_zip(school, term)
    if not data:
        return None, class_count, student_count
    filename = _safe_name(f'{school.name} - {term} - Report Cards') + '.zip'
    response = HttpResponse(data, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response, class_count, student_count
