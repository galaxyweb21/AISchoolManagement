from django.db import transaction
from django.core.files.base import ContentFile
from django.utils import timezone

from students.models import Student
from ai_engine.models import ReportCardBatch, ReportCard
from ai_engine.services.report_card_engine import ReportCardEngine
from ai_engine.services.services import AIService


class ReportCardBatchService:
    @staticmethod
    def create_pending(school, academic_term, triggered_by=None):
        return ReportCardBatch.objects.create(
            school=school, academic_term=academic_term,
            triggered_by=triggered_by, status='PENDING'
        )

    @classmethod
    def run(cls, batch):
        batch.status = 'RUNNING'
        batch.save(update_fields=['status'])
        try:
            school = batch.school
            term = batch.academic_term
            students = Student.objects.filter(school=school, is_active=True).select_related('user', 'school_class', 'grade_level')
            processed = skipped = 0
            for student in students:
                existing = ReportCard.objects.filter(student=student, academic_term=term).first()
                if existing and existing.is_finalized:
                    skipped += 1
                    continue
                computed = ReportCardEngine.compute(student, term)
                preserve = bool(existing and existing.edited_by_id)
                if preserve:
                    narrative = existing.ai_narrative
                    generated_at = existing.ai_last_generated_at
                else:
                    try:
                        narrative = AIService.generate_report_card_narrative(
                            student_name=student.user.get_full_name(),
                            academic_term_name=str(term),
                            overall_average=computed['overall_average'],
                            subject_breakdown=computed['subject_breakdown'],
                            attendance_rate=computed['attendance_rate'],
                        )
                    except Exception:
                        # AI is an enhancement, never a dependency for official marks.
                        narrative = ''
                    generated_at = timezone.now() if narrative else None
                defaults = {
                    'school': school, 'last_batch': batch,
                    'overall_average': computed['overall_average'],
                    'overall_grade': computed['overall_grade'],
                    'overall_remark': computed['overall_remark'],
                    'total_marks': computed['total_marks'],
                    'total_possible': computed['total_possible'],
                    'overall_position': computed['overall_position'],
                    'class_size': computed['class_size'],
                    'attendance_rate': computed['attendance_rate'],
                    'attendance_present': computed['attendance']['present'],
                    'attendance_absent': computed['attendance']['absent'],
                    'attendance_late': computed['attendance']['late'],
                    'attendance_total': computed['attendance']['total'],
                    'ca_weight': computed['ca_weight'], 'exam_weight': computed['exam_weight'],
                    'subject_breakdown': computed['subject_breakdown'],
                    'ai_narrative': narrative, 'ai_last_generated_at': generated_at,
                }
                ReportCard.objects.update_or_create(
                    student=student, academic_term=term, defaults=defaults
                )
                processed += 1
            batch.students_processed = processed
            batch.students_skipped_finalized = skipped
            batch.status = 'COMPLETE'
            batch.save(update_fields=['students_processed', 'students_skipped_finalized', 'status'])
        except Exception as exc:
            batch.status = 'FAILED'
            batch.error_message = str(exc)[:500]
            batch.save(update_fields=['status', 'error_message'])
        return batch

    @staticmethod
    def regenerate_single(report_card):
        computed = ReportCardEngine.compute(report_card.student, report_card.academic_term)
        report_card.overall_average = computed['overall_average']
        report_card.overall_grade = computed['overall_grade']
        report_card.overall_remark = computed['overall_remark']
        report_card.total_marks = computed['total_marks']
        report_card.total_possible = computed['total_possible']
        report_card.overall_position = computed['overall_position']
        report_card.class_size = computed['class_size']
        report_card.attendance_rate = computed['attendance_rate']
        report_card.attendance_present = computed['attendance']['present']
        report_card.attendance_absent = computed['attendance']['absent']
        report_card.attendance_late = computed['attendance']['late']
        report_card.attendance_total = computed['attendance']['total']
        report_card.ca_weight = computed['ca_weight']
        report_card.exam_weight = computed['exam_weight']
        report_card.subject_breakdown = computed['subject_breakdown']
        try:
            report_card.ai_narrative = AIService.generate_report_card_narrative(
                student_name=report_card.student.user.get_full_name(),
                academic_term_name=str(report_card.academic_term),
                overall_average=computed['overall_average'],
                subject_breakdown=computed['subject_breakdown'],
                attendance_rate=computed['attendance_rate'],
            )
            report_card.ai_last_generated_at = timezone.now()
        except Exception:
            report_card.ai_narrative = ''
            report_card.ai_last_generated_at = None
        report_card.edited_by = None
        report_card.edited_at = None
        report_card.save()
        return report_card

    @staticmethod
    def _copy_signature_snapshot(report_card, staff_profile, target_field_name, name_field_name, role_slug):
        """Copy a staff signature into the report-card snapshot field.

        The source may live on Cloudinary/remote storage, so the copy is made
        through Django's storage API rather than accessing ``.path``.
        """
        if not staff_profile or not getattr(staff_profile, 'signature_is_active', True):
            return False
        source = getattr(staff_profile, 'signature_image', None)
        if not source:
            return False
        try:
            source.open('rb')
            try:
                data = source.read()
            finally:
                try:
                    source.close()
                except Exception:
                    pass
            if not data:
                return False

            target = getattr(report_card, target_field_name)
            extension = 'png'
            original_name = str(getattr(source, 'name', '') or '').lower()
            if original_name.endswith('.jpg') or original_name.endswith('.jpeg'):
                extension = 'jpg'
            elif original_name.endswith('.webp'):
                extension = 'webp'
            filename = f"{report_card.id}_{role_slug}.{extension}"
            target.save(filename, ContentFile(data), save=False)
            setattr(report_card, name_field_name, staff_profile.user.get_full_name().strip())
            return True
        except Exception:
            return False

    @staticmethod
    def _resolve_report_card_signature_profiles(report_card):
        """Return the current class-teacher and headteacher StaffProfile rows."""
        student = report_card.student
        school = report_card.school
        teacher_profile = None
        head_profile = None

        school_class = getattr(student, 'school_class', None)
        if school_class:
            try:
                teacher = getattr(school_class, 'homeroom_teacher', None)
                if teacher and getattr(teacher, 'user', None):
                    teacher_profile = getattr(teacher.user, 'staff_profile', None)
            except Exception:
                pass
            if not teacher_profile:
                try:
                    from academics.models import TeacherClassAssignment
                    assignment = (TeacherClassAssignment.objects
                                   .filter(school=school, school_class=school_class, is_active=True)
                                   .select_related('teacher__user__staff_profile')
                                   .order_by('-assigned_at')
                                   .first())
                    if assignment and assignment.teacher and assignment.teacher.user:
                        teacher_profile = getattr(assignment.teacher.user, 'staff_profile', None)
                except Exception:
                    pass

        try:
            from staff.models import StaffProfile
            head_profile = (StaffProfile.objects
                            .filter(school=school, is_active=True, is_headteacher=True)
                            .select_related('user').order_by('id').first())
            if not head_profile:
                head_profile = (StaffProfile.objects
                                .filter(school=school, staff_position='SCHOOL_ADMIN', is_active=True)
                                .select_related('user').order_by('id').first())
        except Exception:
            pass
        return teacher_profile, head_profile

    @classmethod
    @transaction.atomic
    def finalize(cls, report_card, user):
        """Finalize the report and capture the authorized signatures once."""
        teacher_profile, head_profile = cls._resolve_report_card_signature_profiles(report_card)

        # Clear any previous snapshots first. This matters when a report is
        # unlocked, a staff signature is later disabled/replaced, and the card
        # is finalized again. The new official record must never retain stale
        # signature artwork.
        for field_name, name_field in (
            ('teacher_signature_snapshot', 'teacher_signature_name'),
            ('headteacher_signature_snapshot', 'headteacher_signature_name'),
        ):
            existing = getattr(report_card, field_name, None)
            if existing:
                try:
                    existing.delete(save=False)
                except Exception:
                    pass
            setattr(report_card, field_name, None)
            setattr(report_card, name_field, '')

        cls._copy_signature_snapshot(
            report_card, teacher_profile,
            'teacher_signature_snapshot', 'teacher_signature_name', 'teacher'
        )
        cls._copy_signature_snapshot(
            report_card, head_profile,
            'headteacher_signature_snapshot', 'headteacher_signature_name', 'headteacher'
        )

        report_card.is_finalized = True
        report_card.finalized_by = user
        report_card.finalized_at = timezone.now()
        report_card.save(update_fields=[
            'is_finalized', 'finalized_by', 'finalized_at',
            'teacher_signature_snapshot', 'teacher_signature_name',
            'headteacher_signature_snapshot', 'headteacher_signature_name',
        ])
        return report_card
