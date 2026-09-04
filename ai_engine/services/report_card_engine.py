"""Enterprise Ghana-style end-of-term results engine.

Official terminal results use an explicit Class Score /30 and Examination /70.
TerminalResult is authoritative for V8.2. Older Assessment/Grade records remain
supported as a backwards-compatible fallback, so existing V8 data is not lost.
AI is never used for numerical results, grades, positions or attendance.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q

from assessments.models import Grade, TerminalResult
from attendance.models import Attendance


GRADE_SCALE = (
    (90, 'A+', 'Outstanding'),
    (80, 'A', 'Excellent'),
    (70, 'B', 'Very Good'),
    (60, 'C', 'Good'),
    (50, 'D', 'Satisfactory'),
    (40, 'E', 'Pass'),
    (0, 'F', 'Needs Improvement'),
)
DEFAULT_CA_WEIGHT = Decimal('30')
DEFAULT_EXAM_WEIGHT = Decimal('70')


def _q(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def grade_for_percentage(value):
    if value is None:
        return {'code': '', 'label': '', 'remark': ''}
    value = float(value)
    for minimum, code, remark in GRADE_SCALE:
        if value >= minimum:
            return {'code': code, 'label': code, 'remark': remark}
    return {'code': 'F', 'label': 'F', 'remark': 'Needs Improvement'}


class ReportCardEngine:
    @staticmethod
    def _term_grades(student, academic_term):
        return Grade.objects.filter(student=student).filter(
            Q(assessment__academic_term=academic_term) |
            Q(
                assessment__academic_term__isnull=True,
                assessment__created_at__date__gte=academic_term.start_date,
                assessment__created_at__date__lte=academic_term.end_date,
            )
        ).select_related('assessment')

    @staticmethod
    def compute_attendance(student, academic_term):
        records = Attendance.objects.filter(
            student=student,
            date__gte=academic_term.start_date,
            date__lte=academic_term.end_date,
        )
        total = records.count()
        if not total:
            return {'rate': None, 'present': 0, 'absent': 0, 'late': 0, 'total': 0}
        present = records.filter(status__in=['PRESENT', 'LATE']).count()
        absent = records.filter(status='ABSENT').count()
        late = records.filter(status='LATE').count()
        return {
            'rate': round((present / total) * 100, 1),
            'present': present,
            'absent': absent,
            'late': late,
            'total': total,
        }

    @classmethod
    def _terminal_rows(cls, student, academic_term):
        return list(TerminalResult.objects.filter(
            student=student, academic_term=academic_term,
            school=student.school,
        ).order_by('subject'))

    @classmethod
    def _legacy_rows(cls, student, academic_term, excluded_subjects=None):
        excluded_subjects = {str(x).lower() for x in (excluded_subjects or set())}
        grouped = defaultdict(lambda: {'ca': [], 'exam': [], 'all': []})
        for grade in cls._term_grades(student, academic_term):
            assessment = grade.assessment
            if assessment.subject.lower() in excluded_subjects or not assessment.max_score:
                continue
            pct = Decimal(str(grade.score_achieved)) / Decimal(str(assessment.max_score)) * Decimal('100')
            item = {
                'assessment': assessment.title or assessment.subject,
                'type': assessment.assessment_type,
                'score': float(grade.score_achieved),
                'max_score': int(assessment.max_score),
                'percentage': round(float(pct), 1),
            }
            bucket = grouped[assessment.subject]
            bucket['all'].append(item)
            if assessment.score_component == 'EXAM' or assessment.assessment_type == 'EXAM':
                bucket['exam'].append(pct)
            else:
                bucket['ca'].append(pct)
        results = []
        for subject, bucket in sorted(grouped.items()):
            ca_pct = (sum(bucket['ca']) / Decimal(len(bucket['ca']))) if bucket['ca'] else None
            exam_pct = (sum(bucket['exam']) / Decimal(len(bucket['exam']))) if bucket['exam'] else None
            ca_score = (ca_pct * Decimal('0.30')) if ca_pct is not None else None
            exam_score = (exam_pct * Decimal('0.70')) if exam_pct is not None else None
            final = _q(ca_score + exam_score) if ca_score is not None and exam_score is not None else None
            g = grade_for_percentage(final)
            results.append({
                'subject': subject,
                'class_score': float(_q(ca_score)) if ca_score is not None else None,
                'exam_score': float(_q(exam_score)) if exam_score is not None else None,
                'ca_average': round(float(ca_pct), 1) if ca_pct is not None else None,
                'exam_average': round(float(exam_pct), 1) if exam_pct is not None else None,
                'average': float(final) if final is not None else None,
                'total': float(final) if final is not None else None,
                'grade': g['code'] if final is not None else '',
                'remark': g['remark'] if final is not None else '',
                'status': 'Complete' if final is not None else 'Incomplete',
                'assessment_count': len(bucket['all']),
                'assessments': bucket['all'],
            })
        return results

    @classmethod
    def compute_subject_breakdown(cls, student, academic_term):
        """Return the canonical Class /30 + Exam /70 breakdown.

        TerminalResult is authoritative, but legacy Assessment/Grade data is used
        to fill a missing component when older results exist. This prevents a
        partially-created terminal row from hiding valid historical marks.
        """
        terminal = cls._terminal_rows(student, academic_term)
        legacy = cls._legacy_rows(student, academic_term)
        legacy_by_subject = {str(r['subject']).strip().lower(): r for r in legacy}
        results = []
        handled = set()

        for row in terminal:
            key = str(row.subject).strip().lower()
            handled.add(key)
            legacy_row = legacy_by_subject.get(key)
            class_score = row.class_score
            exam_score = row.exam_score

            # Backward-compatible repair/fill for older Grade records. Never
            # replace a real TerminalResult value with a legacy value.
            if class_score is None and legacy_row and legacy_row.get('class_score') is not None:
                class_score = Decimal(str(legacy_row['class_score']))
            if exam_score is None and legacy_row and legacy_row.get('exam_score') is not None:
                exam_score = Decimal(str(legacy_row['exam_score']))

            final = _q(class_score + exam_score) if class_score is not None and exam_score is not None else None
            g = grade_for_percentage(final)
            results.append({
                'subject': row.subject,
                'class_score': float(_q(class_score)) if class_score is not None else None,
                'exam_score': float(_q(exam_score)) if exam_score is not None else None,
                'ca_average': round(float((class_score / Decimal('30')) * Decimal('100')), 1) if class_score is not None else None,
                'exam_average': round(float((exam_score / Decimal('70')) * Decimal('100')), 1) if exam_score is not None else None,
                'average': float(final) if final is not None else None,
                'total': float(final) if final is not None else None,
                'grade': (row.grade or g['code']) if final is not None else '',
                'remark': (row.remark or g['remark']) if final is not None else '',
                'status': 'Complete' if final is not None else row.get_status_display(),
                'assessment_count': 2 if class_score is not None or exam_score is not None else 0,
                'assessments': [],
            })

        # Subjects with only legacy Assessment/Grade records remain visible.
        results.extend(r for r in legacy if str(r['subject']).strip().lower() not in handled)
        return sorted(results, key=lambda x: str(x['subject']).lower())

    @classmethod
    def compute_class_ranking(cls, student, academic_term):
        school_class = student.school_class
        if not school_class:
            return None, 0
        students = list(school_class.student_enrollments.filter(is_active=True).select_related('user'))
        scores = []
        for candidate in students:
            rows = [r for r in cls.compute_subject_breakdown(candidate, academic_term) if r.get('total') is not None]
            if rows:
                avg = sum(Decimal(str(r['total'])) for r in rows) / Decimal(str(len(rows)))
                total = sum(Decimal(str(r['total'])) for r in rows)
                scores.append((candidate.pk, avg, total))
        scores.sort(key=lambda x: (-x[1], -x[2], str(x[0])))
        position = next((i for i, row in enumerate(scores, 1) if row[0] == student.pk), None)
        return position, len(scores)

    @classmethod
    def repair_finalized_snapshot(cls, report_card, save=True):
        """Fill missing Class /30 and Exam /70 cells on a FINALIZED card.

        A card can be finalized (locked) before every subject was fully graded,
        or a teacher can correct/enter a TerminalResult after finalization. The
        locked snapshot then keeps showing '-' forever because finalized cards
        are never recomputed. This repairs only the blank score cells from the
        live TerminalResult data — it never overwrites a score that is already
        present in the snapshot, and it never touches the official/locked
        overall_average, overall_grade, overall_position, etc.
        """
        snapshot = report_card.subject_breakdown or []
        if not snapshot:
            return snapshot
        live_by_subject = {
            str(row['subject']).strip().lower(): row
            for row in cls.compute_subject_breakdown(report_card.student, report_card.academic_term)
        }
        # Numeric fields are missing only when None (0 is a real score).
        # Text fields are missing when None OR '' (an empty string is how a
        # blank grade/remark/status is stored, not a real value).
        numeric_fillable = ('class_score', 'exam_score', 'ca_average', 'exam_average', 'total', 'average')
        text_fillable = ('grade', 'remark', 'status')
        repaired = []
        changed = False
        for row in snapshot:
            row = dict(row)
            live = live_by_subject.get(str(row.get('subject', '')).strip().lower())
            if live:
                for key in numeric_fillable:
                    if row.get(key) is None and live.get(key) is not None:
                        row[key] = live[key]
                        changed = True
                for key in text_fillable:
                    if not row.get(key) and live.get(key):
                        row[key] = live[key]
                        changed = True
            repaired.append(row)
        if changed and save:
            report_card.subject_breakdown = repaired
            report_card.save(update_fields=['subject_breakdown', 'updated_at'])
        return repaired

    @classmethod
    def refresh_report_card_snapshot(cls, report_card, save=True):
        """Recalculate the numerical report-card snapshot from authoritative results.

        For draft cards this keeps the stored JSON in sync with TerminalResult, so
        report cards generated before marks were entered never display stale dashes.
        Finalized cards keep their locked official average/grade/position, but any
        subject row still missing Class /30 or Exam /70 is repaired from the live
        TerminalResult data (see repair_finalized_snapshot).
        """
        if report_card.is_finalized:
            subject_breakdown = cls.repair_finalized_snapshot(report_card, save=save)
            return report_card, {
                'subject_breakdown': subject_breakdown,
                'overall_average': report_card.overall_average,
                'overall_grade': report_card.overall_grade,
                'overall_remark': report_card.overall_remark,
                'total_marks': report_card.total_marks,
                'total_possible': report_card.total_possible,
                'overall_position': report_card.overall_position,
                'class_size': report_card.class_size,
                'attendance_rate': report_card.attendance_rate,
                'attendance': {
                    'present': report_card.attendance_present,
                    'absent': report_card.attendance_absent,
                    'late': report_card.attendance_late,
                    'total': report_card.attendance_total,
                },
                'ca_weight': report_card.ca_weight,
                'exam_weight': report_card.exam_weight,
            }

        computed = cls.compute(report_card.student, report_card.academic_term)
        report_card.subject_breakdown = computed['subject_breakdown']
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
        if save:
            report_card.save(update_fields=[
                'subject_breakdown', 'overall_average', 'overall_grade', 'overall_remark',
                'total_marks', 'total_possible', 'overall_position', 'class_size',
                'attendance_rate', 'attendance_present', 'attendance_absent',
                'attendance_late', 'attendance_total', 'ca_weight', 'exam_weight', 'updated_at'
            ])
        return report_card, computed

    @classmethod
    def compute(cls, student, academic_term):
        subjects = cls.compute_subject_breakdown(student, academic_term)
        attendance = cls.compute_attendance(student, academic_term)
        complete_subjects = [row for row in subjects if row.get('total') is not None]
        overall = None
        total_marks = Decimal('0')
        total_possible = Decimal('0')
        if complete_subjects:
            overall = _q(sum(Decimal(str(row['total'])) for row in complete_subjects) / Decimal(str(len(complete_subjects))))
            total_marks = _q(sum(Decimal(str(row['total'])) for row in complete_subjects))
            total_possible = Decimal(str(len(complete_subjects) * 100))
        position, class_size = cls.compute_class_ranking(student, academic_term)
        overall_grade = grade_for_percentage(overall)
        return {
            'overall_average': float(overall) if overall is not None else None,
            'overall_grade': overall_grade['code'] if overall is not None else '',
            'overall_remark': overall_grade['remark'] if overall is not None else '',
            'attendance_rate': attendance['rate'],
            'attendance': attendance,
            'subject_breakdown': subjects,
            'total_marks': float(total_marks),
            'total_possible': float(total_possible),
            'overall_position': position,
            'class_size': class_size,
            'ca_weight': float(DEFAULT_CA_WEIGHT),
            'exam_weight': float(DEFAULT_EXAM_WEIGHT),
        }
