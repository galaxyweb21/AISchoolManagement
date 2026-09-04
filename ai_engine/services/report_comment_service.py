from django.db import transaction
from django.utils import timezone

from ai_engine.models import ReportCard, ReportCommentBatch
from ai_engine.services.report_card_engine import ReportCardEngine
from ai_engine.services.services import AIService


class ReportCommentService:
    """Generates safe, role-specific report-card comments without changing marks."""

    @staticmethod
    def _context(card):
        rows = card.subject_breakdown or []
        strengths = []
        needs_work = []
        for row in rows:
            subject = row.get('subject', 'Subject')
            total = row.get('total')
            if total is None:
                continue
            try:
                score = float(total)
            except (TypeError, ValueError):
                continue
            if score >= 70:
                strengths.append(f"{subject} ({score:.1f}%)")
            elif score < 50:
                needs_work.append(f"{subject} ({score:.1f}%)")

        attendance = (f"{card.attendance_rate:.1f}%" if card.attendance_rate is not None else "not recorded")
        position = (f"{card.overall_position} of {card.class_size}" if card.overall_position else "not available")
        return {
            'student': card.student.user.get_full_name(),
            'term': str(card.academic_term),
            'class_name': str(card.student.school_class or 'Not assigned'),
            'average': card.overall_average,
            'grade': card.overall_grade or 'N/A',
            'position': position,
            'attendance': attendance,
            'present': card.attendance_present,
            'absent': card.attendance_absent,
            'late': card.attendance_late,
            'conduct': card.conduct or 'Not recorded',
            'promotion': card.promotion_status or 'Not yet determined',
            'strengths': ', '.join(strengths[:5]) or 'No clear strength identified from the available results',
            'needs_work': ', '.join(needs_work[:5]) or 'No major weak area identified from the available results',
            'subjects': rows,
        }

    @classmethod
    def generate_teacher_comment(cls, card):
        c = cls._context(card)
        subject_lines = '\n'.join(
            f"- {r.get('subject','Subject')}: Class/30={r.get('class_score','—')}, Exam/70={r.get('exam_score','—')}, Final={r.get('total','—')}%, Grade={r.get('grade','—')}"
            for r in c['subjects']
        ) or '- No complete subject result is available.'
        prompt = f"""
Write the CLASS TEACHER'S report-card comment for the student below.
Use only the supplied facts. Do not invent achievements, diagnoses, behaviour, attendance events,
or family circumstances. Do not mention AI. Keep it to 3-5 professional sentences.
Focus on academic performance, strengths, subjects needing attention, effort/study habits where the
results support them, attendance where relevant, and one practical next-step recommendation.

Student: {c['student']}
Term: {c['term']}
Class: {c['class_name']}
Overall average: {c['average'] if c['average'] is not None else 'N/A'}%
Overall grade: {c['grade']}
Position: {c['position']}
Attendance: {c['attendance']} (Present {c['present']}, Absent {c['absent']}, Late {c['late']})
Conduct recorded: {c['conduct']}
Promotion status: {c['promotion']}
Strengths from results: {c['strengths']}
Areas needing attention: {c['needs_work']}
Subject results:
{subject_lines}
"""
        return AIService.generate_report_comment(prompt, role='class teacher')

    @classmethod
    def generate_headteacher_comment(cls, card):
        c = cls._context(card)
        subject_lines = '\n'.join(
            f"- {r.get('subject','Subject')}: Final={r.get('total','—')}%, Grade={r.get('grade','—')}"
            for r in c['subjects']
        ) or '- No complete subject result is available.'
        prompt = f"""
Write the HEADTEACHER'S final report-card comment for the student below.
Use only the supplied facts. Do not invent achievements, disciplinary incidents, health information,
or family circumstances. Do not mention AI. Keep it to 3-5 professional sentences.
Give a balanced whole-student summary covering achievement, attendance, conduct if recorded, progress
or effort only where supported by the data, promotion status if available, and an encouraging direction
for the next term. This is an official school document, so be concise, dignified and objective.

Student: {c['student']}
Term: {c['term']}
Class: {c['class_name']}
Overall average: {c['average'] if c['average'] is not None else 'N/A'}%
Overall grade: {c['grade']}
Position: {c['position']}
Attendance: {c['attendance']} (Present {c['present']}, Absent {c['absent']}, Late {c['late']})
Conduct recorded: {c['conduct']}
Promotion status: {c['promotion']}
Strongest areas from results: {c['strengths']}
Areas needing attention: {c['needs_work']}
Subject results:
{subject_lines}
"""
        return AIService.generate_report_comment(prompt, role='headteacher')

    @classmethod
    @transaction.atomic
    def generate_single(cls, card, user, comment_type, force=False):
        if card.is_finalized:
            raise ValueError('Finalized report cards are locked.')
        if comment_type not in ('teacher', 'headteacher'):
            raise ValueError('Invalid comment type.')
        if comment_type == 'teacher' and card.teacher_comment_source == 'MANUAL' and not force:
            return False, 'Manual teacher comment preserved.'
        if comment_type == 'headteacher' and card.headteacher_comment_source == 'MANUAL' and not force:
            return False, 'Manual headteacher comment preserved.'

        comment = cls.generate_teacher_comment(card) if comment_type == 'teacher' else cls.generate_headteacher_comment(card)
        if not comment:
            error = getattr(AIService, 'LAST_ERROR', '') or 'The Groq service returned no comment.'
            # Keep credentials out of the browser while giving the administrator
            # the actual reason (missing key, quota, invalid model, network, etc.).
            safe_error = error.replace(AIService._api_key(), '[configured key]') if AIService._api_key() else error
            raise ValueError(f'AI comment generation failed: {safe_error[:500]}')
        now = timezone.now()
        if comment_type == 'teacher':
            card.teacher_comment = comment.strip()
            card.teacher_comment_source = 'AI'
            card.teacher_comment_generated_at = now
        else:
            card.headteacher_comment = comment.strip()
            card.headteacher_comment_source = 'AI'
            card.headteacher_comment_generated_at = now
        card.edited_by = user
        card.edited_at = now
        card.save()
        return True, comment.strip()

    @classmethod
    def run_batch(cls, batch):
        batch.status = 'RUNNING'
        batch.error_message = ''
        batch.save(update_fields=['status', 'error_message'])
        try:
            qs = ReportCard.objects.filter(school=batch.school, academic_term=batch.academic_term).select_related('student__user', 'student__school_class')
            if batch.school_class_id:
                qs = qs.filter(student__school_class_id=batch.school_class_id)
            processed = skipped = teacher_count = head_count = failures = 0
            for card in qs.iterator():
                if card.is_finalized:
                    skipped += 1
                    continue
                processed += 1
                if batch.generate_teacher:
                    teacher_due = (not card.teacher_comment) if batch.only_missing else (batch.regenerate_ai and card.teacher_comment_source == 'AI')
                    if teacher_due:
                        try:
                            ok, _ = cls.generate_single(card, batch.triggered_by, 'teacher', force=False)
                            teacher_count += int(ok)
                        except Exception:
                            failures += 1
                if batch.generate_headteacher:
                    head_due = (not card.headteacher_comment) if batch.only_missing else (batch.regenerate_ai and card.headteacher_comment_source == 'AI')
                    if head_due:
                        try:
                            ok, _ = cls.generate_single(card, batch.triggered_by, 'headteacher', force=False)
                            head_count += int(ok)
                        except Exception:
                            failures += 1
            batch.students_processed = processed
            batch.students_skipped_finalized = skipped
            batch.teacher_comments_generated = teacher_count
            batch.headteacher_comments_generated = head_count
            batch.failures = failures
            batch.status = 'COMPLETE'
            batch.save(update_fields=['students_processed','students_skipped_finalized','teacher_comments_generated','headteacher_comments_generated','failures','status'])
        except Exception as exc:
            batch.status = 'FAILED'
            batch.error_message = str(exc)[:500]
            batch.save(update_fields=['status','error_message'])
        return batch
