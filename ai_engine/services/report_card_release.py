import io
import logging
from collections import defaultdict
from datetime import date

from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from ai_engine.models import ReportCard, ReportCardBatch, ReportCardDelivery, ReportCardReleaseBatch
from ai_engine.services.email_monitoring import EmailMonitoringService
from ai_engine.services.report_card_batch import ReportCardBatchService
from ai_engine.services.report_comment_service import ReportCommentService
from ai_engine.services.export_service import ExportService
from students.models import Student

logger = logging.getLogger(__name__)


class ReportCardReleaseService:
    """Enterprise end-of-term release pipeline.

    One release operation can:
      1. generate/refresh all draft report cards;
      2. generate missing AI teacher/headteacher comments;
      3. finalize eligible cards and snapshot signatures;
      4. create one A4 print pack ordered by class then student;
      5. email each student's individual finalized PDF to the linked parent.

    It deliberately refuses to auto-finalize an incomplete academic record.
    """

    @staticmethod
    def _is_complete(card):
        rows = card.subject_breakdown or []
        if not rows:
            return False, 'No subject results found.'
        incomplete = []
        for row in rows:
            if row.get('class_score') is None or row.get('exam_score') is None:
                incomplete.append(row.get('subject', 'Subject'))
        if incomplete:
            return False, 'Missing Class /30 or Exam /70 for: ' + ', '.join(incomplete[:8])
        return True, ''

    @classmethod
    def generate_cards(cls, school, term, user=None):
        batch = ReportCardBatchService.create_pending(school, term, user)
        return ReportCardBatchService.run(batch)

    @classmethod
    def generate_comments(cls, school, term, user=None):
        from ai_engine.models import ReportCommentBatch
        batch = ReportCommentBatch.objects.create(
            school=school,
            academic_term=term,
            triggered_by=user,
            only_missing=True,
            regenerate_ai=False,
            generate_teacher=True,
            generate_headteacher=True,
        )
        return ReportCommentService.run_batch(batch)

    @classmethod
    def finalize_ready_cards(cls, school, term, user):
        cards = (ReportCard.objects
                 .filter(school=school, academic_term=term, is_finalized=False)
                 .select_related('student__user', 'student__school_class'))
        finalized = 0
        blocked = []
        for card in cards:
            ready, reason = cls._is_complete(card)
            if not ready:
                blocked.append({'student': card.student.user.get_full_name(), 'reason': reason})
                continue
            try:
                ReportCardBatchService.finalize(card, user)
                finalized += 1
            except Exception as exc:
                blocked.append({'student': card.student.user.get_full_name(), 'reason': str(exc)[:300]})
        return finalized, blocked

    @classmethod
    def build_print_pack(cls, school, term, release_batch=None):
        """Create one A4 portrait PDF, one report per page, grouped by class."""
        cards = (ReportCard.objects
                 .filter(school=school, academic_term=term, is_finalized=True)
                 .select_related('student__user', 'student__school_class', 'student__grade_level')
                 .order_by('student__school_class__name', 'student__user__last_name', 'student__user__first_name'))

        if not cards.exists():
            return None, 0

        # The existing single-card exporter owns the authoritative styling and
        # context. We reuse its template but add a page break after every card.
        pieces = []
        for card in cards:
            computed = ExportService._report_card_data(card)
            signatories = ExportService._report_card_signatories(card)
            context = {
                'report_card': card,
                'student': card.student,
                'academic_term': card.academic_term,
                'subject_breakdown': computed.get('subject_breakdown', []),
                'generated_at': timezone.now(),
                'school_logo': ExportService._safe_file_url(getattr(school, 'logo', None)),
                'student_photo': ExportService._safe_file_url(getattr(getattr(card.student, 'user', None), 'profile_picture', None)),
                **signatories,
            }
            context['teacher_signature_url'] = ExportService._signature_data_uri(signatories.get('class_teacher_signature')) or ExportService._safe_file_url(signatories.get('class_teacher_signature'))
            context['headteacher_signature_url'] = ExportService._signature_data_uri(signatories.get('headteacher_signature')) or ExportService._safe_file_url(signatories.get('headteacher_signature'))
            body = render_to_string('ai_engine/exports/report_card_export_pdf.html', context)
            pieces.append(f'<div class="report-page">{body}</div>')

        css = '''<style>
        @page{size:A4 portrait;margin:7mm 7mm 8mm 7mm}
        body{font-family:Helvetica,Arial,sans-serif;color:#25322e;font-size:8pt;line-height:1.25;margin:0;background:#fff}
        .report-page{page-break-after:always;page-break-inside:avoid;min-height:270mm}
        .report-page:last-child{page-break-after:auto}
        table{width:100%;border-collapse:collapse}
        .report-sheet{border:1.2px solid #25322e;padding:5px 6px 6px;background:#fff}
        .school-header{border:1.2px solid #25322e;background:#17352c}
        .header-side{vertical-align:middle;text-align:center}.left-side{width:16%;padding:6px}.right-side{width:16%;padding:5px}
        .header-center{width:68%;text-align:center;padding:7px 5px;vertical-align:middle}
        .school-logo{width:55px;height:55px}.school-name{color:#fff;font-size:16pt;font-weight:bold;letter-spacing:.5px}
        .school-contact{color:#dce6e1;font-size:6.8pt;margin-top:2px}.report-title{display:inline-block;background:#fff;color:#17352c;font-size:9.5pt;font-weight:bold;letter-spacing:.8px;padding:4px 12px;margin-top:6px}.period{color:#e3ebe7;font-size:7.2pt;font-weight:bold;margin-top:4px}
        .student-photo{width:62px;height:72px;border:2px solid #fff}.photo-placeholder{width:62px;height:72px;border:1px solid #dce6e1;color:#dce6e1;font-size:6.5pt;font-weight:bold;text-align:center;padding-top:22px}
        .identity{margin-top:6px;border:1px solid #8b9590}.identity td{border:1px solid #cbd1ce;padding:4px 6px}.identity-label{background:#eef1ef;color:#59645f;font-size:6.5pt;font-weight:bold;letter-spacing:.3px;width:14%}.identity-value{width:36%;color:#28342f}.identity-value.name{font-weight:bold}
        .summary{margin-top:6px;border:1px solid #aab3af}.summary td{width:20%;text-align:center;border-right:1px solid #cbd1ce;padding:5px 2px;background:#f7f8f7}.summary td:last-child{border-right:0}.k-label{display:block;color:#66716c;font-size:6pt;font-weight:bold;letter-spacing:.5px}.k-value{display:block;color:#17352c;font-size:10.5pt;font-weight:bold;margin-top:1px}.k-value small{font-size:6.5pt;color:#65706b}.k-value.promotion{font-size:7.5pt;margin-top:3px}
        .section-bar{background:#17352c;color:#fff;font-size:8.2pt;font-weight:bold;letter-spacing:.55px;padding:5px 7px;margin-top:7px;border-left:4px solid #c9a14a}.results{border:1px solid #7f8985}.results th{background:#eef1ef;color:#24312d;border:1px solid #9aa39f;padding:4px 3px;font-size:6.6pt;font-weight:bold;text-align:center}.results th.subject,.results th.remark{text-align:left}.results th small{font-size:5.8pt;font-weight:normal}.results td{border:1px solid #d4d9d6;padding:4px 4px;font-size:7.3pt}.results tbody tr:nth-child(even){background:#f8f9f8}.subject{text-align:left;width:24%}.remark{text-align:left;width:20%;color:#56615c}.center{text-align:center}.strong{font-weight:bold;color:#25322e}.final{font-weight:bold}.grade{font-weight:bold;color:#17352c}.empty{text-align:center;color:#7b8580;padding:9px}.results tfoot td{background:#eef1ef;border-top:1.2px solid #7f8985;font-weight:bold}.total-label{text-align:right;color:#52605a;font-size:6.7pt}.total-value{text-align:center;color:#17352c;font-size:8.5pt}.scale-note{color:#69736e;font-size:6.2pt;font-style:italic;margin-top:3px}
        .attendance{border:1px solid #aab3af}.attendance td{border:1px solid #d1d6d3;text-align:center;padding:5px 4px;background:#fafbfa}.attendance .wide{text-align:left}.a-label{display:block;color:#69736e;font-size:5.9pt;font-weight:bold;letter-spacing:.35px;margin-bottom:1px}.attendance strong{font-size:7.5pt;color:#25322e}
        .comments{margin-top:6px}.comments td{width:50%;vertical-align:top;padding-right:4px}.comments td+td{padding-right:0;padding-left:4px}.comment-heading{background:#eef1ef;color:#17352c;border:1px solid #c7ceca;border-bottom:0;font-size:6.8pt;font-weight:bold;padding:4px 6px}.comment-box{border:1px solid #c7ceca;background:#fbfcfb;padding:6px;min-height:34px;color:#39453f;line-height:1.3}
        .signature-heading{margin-top:7px;margin-bottom:0}.signatures{border:1px solid #aab3af}.signatures td{text-align:center;width:33.33%;border:1px solid #d1d6d3;padding:3px 6px;color:#3e4944}.signatures .sig-head td{background:#eef1ef;color:#25322e;font-size:6.2pt;padding:4px 5px}.signatures .sig-name td{font-size:7.1pt;font-weight:bold;color:#25322e;padding:4px 5px}.signature-image{display:block;width:auto;max-width:125px;max-height:30px;height:auto;object-fit:contain;margin:0 auto 2px auto}.sig-image-row td{height:36px;vertical-align:bottom;overflow:hidden}.signature-line{border-top:1px solid #59645f;height:2px}.signatures .sig-caption td{border-top:0;color:#7b8580;font-size:5.8pt;padding-top:0}.record-note{margin-top:7px;border:1px solid #c8cfcc;background:#f6f8f7;color:#59645f;padding:4px 6px;font-size:6.2pt;text-align:center}.footer{text-align:center;color:#7b8580;font-size:5.8pt;margin-top:4px}
        </style>'''
        html = '<!DOCTYPE html><html><head><meta charset="utf-8">' + css + '</head><body>' + ''.join(pieces) + '</body></html>'
        response = ExportService._generate_pdf(html, f'report_cards_{term.id}.pdf')
        # ExportService returns HttpResponse; extract PDF bytes for storage/email.
        data = bytes(response.content)
        return data, cards.count()

    @classmethod
    def email_cards(cls, release_batch):
        cards = (ReportCard.objects.filter(school=release_batch.school, academic_term=release_batch.academic_term, is_finalized=True)
                 .select_related('student__user', 'student__parent', 'student__school_class'))
        sent = failed = skipped = 0
        for card in cards.iterator():
            parent = getattr(card.student, 'parent', None)
            recipient = (getattr(parent, 'email', '') or '').strip()
            delivery, _ = ReportCardDelivery.objects.get_or_create(
                release_batch=release_batch, report_card=card,
                defaults={'recipient_email': recipient, 'status': 'PENDING'}
            )
            if delivery.status == 'SENT':
                sent += 1
                continue
            if recipient and delivery.recipient_email != recipient:
                delivery.recipient_email = recipient
                delivery.status = 'PENDING'
                delivery.next_retry_at = None
                delivery.save(update_fields=['recipient_email', 'status', 'next_retry_at'])
            result = EmailMonitoringService.send_report_card_delivery(delivery)
            if result == 'SENT': sent += 1
            elif result == 'SKIPPED': skipped += 1
            else: failed += 1
        return sent, failed, skipped

    @classmethod
    def run(cls, release_batch, user=None):
        release_batch.status = 'RUNNING'
        release_batch.started_at = timezone.now()
        release_batch.save(update_fields=['status', 'started_at'])
        try:
            generated = cls.generate_cards(release_batch.school, release_batch.academic_term, user)
            release_batch.generated_count = generated.students_processed
            # Generate missing official comments before the finalization gate.
            # A comment failure never changes marks and never blocks a complete
            # academic record from being finalized.
            try:
                cls.generate_comments(release_batch.school, release_batch.academic_term, user)
            except Exception:
                logger.exception('Automatic report-card comment generation failed; continuing with release.')
            finalized, blocked = cls.finalize_ready_cards(release_batch.school, release_batch.academic_term, user)
            release_batch.finalized_count = finalized
            release_batch.blocked_count = len(blocked)
            release_batch.blocked_details = blocked[:100]

            if release_batch.email_parents and finalized:
                sent, failed, skipped = cls.email_cards(release_batch)
                release_batch.emailed_count = sent
                release_batch.email_failed_count = failed
                release_batch.email_skipped_count = skipped

            if release_batch.generate_print_pack and finalized:
                pdf_bytes, count = cls.build_print_pack(release_batch.school, release_batch.academic_term, release_batch)
                if pdf_bytes:
                    filename = f'report_cards_{release_batch.school.subdomain}_{release_batch.academic_term.id}.pdf'
                    release_batch.print_pack.save(filename, ContentFile(pdf_bytes), save=False)
                    release_batch.print_pack_generated_at = timezone.now()
                    release_batch.print_pack_count = count

            release_batch.status = 'COMPLETE' if (not blocked and release_batch.email_failed_count == 0 and release_batch.email_skipped_count == 0) else 'PARTIAL'
            release_batch.completed_at = timezone.now()
            release_batch.save()
        except Exception as exc:
            release_batch.status = 'FAILED'
            release_batch.error_message = str(exc)[:1000]
            release_batch.completed_at = timezone.now()
            release_batch.save(update_fields=['status', 'error_message', 'completed_at'])
            logger.exception('Automatic report-card release failed')
        return release_batch
