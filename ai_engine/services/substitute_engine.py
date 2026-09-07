# ai_engine/services/substitute_engine.py
"""
Substitute-teacher auto-cover. Same split as every other engine here: the
actual assignment (who covers which period) is deterministic and
explainable - who's free, who's qualified, who isn't already overloaded -
because it's a real operational decision an admin has to stand behind, not
something to leave to a model's judgment. The AI's job is limited to
drafting the handover note.
"""
from academics.models import Timetable, TimetableEntry
from staff.models import Teacher, TeacherAbsence
from school.models import AcademicTerm
from .services import AIService
from ai_engine.models import *

class SubstituteCoverError(Exception):
    """Raised when there's no published timetable to work from for the
    absence's date - surfaced directly to the admin triggering this."""


class SubstituteMatchService:

    @staticmethod
    def _teacher_already_busy(teacher, timeslot, exclude_entry_id, published_timetable):
        return TimetableEntry.objects.filter(
            timetable=published_timetable, teacher=teacher, timeslot=timeslot
        ).exclude(id=exclude_entry_id).exists()

    @classmethod
    def find_candidates(cls, entry, absence, published_timetable):
        """
        Ranked list of dicts (best first): {'teacher', 'score', 'qualified', 'reasons'}
        for covering one TimetableEntry. The score is only for ordering the
        candidate list sensibly - it's shown as "why this pick" reasons in
        the UI, not presented as some precise probability.
        """
        school = entry.school_class.school
        date = absence.date

        absent_teacher_ids = set(
            TeacherAbsence.objects.filter(school=school, date=date).values_list('teacher_id', flat=True)
        )
        candidates = Teacher.objects.filter(school=school, is_active=True).exclude(
            id__in=absent_teacher_ids
        ).prefetch_related('subjects')

        results = []
        for teacher in candidates:
            if cls._teacher_already_busy(teacher, entry.timeslot, entry.id, published_timetable):
                continue  # hard exclude - can't be in two places at once

            reasons = []
            score = 50  # baseline: free at this timeslot and not absent

            qualified = entry.subject in teacher.subjects.all()
            if qualified:
                score += 30
                reasons.append(f"Qualified in {entry.subject.name}")
            else:
                reasons.append(f"Not a {entry.subject.name} specialist - general cover only")

            periods_that_day = TimetableEntry.objects.filter(
                timetable=published_timetable, teacher=teacher, timeslot__day=entry.timeslot.day
            ).count()
            score += max(0, 10 - periods_that_day)
            if periods_that_day == 0:
                reasons.append("Free the rest of the day")

            weekly_periods = TimetableEntry.objects.filter(timetable=published_timetable, teacher=teacher).count()
            if weekly_periods >= teacher.max_periods_per_week:
                score -= 15
                reasons.append("Already at/over their normal weekly load")

            results.append({'teacher': teacher, 'score': score, 'qualified': qualified, 'reasons': reasons})

        results.sort(key=lambda r: r['score'], reverse=True)
        return results


class CoverPlanService:

    @staticmethod
    def _find_published_timetable(school, date):
        term = AcademicTerm.objects.filter(
            academic_year__school=school, start_date__lte=date, end_date__gte=date
        ).first()
        if not term:
            return None, None
        timetable = Timetable.objects.filter(school=school, academic_term=term, is_published=True).first()
        return term, timetable

    @classmethod
    def generate_for_absence(cls, absence, generated_by=None):
        """
        Builds/refreshes SubstituteAssignment rows for every period the
        absent teacher had scheduled that day. Idempotent and safe to
        re-run: a CONFIRMED assignment is left untouched entirely (a human
        decision doesn't get silently recomputed), and an edited handover
        note is preserved even when the underlying suggestion refreshes.
        """
        from ai_engine.models import SubstituteAssignment  # avoid circular import at module load

        school = absence.school
        term, published = cls._find_published_timetable(school, absence.date)
        if not term:
            raise SubstituteCoverError(
                "No academic term covers this date. Check the date or set up the school's academic terms."
            )
        if not published:
            raise SubstituteCoverError(
                f"No published timetable for {term}. Generate and publish a timetable for this term first."
            )

        day_code = absence.date.strftime('%a').upper()[:3]  # 'MON', 'TUE', ... matches TimeSlot.DAY_CHOICES
        affected_entries = TimetableEntry.objects.filter(
            timetable=published, teacher=absence.teacher, timeslot__day=day_code
        ).select_related('subject', 'school_class', 'timeslot', 'room')

        assignments = []
        for entry in affected_entries:
            existing = SubstituteAssignment.objects.filter(absence=absence, timetable_entry=entry).first()
            if existing and existing.status == 'CONFIRMED':
                assignments.append(existing)
                continue

            candidates = SubstituteMatchService.find_candidates(entry, absence, published)
            top = candidates[0] if candidates else None

            assignment, _ = SubstituteAssignment.objects.update_or_create(
                absence=absence, timetable_entry=entry,
                defaults={
                    'school': school,
                    'suggested_substitute': top['teacher'] if top else None,
                    'status': 'SUGGESTED' if top else 'UNCOVERED',
                },
            )

            if top and not assignment.note_edited_by:
                period_label = f"{entry.timeslot.get_day_display()} P{entry.timeslot.period_index}"
                assignment.handover_note = AIService.generate_substitute_handover_note(
                    substitute_name=top['teacher'].user.get_full_name(),
                    subject_name=entry.subject.name,
                    class_name=entry.school_class.name,
                    period_label=period_label,
                    is_subject_qualified=top['qualified'],
                    absent_teacher_name=absence.teacher.user.get_full_name(),
                )
                assignment.save(update_fields=['handover_note'])

            assignments.append(assignment)

        return assignments
