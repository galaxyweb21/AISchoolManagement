# ai_engine/services/export_service.py
"""
Export Service for AI-generated content
Supports PDF and DOC document generation
"""

import io
import base64
import os
from datetime import datetime
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string

try:
    from PIL import Image, ImageChops
except Exception:  # pragma: no cover
    Image = None
    ImageChops = None
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
import tempfile
import logging

logger = logging.getLogger(__name__)

# Try to import xhtml2pdf, fallback to a warning if not available
try:
    from xhtml2pdf import pisa

    XHTML2PDF_AVAILABLE = True
except ImportError as e:
    XHTML2PDF_AVAILABLE = False
    logger.warning(f"xhtml2pdf not available: {e}. PDF export will use fallback.")


class ExportService:
    """Service for exporting AI-generated content to PDF and DOC formats"""

    @staticmethod
    def _pdf_link_callback(uri, rel):
        from urllib.parse import urlparse
        path = urlparse(uri).path if uri else ''
        media_url = getattr(settings, 'MEDIA_URL', '/media/')
        static_url = getattr(settings, 'STATIC_URL', '/static/')
        if path.startswith(media_url):
            candidate = os.path.join(getattr(settings, 'MEDIA_ROOT', ''), path[len(media_url):].lstrip('/'))
        elif path.startswith(static_url):
            candidate = os.path.join(getattr(settings, 'STATIC_ROOT', ''), path[len(static_url):].lstrip('/'))
            if not os.path.exists(candidate):
                candidate = os.path.join(getattr(settings, 'BASE_DIR', ''), 'static', path[len(static_url):].lstrip('/'))
        else:
            candidate = uri
        return candidate if candidate and os.path.exists(candidate) else uri

    @staticmethod
    def _generate_pdf(html_content, filename):
        if not XHTML2PDF_AVAILABLE:
            return ExportService._fallback_pdf_response(filename)
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        status = pisa.CreatePDF(html_content, dest=response, encoding='UTF-8', link_callback=ExportService._pdf_link_callback)
        if status.err:
            logger.error('xhtml2pdf returned %s error(s) for %s', status.err, filename)
            return ExportService._fallback_pdf_response(filename)
        return response

    @staticmethod
    def _fallback_pdf_response(filename):
        """
        Fallback when xhtml2pdf is not available.
        Returns a simple HTML page with instructions.
        """
        fallback_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>PDF Export Unavailable</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                .icon {{ font-size: 64px; color: #dc3545; }}
                h1 {{ color: #333; }}
                p {{ color: #666; line-height: 1.6; }}
                .btn {{ display: inline-block; padding: 12px 24px; background: #0d6efd; color: white; text-decoration: none; border-radius: 6px; }}
                .btn:hover {{ background: #0a58ca; }}
                .options {{ text-align: left; max-width: 400px; margin: 20px auto; }}
                .options li {{ margin-bottom: 8px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="icon">📄</div>
                <h1>PDF Export Unavailable</h1>
                <p>The PDF export feature requires the xhtml2pdf library which is not installed.</p>
                <p><strong>Alternative Options:</strong></p>
                <ul class="options">
                    <li>✅ Use the <strong>DOC</strong> export option (Microsoft Word format)</li>
                    <li>✅ Use the <strong>Print</strong> function in your browser and select "Save as PDF"</li>
                    <li>📦 Install xhtml2pdf: <code>pip install xhtml2pdf</code></li>
                </ul>
                <p style="margin-top: 30px;">
                    <a href="#" onclick="window.print(); return false;" class="btn">🖨️ Print this page (Save as PDF)</a>
                </p>
                <p style="margin-top: 20px; font-size: 12px; color: #999;">
                    Content for: {filename}
                </p>
            </div>
        </body>
        </html>
        """
        response = HttpResponse(fallback_html, content_type='text/html')
        response['Content-Disposition'] = f'attachment; filename="{filename.replace(".pdf", ".html")}"'
        return response

    @staticmethod
    def _get_pdf_styles():
        """Get common PDF styles"""
        return """
        <style>
            body {
                font-family: 'Helvetica', 'Arial', sans-serif;
                font-size: 12px;
                line-height: 1.6;
                margin: 40px;
                color: #333;
            }
            .header {
                text-align: center;
                margin-bottom: 30px;
                border-bottom: 2px solid #0d6efd;
                padding-bottom: 20px;
            }
            .header h1 {
                font-size: 24px;
                color: #0d6efd;
                margin: 0;
            }
            .header h2 {
                font-size: 18px;
                color: #333;
                margin: 5px 0;
            }
            .header .subtitle {
                color: #666;
                font-size: 12px;
            }
            .meta {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
            }
            .meta table {
                width: 100%;
            }
            .meta td {
                padding: 3px 10px;
            }
            .meta td:first-child {
                font-weight: bold;
                width: 120px;
            }
            .question {
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 1px solid #eee;
            }
            .question .q-header {
                font-weight: bold;
                font-size: 13px;
                color: #0d6efd;
            }
            .question .q-text {
                margin: 8px 0;
            }
            .question .q-points {
                color: #666;
                font-size: 11px;
            }
            .question .options {
                margin: 5px 0 5px 20px;
            }
            .question .options li {
                list-style-type: disc;
                margin-bottom: 2px;
            }
            .footer {
                text-align: center;
                margin-top: 40px;
                padding-top: 20px;
                border-top: 1px solid #ddd;
                color: #999;
                font-size: 10px;
            }
            .instructions {
                background: #f0f7ff;
                padding: 12px 15px;
                border-radius: 5px;
                margin-bottom: 20px;
                border-left: 4px solid #0d6efd;
            }
            .answer-space {
                min-height: 60px;
                border-bottom: 1px dashed #ccc;
                margin: 5px 0 10px 0;
            }
            .section-title {
                font-size: 16px;
                font-weight: bold;
                color: #198754;
                margin: 20px 0 10px 0;
                border-bottom: 1px solid #198754;
                padding-bottom: 5px;
            }
            .subject-table {
                width: 100%;
                border-collapse: collapse;
                margin: 10px 0;
            }
            .subject-table th {
                background: #198754;
                color: white;
                padding: 8px 12px;
                text-align: left;
            }
            .subject-table td {
                padding: 6px 12px;
                border-bottom: 1px solid #ddd;
            }
            .subject-table tr:nth-child(even) {
                background: #f8f9fa;
            }
            .comment-box {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin: 15px 0;
                border-left: 4px solid #198754;
            }
            .overall-score {
                font-size: 18px;
                font-weight: bold;
                color: #198754;
            }
            .risk-critical { color: #dc3545; font-weight: bold; }
            .risk-high { color: #ffc107; font-weight: bold; }
            .risk-medium { color: #0dcaf0; font-weight: bold; }
            .risk-low { color: #198754; font-weight: bold; }
            .risk-factors li {
                margin-bottom: 5px;
            }
            .factor-points {
                float: right;
                font-weight: bold;
                color: #6c757d;
            }
        </style>
        """

    @staticmethod
    def export_exam_to_pdf(exam, questions):
        """Export an AI-generated exam to PDF"""
        context = {
            'exam': exam,
            'questions': questions,
            'total_points': sum(q.points for q in questions),
            'generated_at': datetime.now(),
            'school_name': exam.school.name if exam.school else 'School',
        }

        html_content = render_to_string('ai_engine/exports/exam_export_pdf.html', context)

        # Wrap with styles
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{exam.title}</title>
            {ExportService._get_pdf_styles()}
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

        filename = f"exam_{exam.title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return ExportService._generate_pdf(full_html, filename)

    @staticmethod
    def export_exam_to_doc(exam, questions):
        """Export an AI-generated exam to DOC (Word) format"""
        doc = Document()

        # Add school header
        header = doc.add_heading(exam.school.name if exam.school else 'School', 0)
        header.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Exam title
        title = doc.add_heading(exam.title, 1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Exam metadata
        doc.add_paragraph(f"Subject: {exam.subject}")
        doc.add_paragraph(f"Class: {exam.school_class.name if exam.school_class else 'N/A'}")
        doc.add_paragraph(f"Grade Level: {exam.grade_level}")
        doc.add_paragraph(f"Difficulty: {exam.get_difficulty_display()}")
        doc.add_paragraph(f"Total Points: {sum(q.points for q in questions)}")
        doc.add_paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}")
        doc.add_paragraph("")
        doc.add_paragraph("Instructions: Answer all questions. Read each question carefully.")
        doc.add_paragraph("")

        # Add questions
        for i, q in enumerate(questions, 1):
            p = doc.add_paragraph()
            p.add_run(f"Q{i}. ").bold = True
            p.add_run(q.question_text)
            doc.add_paragraph(f"[{q.points} point{'s' if q.points > 1 else ''}]")

            if q.question_type == 'MCQ' and q.options:
                for opt in q.options:
                    doc.add_paragraph(f"   • {opt}", style='List Bullet')

            if q.question_type in ['SHORT_ANSWER', 'ESSAY']:
                for _ in range(3 if q.question_type == 'SHORT_ANSWER' else 6):
                    doc.add_paragraph("")

            doc.add_paragraph("")

        doc.add_paragraph("")
        doc.add_paragraph("--- End of Exam ---")
        doc.add_paragraph(f"Generated by EduAI on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        filename = f"exam_{exam.title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        doc.save(response)
        return response

    @staticmethod
    def _report_card_data(report_card):
        '''Use live TerminalResult data for draft cards. Finalized cards keep their
        locked official average/grade/position, but any subject row still missing
        Class /30 or Exam /70 is repaired from the live TerminalResult data so an
        export never shows a dash once the marks have actually been entered.'''
        from ai_engine.services.report_card_engine import ReportCardEngine
        report_card, computed = ReportCardEngine.refresh_report_card_snapshot(report_card, save=True)
        return computed

    @staticmethod
    def _safe_file_url(field):
        try:
            return field.url if field else ''
        except Exception:
            return ''

    @staticmethod
    def _file_bytes(field):
        """Read a Django FileField through its storage backend.

        Never use ``field.path`` here: production deployments may use Cloudinary
        or another remote storage backend where absolute filesystem paths do not
        exist.
        """
        if not field:
            return None
        try:
            field.open('rb')
            try:
                return field.read()
            finally:
                try:
                    field.close()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning('Could not read stored file for document export: %s', exc)
            return None

    @staticmethod
    def _prepare_signature_image(data):
        """Crop whitespace and normalize a handwritten signature for exports.

        Staff often upload a phone photo or a PNG with large blank margins.
        Cropping those margins makes the signature readable while keeping the
        original stored file untouched.
        """
        if not data or Image is None or ImageChops is None:
            return data, 'image/png'

        try:
            image = Image.open(io.BytesIO(data)).convert('RGBA')
            bbox = None

            # Prefer alpha bounds when the uploaded PNG has transparency.
            alpha = image.getchannel('A')
            alpha_bbox = alpha.getbbox()
            if alpha_bbox:
                bbox = alpha_bbox
            else:
                # For white-background photos/scans, crop pixels that differ
                # materially from white. Keep a small safety margin.
                rgb = image.convert('RGB')
                bg = Image.new('RGB', rgb.size, 'white')
                diff = ImageChops.difference(rgb, bg)
                diff = diff.point(lambda px: 255 if px > 18 else 0)
                bbox = diff.getbbox()

            if bbox:
                left, top, right, bottom = bbox
                pad_x = max(8, int(image.width * 0.02))
                pad_y = max(6, int(image.height * 0.04))
                bbox = (
                    max(0, left - pad_x),
                    max(0, top - pad_y),
                    min(image.width, right + pad_x),
                    min(image.height, bottom + pad_y),
                )
                image = image.crop(bbox)

            # Cap the export dimensions without shrinking small originals.
            image.thumbnail((900, 260), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            image.save(output, format='PNG', optimize=True)
            return output.getvalue(), 'image/png'
        except Exception as exc:
            logger.warning('Could not normalize report-card signature image: %s', exc)
            return data, 'image/png'

    @staticmethod
    def _signature_data_uri(field):
        data = ExportService._file_bytes(field)
        if not data:
            return None
        data, mime = ExportService._prepare_signature_image(data)
        return 'data:%s;base64,%s' % (mime, base64.b64encode(data).decode('ascii'))

    @staticmethod
    def _report_card_signatories(report_card):
        """Resolve authorized report-card signatories and their signatures.

        Draft cards use the current staff signatures. Finalized cards prefer
        the immutable signature snapshots captured during finalization, so a
        later staff-signature change cannot alter an already-issued report.
        """
        student = report_card.student
        school = report_card.school

        class_teacher_name = ''
        class_teacher_profile = None
        school_class = getattr(student, 'school_class', None)
        if school_class:
            try:
                teacher = getattr(school_class, 'homeroom_teacher', None)
                if teacher and getattr(teacher, 'user', None):
                    class_teacher_name = teacher.user.get_full_name().strip()
                    class_teacher_profile = getattr(teacher.user, 'staff_profile', None)
            except Exception:
                pass
            if not class_teacher_name:
                try:
                    from academics.models import TeacherClassAssignment
                    assignment = (TeacherClassAssignment.objects
                                   .filter(school=school, school_class=school_class, is_active=True)
                                   .select_related('teacher__user__staff_profile')
                                   .order_by('-assigned_at')
                                   .first())
                    if assignment and assignment.teacher and assignment.teacher.user:
                        class_teacher_name = assignment.teacher.user.get_full_name().strip()
                        class_teacher_profile = getattr(assignment.teacher.user, 'staff_profile', None)
                except Exception:
                    pass

        headteacher_profile = None
        headteacher_name = ''
        try:
            from staff.models import StaffProfile
            # Explicit designation wins. This makes the selection predictable
            # when a school has several administrators.
            headteacher_profile = (StaffProfile.objects
                                   .filter(school=school, is_active=True, is_headteacher=True)
                                   .select_related('user')
                                   .order_by('id')
                                   .first())
            if not headteacher_profile:
                headteacher_profile = (StaffProfile.objects
                                       .filter(school=school, staff_position='SCHOOL_ADMIN', is_active=True)
                                       .select_related('user')
                                       .order_by('id')
                                       .first())
            if headteacher_profile and headteacher_profile.user:
                headteacher_name = headteacher_profile.user.get_full_name().strip()
        except Exception:
            pass
        if not headteacher_name:
            try:
                head_user = (school.users.filter(role='SCHOOL_ADMIN', is_active=True)
                             .order_by('id').first())
                if head_user:
                    headteacher_name = head_user.get_full_name().strip()
                    headteacher_profile = getattr(head_user, 'staff_profile', None)
            except Exception:
                pass

        parent_name = ''
        try:
            parent = getattr(student, 'parent', None)
            if parent:
                parent_name = parent.get_full_name().strip()
        except Exception:
            pass

        # For finalized cards, use the stored snapshot first. For older
        # finalized cards that pre-date this feature, gracefully fall back to
        # the current staff signature instead of breaking export.
        teacher_signature = getattr(report_card, 'teacher_signature_snapshot', None) if report_card.is_finalized else None
        headteacher_signature = getattr(report_card, 'headteacher_signature_snapshot', None) if report_card.is_finalized else None

        if not teacher_signature and class_teacher_profile and getattr(class_teacher_profile, 'signature_is_active', True):
            teacher_signature = getattr(class_teacher_profile, 'signature_image', None)
        if not headteacher_signature and headteacher_profile and getattr(headteacher_profile, 'signature_is_active', True):
            headteacher_signature = getattr(headteacher_profile, 'signature_image', None)

        if report_card.is_finalized:
            class_teacher_name = getattr(report_card, 'teacher_signature_name', '') or class_teacher_name
            headteacher_name = getattr(report_card, 'headteacher_signature_name', '') or headteacher_name

        return {
            'class_teacher_name': class_teacher_name or 'Class Teacher',
            'headteacher_name': headteacher_name or 'Headteacher / Head of School',
            'parent_name': parent_name or 'Parent / Guardian',
            'class_teacher_signature': teacher_signature,
            'headteacher_signature': headteacher_signature,
        }

    @staticmethod
    def export_report_card_to_pdf(report_card):
        school, student = report_card.school, report_card.student
        computed = ExportService._report_card_data(report_card)
        signatories = ExportService._report_card_signatories(report_card)
        context = {
            'report_card': report_card,
            'student': student,
            'academic_term': report_card.academic_term,
            'subject_breakdown': computed.get('subject_breakdown', []),
            'generated_at': datetime.now(),
            'school_logo': ExportService._safe_file_url(getattr(school, 'logo', None)),
            'student_photo': ExportService._safe_file_url(getattr(getattr(student, 'user', None), 'profile_picture', None)),
            **signatories,
        }
        context.update({
            'teacher_signature_url': ExportService._signature_data_uri(signatories.get('class_teacher_signature')) or ExportService._safe_file_url(signatories.get('class_teacher_signature')),
            'headteacher_signature_url': ExportService._signature_data_uri(signatories.get('headteacher_signature')) or ExportService._safe_file_url(signatories.get('headteacher_signature')),
        })
        html = render_to_string('ai_engine/exports/report_card_export_pdf.html', context)
        css = '''<style>
        @page{size:A4 portrait;margin:7mm 7mm 8mm 7mm}
        body{font-family:Helvetica,Arial,sans-serif;color:#25322e;font-size:8pt;line-height:1.25;margin:0;background:#fff}
        table{width:100%;border-collapse:collapse}
        .report-sheet{border:1.2px solid #25322e;padding:5px 6px 6px;background:#fff}

        /* Professional school header: restrained green, charcoal and neutral tones. */
        .school-header{border:1.2px solid #25322e;background:#17352c}
        .header-side{vertical-align:middle;text-align:center}
        .left-side{width:16%;padding:6px}
        .right-side{width:16%;padding:5px}
        .header-center{width:68%;text-align:center;padding:7px 5px;vertical-align:middle}
        .school-logo{width:55px;height:55px}
        .school-name{color:#fff;font-size:16pt;font-weight:bold;letter-spacing:.5px}
        .school-contact{color:#dce6e1;font-size:6.8pt;margin-top:2px}
        .report-title{display:inline-block;background:#fff;color:#17352c;font-size:9.5pt;font-weight:bold;letter-spacing:.8px;padding:4px 12px;margin-top:6px}
        .period{color:#e3ebe7;font-size:7.2pt;font-weight:bold;margin-top:4px}
        .student-photo{width:62px;height:72px;border:2px solid #fff}
        .photo-placeholder{width:62px;height:72px;border:1px solid #dce6e1;color:#dce6e1;font-size:6.5pt;font-weight:bold;text-align:center;padding-top:22px}

        .identity{margin-top:6px;border:1px solid #8b9590}
        .identity td{border:1px solid #cbd1ce;padding:4px 6px}
        .identity-label{background:#eef1ef;color:#59645f;font-size:6.5pt;font-weight:bold;letter-spacing:.3px;width:14%}
        .identity-value{width:36%;color:#28342f}
        .identity-value.name{font-weight:bold}

        .summary{margin-top:6px;border:1px solid #aab3af}
        .summary td{width:20%;text-align:center;border-right:1px solid #cbd1ce;padding:5px 2px;background:#f7f8f7}
        .summary td:last-child{border-right:0}
        .k-label{display:block;color:#66716c;font-size:6pt;font-weight:bold;letter-spacing:.5px}
        .k-value{display:block;color:#17352c;font-size:10.5pt;font-weight:bold;margin-top:1px}
        .k-value small{font-size:6.5pt;color:#65706b}
        .k-value.promotion{font-size:7.5pt;margin-top:3px}

        .section-bar{background:#17352c;color:#fff;font-size:8.2pt;font-weight:bold;letter-spacing:.55px;padding:5px 7px;margin-top:7px;border-left:4px solid #c9a14a}
        .results{border:1px solid #7f8985}
        .results th{background:#eef1ef;color:#24312d;border:1px solid #9aa39f;padding:4px 3px;font-size:6.6pt;font-weight:bold;text-align:center}
        .results th.subject,.results th.remark{text-align:left}
        .results th small{font-size:5.8pt;font-weight:normal}
        .results td{border:1px solid #d4d9d6;padding:4px 4px;font-size:7.3pt}
        .results tbody tr:nth-child(even){background:#f8f9f8}
        .subject{text-align:left;width:24%}
        .remark{text-align:left;width:20%;color:#56615c}
        .center{text-align:center}
        .strong{font-weight:bold;color:#25322e}
        .final{font-weight:bold}
        .grade{font-weight:bold;color:#17352c}
        .empty{text-align:center;color:#7b8580;padding:9px}
        .results tfoot td{background:#eef1ef;border-top:1.2px solid #7f8985;font-weight:bold}
        .total-label{text-align:right;color:#52605a;font-size:6.7pt}
        .total-value{text-align:center;color:#17352c;font-size:8.5pt}
        .scale-note{color:#69736e;font-size:6.2pt;font-style:italic;margin-top:3px}

        .attendance{border:1px solid #aab3af}
        .attendance td{border:1px solid #d1d6d3;text-align:center;padding:5px 4px;background:#fafbfa}
        .attendance .wide{text-align:left}
        .a-label{display:block;color:#69736e;font-size:5.9pt;font-weight:bold;letter-spacing:.35px;margin-bottom:1px}
        .attendance strong{font-size:7.5pt;color:#25322e}

        .comments{margin-top:6px}
        .comments td{width:50%;vertical-align:top;padding-right:4px}
        .comments td+td{padding-right:0;padding-left:4px}
        .comment-heading{background:#eef1ef;color:#17352c;border:1px solid #c7ceca;border-bottom:0;font-size:6.8pt;font-weight:bold;padding:4px 6px}
        .comment-box{border:1px solid #c7ceca;background:#fbfcfb;padding:6px;min-height:34px;color:#39453f;line-height:1.3}

        .signature-heading{margin-top:7px;margin-bottom:0}
        .signatures{border:1px solid #aab3af}
        .signatures td{text-align:center;width:33.33%;border:1px solid #d1d6d3;padding:3px 6px;color:#3e4944}
        .signatures .sig-head td{background:#eef1ef;color:#25322e;font-size:6.2pt;padding:4px 5px}
        .signatures .sig-name td{font-size:7.1pt;font-weight:bold;color:#25322e;padding:4px 5px}
        .signature-space{height:28px}
        .signature-image{display:block;width:auto;max-width:125px;max-height:30px;height:auto;object-fit:contain;margin:0 auto 2px auto}
        .sig-image-row td{height:36px;vertical-align:bottom;overflow:hidden}
        .signature-line{border-top:1px solid #59645f;height:2px}
        .signatures .sig-caption td{border-top:0;color:#7b8580;font-size:5.8pt;padding-top:0}

        .record-note{margin-top:7px;border:1px solid #c8cfcc;background:#f6f8f7;color:#59645f;padding:4px 6px;font-size:6.2pt;text-align:center}
        .record-note strong{color:#17352c}
        .footer{text-align:center;color:#7b8580;font-size:5.8pt;margin-top:4px}
        </style>'''
        full = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>End-of-Term Report Card</title>'+css+'</head><body>'+html+'</body></html>'
        return ExportService._generate_pdf(full, f'report_card_{student.admission_number}_{datetime.now():%Y%m%d}.pdf')

    @staticmethod
    def _shade_cell(cell, fill):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tcPr = cell._tc.get_or_add_tcPr()
        shd = tcPr.find(qn('w:shd'))
        if shd is None:
            shd = OxmlElement('w:shd'); tcPr.append(shd)
        shd.set(qn('w:fill'), fill)

    @staticmethod
    def _shade_paragraph_bg(paragraph, fill):
        """Shade a plain paragraph's background (used for section-header bars
        that aren't inside a table cell)."""
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        pPr = paragraph._p.get_or_add_pPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
        pPr.append(shd)

    @staticmethod
    def _set_cell_margins(cell, top=80, start=90, bottom=80, end=90):
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tc = cell._tc; tcPr = tc.get_or_add_tcPr(); tcMar = tcPr.first_child_found_in('w:tcMar')
        if tcMar is None:
            tcMar = OxmlElement('w:tcMar'); tcPr.append(tcMar)
        for m, v in [('top', top), ('start', start), ('bottom', bottom), ('end', end)]:
            node = tcMar.find(qn(f'w:{m}'))
            if node is None: node = OxmlElement(f'w:{m}'); tcMar.append(node)
            node.set(qn('w:w'), str(v)); node.set(qn('w:type'), 'dxa')

    @staticmethod
    def export_report_card_to_doc(report_card):
        """Export the end-of-term report card as a professional Word document.

        The Word layout intentionally mirrors the PDF version: school identity
        at the top, student photo on the right, compact learner information,
        academic results, attendance, comments and signature lines.
        """
        school, student = report_card.school, report_card.student
        computed = ExportService._report_card_data(report_card)
        doc = Document()
        sec = doc.sections[0]
        sec.top_margin = Inches(.38)
        sec.bottom_margin = Inches(.42)
        sec.left_margin = Inches(.45)
        sec.right_margin = Inches(.45)

        styles = doc.styles
        styles['Normal'].font.name = 'Aptos'
        styles['Normal'].font.size = Pt(8.5)

        # ---------- SCHOOL HEADER ----------
        head = doc.add_table(rows=1, cols=3)
        head.autofit = False
        head.alignment = WD_TABLE_ALIGNMENT.CENTER
        widths = [Inches(1.05), Inches(5.65), Inches(1.05)]
        for i, width in enumerate(widths):
            head.columns[i].width = width
            head.cell(0, i).width = width

        for cell in head.rows[0].cells:
            ExportService._shade_cell(cell, '17352C')
            ExportService._set_cell_margins(cell, 65, 55, 65, 55)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

        logo_cell = head.cell(0, 0)
        logo_p = logo_cell.paragraphs[0]
        logo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        logo_bytes = ExportService._file_bytes(getattr(school, 'logo', None))
        if logo_bytes:
            logo_p.add_run().add_picture(io.BytesIO(logo_bytes), width=Inches(.68))

        center = head.cell(0, 1)
        p = center.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(str(school.name).upper())
        r.bold = True
        r.font.size = Pt(16)
        r.font.color.rgb = RGBColor(255, 255, 255)

        contact_bits = [str(v) for v in [getattr(school, 'address', ''), getattr(school, 'phone_number', ''), getattr(school, 'contact_email', '')] if v]
        if contact_bits:
            r = p.add_run('\n' + ' • '.join(contact_bits))
            r.font.size = Pt(6.8)
            r.font.color.rgb = RGBColor(218, 229, 224)

        r = p.add_run('\nEND-OF-TERM REPORT CARD')
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)

        r = p.add_run(f'\n{report_card.academic_term.academic_year.name}  |  {report_card.academic_term.name}')
        r.bold = True
        r.font.size = Pt(7)
        r.font.color.rgb = RGBColor(218, 229, 224)

        photo_cell = head.cell(0, 2)
        photo_p = photo_cell.paragraphs[0]
        photo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        profile = getattr(getattr(student, 'user', None), 'profile_picture', None)
        profile_bytes = ExportService._file_bytes(profile)
        if profile_bytes:
            photo_p.add_run().add_picture(io.BytesIO(profile_bytes), width=Inches(.82), height=Inches(.96))
        else:
            initials = ((student.user.first_name[:1] if student.user.first_name else '') +
                        (student.user.last_name[:1] if student.user.last_name else '')).upper() or '—'
            rr = photo_p.add_run(initials)
            rr.bold = True
            rr.font.size = Pt(18)
            rr.font.color.rgb = RGBColor(255, 255, 255)

        doc.add_paragraph().paragraph_format.space_after = Pt(1)

        # ---------- STUDENT INFORMATION ----------
        info = doc.add_table(rows=3, cols=4)
        info.style = 'Table Grid'
        info.alignment = WD_TABLE_ALIGNMENT.CENTER
        info_data = [
            ('STUDENT NAME', student.user.get_full_name().upper(), 'ADMISSION NO.', student.admission_number or 'N/A'),
            ('CLASS / GRADE', f'{student.school_class or "N/A"} / {student.grade_level or "N/A"}', 'GENDER', student.user.get_gender_display() or 'N/A'),
            ('ACADEMIC YEAR', getattr(report_card.academic_term.academic_year, 'name', 'N/A'), 'TERM', getattr(report_card.academic_term, 'name', 'N/A')),
        ]
        for row, values in zip(info.rows, info_data):
            for idx, value in enumerate(values):
                cell = row.cells[idx]
                cell.text = str(value)
                ExportService._set_cell_margins(cell, 42, 55, 42, 55)
                if idx in (0, 2):
                    ExportService._shade_cell(cell, 'EEF1EF')
                    run = cell.paragraphs[0].runs[0]
                    run.bold = True
                    run.font.size = Pt(6.5)
                    run.font.color.rgb = RGBColor(83, 96, 90)
                else:
                    run = cell.paragraphs[0].runs[0]
                    run.font.size = Pt(8)
                    if idx == 1 and row is info.rows[0]:
                        run.bold = True

        # ---------- SUMMARY ----------
        avg = report_card.overall_average
        summary = doc.add_table(rows=2, cols=5)
        summary.style = 'Table Grid'
        summary.alignment = WD_TABLE_ALIGNMENT.CENTER
        labels = ['AVERAGE', 'POSITION', 'GRADE', 'ATTENDANCE', 'PROMOTION']
        values = [
            f'{avg:.1f}%' if avg is not None else '—',
            f'{report_card.overall_position} / {report_card.class_size}' if report_card.overall_position and report_card.class_size else (str(report_card.overall_position) if report_card.overall_position else '—'),
            report_card.overall_grade or '—',
            f'{report_card.attendance_rate:.1f}%' if report_card.attendance_rate is not None else '—',
            report_card.promotion_status or '—',
        ]
        for j, (label, value) in enumerate(zip(labels, values)):
            lc = summary.cell(0, j)
            vc = summary.cell(1, j)
            ExportService._shade_cell(lc, 'EEF1EF')
            ExportService._shade_cell(vc, 'FAFBFA')
            lc.text = label
            vc.text = str(value)
            lc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            vc.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            lc.paragraphs[0].runs[0].bold = True
            lc.paragraphs[0].runs[0].font.size = Pt(6)
            lc.paragraphs[0].runs[0].font.color.rgb = RGBColor(83, 96, 90)
            vc.paragraphs[0].runs[0].bold = True
            vc.paragraphs[0].runs[0].font.size = Pt(10.5 if j < 4 else 7.5)
            vc.paragraphs[0].runs[0].font.color.rgb = RGBColor(23, 53, 44)
            ExportService._set_cell_margins(lc, 35, 35, 18, 35)
            ExportService._set_cell_margins(vc, 18, 35, 42, 35)

        # ---------- SECTION HELPER ----------
        def section_bar(text):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(2)
            ExportService._shade_paragraph_bg(p, '17352C')
            r = p.add_run('  ' + text)
            r.bold = True
            r.font.size = Pt(9.5)
            r.font.color.rgb = RGBColor(255, 255, 255)
            return p

        section_bar('ACADEMIC PERFORMANCE')
        results = doc.add_table(rows=1, cols=7)
        results.style = 'Table Grid'
        results.alignment = WD_TABLE_ALIGNMENT.CENTER
        headers = ['Subject', 'Class /30', 'Exam /70', 'Final /100', 'Position', 'Grade', 'Meaning / Remarks']
        for cell, text in zip(results.rows[0].cells, headers):
            cell.text = text
            ExportService._shade_cell(cell, 'EEF1EF')
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = cell.paragraphs[0].runs[0]
            run.bold = True
            run.font.size = Pt(6.3)
            run.font.color.rgb = RGBColor(45, 58, 52)
            ExportService._set_cell_margins(cell, 40, 35, 40, 35)

        for row_idx, item in enumerate(computed.get('subject_breakdown', [])):
            cells = results.add_row().cells
            cs, es, total = item.get('class_score'), item.get('exam_score'), item.get('total')
            vals = [
                item.get('subject', ''),
                f'{float(cs):.2f}' if cs is not None else '—',
                f'{float(es):.2f}' if es is not None else '—',
                f'{float(total):.2f}' if total is not None else '—',
                item.get('position', '—') or '—',
                item.get('grade', '—') or '—',
                item.get('remark', '—') or '—',
            ]
            for idx, (cell, value) in enumerate(zip(cells, vals)):
                cell.text = str(value)
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.LEFT if idx in (0, 6) else WD_ALIGN_PARAGRAPH.CENTER
                if row_idx % 2 == 1:
                    ExportService._shade_cell(cell, 'FAFBFA')
                run = cell.paragraphs[0].runs[0]
                run.font.size = Pt(7.2)
                if idx in (0, 3, 5):
                    run.bold = True
                    run.font.color.rgb = RGBColor(23, 53, 44)
                ExportService._set_cell_margins(cell, 35, 35, 35, 35)

        total_row = results.add_row().cells
        total_row[0].merge(total_row[2])
        total_row[0].text = 'TOTAL PERFORMANCE'
        total_row[3].text = f'{report_card.total_marks:.1f}' if report_card.total_marks else '—'
        for cell in total_row:
            ExportService._shade_cell(cell, 'EEF1EF')
            ExportService._set_cell_margins(cell, 35, 35, 35, 35)
            if cell.paragraphs[0].runs:
                cell.paragraphs[0].runs[0].bold = True
                cell.paragraphs[0].runs[0].font.size = Pt(7)
        total_row[0].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        total_row[3].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        p = doc.add_paragraph('Assessment scale: Class Score /30 + Examination /70 = Final Score /100.')
        p.paragraph_format.space_after = Pt(1)
        p.runs[0].italic = True
        p.runs[0].font.size = Pt(6.5)
        p.runs[0].font.color.rgb = RGBColor(105, 115, 110)

        section_bar('ATTENDANCE & GENERAL ASSESSMENT')
        att = doc.add_table(rows=2, cols=6)
        att.style = 'Table Grid'
        attendance = [
            ('PRESENT', report_card.attendance_present),
            ('ABSENT', report_card.attendance_absent),
            ('LATE', report_card.attendance_late),
            ('OUT OF', report_card.attendance_total),
            ('CONDUCT', report_card.conduct or '—'),
            ('REOPENING / NEXT TERM', report_card.next_term_date.strftime('%d %b %Y') if report_card.next_term_date else '—'),
        ]
        for i, (label, value) in enumerate(attendance):
            for row_index, text in enumerate((label, value)):
                cell = att.cell(row_index, i)
                cell.text = str(text)
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER if i < 4 else WD_ALIGN_PARAGRAPH.LEFT
                ExportService._set_cell_margins(cell, 35, 35, 35, 35)
                if row_index == 0:
                    ExportService._shade_cell(cell, 'EEF1EF')
                    cell.paragraphs[0].runs[0].bold = True
                    cell.paragraphs[0].runs[0].font.size = Pt(5.8)
                    cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(83, 96, 90)
                else:
                    cell.paragraphs[0].runs[0].bold = True
                    cell.paragraphs[0].runs[0].font.size = Pt(7.2)
                    cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(37, 50, 46)

        # ---------- COMMENTS ----------
        comments = doc.add_table(rows=1, cols=2)
        comments.style = 'Table Grid'
        comments.alignment = WD_TABLE_ALIGNMENT.CENTER
        comment_values = [
            ("CLASS TEACHER'S REMARK", report_card.teacher_comment or report_card.ai_narrative or 'No comment recorded.'),
            ("HEADTEACHER'S REMARK", report_card.headteacher_comment or 'No comment recorded.'),
        ]
        for i, (title, text) in enumerate(comment_values):
            cell = comments.cell(0, i)
            ExportService._set_cell_margins(cell, 45, 55, 55, 55)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(title + '\n')
            r.bold = True
            r.font.size = Pt(6.8)
            r.font.color.rgb = RGBColor(23, 53, 44)
            r = p.add_run(str(text))
            r.font.size = Pt(7.5)
            r.font.color.rgb = RGBColor(57, 69, 64)

        # ---------- SIGNATORY / APPROVAL PANEL ----------
        signatories = ExportService._report_card_signatories(report_card)
        sig_title = doc.add_paragraph()
        sig_title.paragraph_format.space_before = Pt(7)
        sig_title.paragraph_format.space_after = Pt(2)
        ExportService._shade_paragraph_bg(sig_title, '17352C')
        r = sig_title.add_run('  REPORT CARD SIGNATORIES')
        r.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)

        sig = doc.add_table(rows=4, cols=3)
        sig.style = 'Table Grid'
        sig.alignment = WD_TABLE_ALIGNMENT.CENTER
        sig_data = [
            ('CLASS TEACHER', signatories['class_teacher_name']),
            ('HEADTEACHER / HEAD OF SCHOOL', signatories['headteacher_name']),
            ('PARENT / GUARDIAN', signatories['parent_name']),
        ]
        for i, (title, name) in enumerate(sig_data):
            c = sig.cell(0, i)
            c.text = title
            ExportService._shade_cell(c, 'EEF1EF')
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            rr = c.paragraphs[0].runs[0]
            rr.bold = True; rr.font.size = Pt(6.4); rr.font.color.rgb = RGBColor(45, 58, 52)

            c = sig.cell(1, i)
            c.text = str(name)
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            rr = c.paragraphs[0].runs[0]
            rr.bold = True; rr.font.size = Pt(7.2); rr.font.color.rgb = RGBColor(37, 50, 46)

            c = sig.cell(2, i)
            c.text = ''
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            signature_field = (signatories.get('class_teacher_signature') if i == 0 else
                               signatories.get('headteacher_signature') if i == 1 else None)
            signature_bytes = ExportService._file_bytes(signature_field)
            if signature_bytes:
                try:
                    c.paragraphs[0].add_run().add_picture(io.BytesIO(signature_bytes), width=Inches(1.45))
                except Exception as exc:
                    logger.warning('Could not embed report-card signature in Word export: %s', exc)
            c.paragraphs[0].add_run('\n____________________________')
            for rr in c.paragraphs[0].runs:
                rr.font.size = Pt(7)

            c = sig.cell(3, i)
            c.text = 'Signature & Date'
            c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            rr = c.paragraphs[0].runs[0]; rr.font.size = Pt(5.9); rr.font.color.rgb = RGBColor(105, 115, 110)

            for row_idx, margin in ((0, (30,35,25,35)), (1, (28,35,28,35)), (2, (8,35,3,35)), (3, (3,35,25,35))):
                ExportService._set_cell_margins(sig.cell(row_idx, i), *margin)

        # ---------- FOOTER ----------
        foot = sec.footer.paragraphs[0]
        foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
        foot.text = f'{school.name} • {report_card.academic_term} • {"OFFICIAL RECORD" if report_card.is_finalized else "DRAFT"} • EduAI School Management'
        for run in foot.runs:
            run.font.size = Pt(6.2)
            run.font.color.rgb = RGBColor(110, 120, 115)

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'attachment; filename="report_card_{student.admission_number}_{datetime.now():%Y%m%d}.docx"'
        doc.save(response)
        return response

    @staticmethod
    def export_risk_assessment_to_pdf(assessment):
        """Export a risk assessment to PDF"""
        context = {
            'assessment': assessment,
            'student': assessment.student,
            'generated_at': datetime.now(),
        }

        html_content = render_to_string('ai_engine/exports/risk_assessment_export_pdf.html', context)

        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Risk Assessment - {assessment.student.user.get_full_name()}</title>
            {ExportService._get_pdf_styles()}
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

        filename = f"risk_assessment_{assessment.student.user.get_full_name()}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return ExportService._generate_pdf(full_html, filename)

    @staticmethod
    def export_risk_assessment_to_doc(assessment):
        """Export a risk assessment to DOC (Word) format"""
        doc = Document()

        header = doc.add_heading(assessment.school.name if assessment.school else 'School', 0)
        header.alignment = WD_ALIGN_PARAGRAPH.CENTER

        title = doc.add_heading('Student Risk Assessment Report', 1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph(f"Student: {assessment.student.user.get_full_name()}")
        doc.add_paragraph(f"Admission Number: {assessment.student.admission_number}")
        doc.add_paragraph(f"Grade Level: {assessment.student.grade_level}")
        doc.add_paragraph(
            f"Class: {assessment.student.school_class.name if assessment.student.school_class else 'N/A'}")
        doc.add_paragraph(f"Assessment Date: {assessment.run.computed_at if assessment.run else datetime.now()}")
        doc.add_paragraph("")

        doc.add_heading('Risk Assessment Summary', 2)
        doc.add_paragraph(f"Risk Score: {assessment.risk_score}/100")
        doc.add_paragraph(f"Risk Band: {assessment.risk_band}")
        doc.add_paragraph("")

        doc.add_heading('Contributing Factors', 2)
        if assessment.contributing_factors:
            for factor in assessment.contributing_factors:
                doc.add_paragraph(f"• {factor['factor']}: {factor['detail']} (Points: {factor['points']})")
        else:
            doc.add_paragraph("No specific risk factors identified.")

        doc.add_paragraph("")

        doc.add_heading('Detailed Analysis', 2)
        doc.add_paragraph(
            f"Attendance Rate: {assessment.attendance_rate}%" if assessment.attendance_rate else "Attendance: N/A")
        doc.add_paragraph(
            f"Grade Average: {assessment.grade_average}%" if assessment.grade_average else "Grade Average: N/A")
        doc.add_paragraph(
            f"Fee Overdue: {assessment.fee_overdue_amount}" if assessment.fee_overdue_amount else "Fee Overdue: None")
        doc.add_paragraph("")

        if assessment.narrative:
            doc.add_heading('Narrative Summary', 2)
            doc.add_paragraph(assessment.narrative)
            doc.add_paragraph("")

        doc.add_paragraph("--- End of Risk Assessment ---")
        doc.add_paragraph(f"Generated by EduAI on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        filename = f"risk_assessment_{assessment.student.user.get_full_name()}_{datetime.now().strftime('%Y%m%d')}.docx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        doc.save(response)
        return response

    @staticmethod
    def export_finance_insight_to_pdf(snapshot, assessments):
        """Export finance insights to PDF"""
        context = {
            'snapshot': snapshot,
            'assessments': assessments,
            'generated_at': datetime.now(),
            'school_name': snapshot.get('school_name', 'School'),
        }

        html_content = render_to_string('ai_engine/exports/finance_insight_export_pdf.html', context)

        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Finance Insights</title>
            {ExportService._get_pdf_styles()}
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

        filename = f"finance_insights_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        return ExportService._generate_pdf(full_html, filename)