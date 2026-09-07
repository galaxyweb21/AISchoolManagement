"""
Verified School Database Intelligence
=====================================

A tenant-safe, deterministic query layer for factual questions about the
school database.  It deliberately answers database facts with Django ORM
instead of asking the LLM to guess them.

The LLM remains useful for explanations and educational knowledge, but it is
never the source of truth for counts, lists, statuses, balances, or dates
stored in the school's database.
"""
import logging
import re
from datetime import date

from django.apps import apps
from django.db.models import Count, Q, Sum, Avg
from django.utils import timezone

logger = logging.getLogger(__name__)


class SchoolDatabaseIntelligence:
    """High-confidence, school-scoped database answers."""

    def __init__(self, user, school, allowed_students=None):
        self.user = user
        self.school = school
        self.allowed_students = allowed_students

    @staticmethod
    def norm(value):
        value = str(value or '').strip().lower()
        value = re.sub(r'[^a-z0-9\s\-/]', ' ', value)
        return re.sub(r'\s+', ' ', value).strip()

    def meta(self, mode='verified_database'):
        return {
            'mode': mode,
            'sources': ['school_database'],
            'scope': 'authorized school data',
        }

    def _can(self, capability):
        try:
            from .role_ai_policy import can_use
            return bool(can_use(self.user, capability))
        except Exception:
            return False

    def _students(self):
        from students.models import Student
        if self.allowed_students is not None:
            return self.allowed_students
        return Student.objects.filter(school=self.school, is_active=True)

    def _staff(self):
        from staff.models import StaffProfile
        return StaffProfile.objects.filter(school=self.school).select_related('user', 'department', 'staff_grade')

    # ------------------------------------------------------------------
    # STAFF
    # ------------------------------------------------------------------
    def _staff_queryset_for_question(self, q):
        qs = self._staff()
        if 'inactive' in q or 'former staff' in q or 'former employee' in q:
            return qs.filter(is_active=False)
        qs = qs.filter(is_active=True)
        if any(x in q for x in ('teacher', 'teachers', 'teaching staff')):
            qs = qs.filter(staff_position='TEACHER')
        elif any(x in q for x in ('non teaching', 'non-teaching', 'non teaching staff')):
            qs = qs.exclude(staff_position='TEACHER')
        for key, value in (
            ('school administrator', 'SCHOOL_ADMIN'), ('bursar', 'BURSAR'),
            ('finance officer', 'BURSAR'), ('registrar', 'REGISTRAR'),
            ('hod', 'HOD'), ('head of department', 'HOD'), ('secretary', 'SECRETARY'),
            ('it support', 'IT_SUPPORT'), ('librarian', 'LIBRARIAN'),
        ):
            if key in q:
                qs = qs.filter(staff_position=value)
                break
        return qs

    def _staff_question(self, q):
        if not self._can('staff'):
            return {'answer': 'You do not have permission to access staff information.', **self.meta('permission_denied')}
        staff_words = ('staff', 'employee', 'employees', 'personnel', 'teacher', 'teachers')
        if not any(x in q for x in staff_words):
            return None
        action = any(x in q for x in ('how many', 'number of', 'count', 'total', 'who', 'which', 'list', 'show', 'names'))
        if not action:
            return None
        qs = self._staff_queryset_for_question(q)
        count = qs.count()
        available = 'available' in q or 'currently working' in q or 'at work' in q
        if available:
            today = timezone.localdate()
            try:
                from staff.models import LeaveRequest
                leave_ids = LeaveRequest.objects.filter(
                    school=self.school,
                    staff__school=self.school,
                    staff__is_active=True,
                    status__in=('APPROVED', 'TAKEN'),
                    start_date__lte=today,
                    end_date__gte=today,
                ).values_list('staff_id', flat=True)
                available_count = qs.exclude(pk__in=leave_ids).count()
                on_leave = count - available_count
            except Exception:
                logger.exception('Staff availability lookup failed')
                return {'answer': 'I could not verify staff availability from the school database.', **self.meta('database_error')}
            return {
                'answer': f"## Staff Availability\n\nThere are **{count:,} active staff members** matching your query. As of **{today:%d %B %Y}**, **{available_count:,}** are available and **{on_leave:,}** are on approved/taken leave.",
                'data': {'active_staff': count, 'available_staff': available_count, 'on_leave': on_leave, 'date': today.isoformat()},
                **self.meta(),
            }
        if any(x in q for x in ('who', 'which', 'list', 'show', 'names')):
            rows = qs.order_by('user__last_name', 'user__first_name')[:100]
            lines = [f"## Staff\n\n**{count:,}** staff members match your query.", '']
            records = []
            for i, s in enumerate(rows, 1):
                name = s.user.get_full_name().strip() or s.user.username
                pos = s.get_staff_position_display()
                dept = getattr(s.department, 'name', None) or 'No department'
                lines.append(f'{i}. **{name}** — {pos} — {dept}')
                records.append({'name': name, 'position': pos, 'department': dept})
            if count > 100:
                lines.append(f'\n*Showing the first 100 of {count:,} records.*')
            return {'answer': '\n'.join(lines), 'data': {'count': count, 'staff': records}, **self.meta()}
        label = 'inactive' if 'inactive' in q or 'former' in q else 'active'
        return {'answer': f"There are **{count:,} {label} staff members** matching your query.", 'data': {'count': count, 'status': label}, **self.meta()}

    # ------------------------------------------------------------------
    # STUDENTS / CLASSES / SUBJECTS
    # ------------------------------------------------------------------
    def _student_question(self, q):
        if not self._can('students'):
            return {'answer': 'You do not have permission to access student information.', **self.meta('permission_denied')}
        if not any(x in q for x in ('student', 'students', 'learner', 'learners', 'pupil', 'pupils')):
            return None
        qs = self._students()
        if 'inactive' in q:
            from students.models import Student
            qs = Student.objects.filter(school=self.school, is_active=False)
        action = any(x in q for x in ('how many', 'number of', 'count', 'total', 'who', 'which', 'list', 'show', 'names', 'population'))
        if not action:
            return None
        count = qs.count()
        if any(x in q for x in ('who', 'which', 'list', 'show', 'names')):
            rows = qs.select_related('user', 'school_class', 'grade_level').order_by('user__last_name', 'user__first_name')[:100]
            lines = [f"## Students\n\n**{count:,}** students match your query.", '']
            for i, s in enumerate(rows, 1):
                name = s.user.get_full_name().strip() or s.user.username
                cls = getattr(s.school_class, 'name', None) or 'Not assigned'
                grade = getattr(s.grade_level, 'name', None) or 'Not assigned'
                lines.append(f'{i}. **{name}** — {cls} — {grade}')
            if count > 100:
                lines.append(f'\n*Showing the first 100 of {count:,} records.*')
            return {'answer': '\n'.join(lines), 'data': {'count': count}, **self.meta()}
        status = 'inactive' if 'inactive' in q else 'active'
        return {'answer': f"There are **{count:,} {status} students** in the authorized school scope.", 'data': {'count': count, 'status': status}, **self.meta()}

    def _class_question(self, q):
        if not self._can('academics'):
            return {'answer': 'You do not have permission to access academic information.', **self.meta('permission_denied')}
        if not any(x in q for x in ('class', 'classes', 'grade level', 'grade levels')):
            return None
        from academics.models import SchoolClass
        if any(x in q for x in ('how many', 'number of', 'count', 'total', 'list', 'show', 'which', 'what classes')):
            qs = SchoolClass.objects.filter(school=self.school)
            if 'inactive' in q:
                qs = qs.filter(is_active=False)
            elif 'active' in q:
                qs = qs.filter(is_active=True)
            count = qs.count()
            if any(x in q for x in ('list', 'show', 'which', 'what classes')):
                rows = qs.select_related('grade_level').order_by('grade_level__order', 'name')[:100]
                lines = [f"## School Classes\n\n**{count:,} classes** match your query.", '']
                for i, c in enumerate(rows, 1):
                    lines.append(f'{i}. **{c.name}** — {c.grade_level.name if c.grade_level else "No grade level"} — {"Active" if c.is_active else "Inactive"}')
                return {'answer': '\n'.join(lines), 'data': {'count': count}, **self.meta()}
            return {'answer': f"There are **{count:,} school classes** matching your query.", 'data': {'count': count}, **self.meta()}
        return None

    def _subject_question(self, q):
        if not self._can('academics'):
            return {'answer': 'You do not have permission to access academic information.', **self.meta('permission_denied')}
        if not any(x in q for x in ('subject', 'subjects')):
            return None
        from academics.models import Subject
        if not any(x in q for x in ('how many', 'number of', 'count', 'total', 'list', 'show', 'which')):
            return None
        qs = Subject.objects.filter(school=self.school)
        if 'inactive' in q: qs = qs.filter(is_active=False)
        elif 'active' in q: qs = qs.filter(is_active=True)
        count = qs.count()
        if any(x in q for x in ('list', 'show', 'which')):
            lines = [f"## Subjects\n\n**{count:,} subjects** match your query.", '']
            for i, s in enumerate(qs.order_by('name')[:100], 1):
                lines.append(f'{i}. **{s.name}** — {"Active" if s.is_active else "Inactive"}')
            return {'answer': '\n'.join(lines), 'data': {'count': count}, **self.meta()}
        return {'answer': f"There are **{count:,} subjects** matching your query.", 'data': {'count': count}, **self.meta()}


    # ------------------------------------------------------------------
    # FINANCE / ATTENDANCE / ACADEMICS
    # ------------------------------------------------------------------
    def _finance_question(self, q):
        if not self._can('finance'):
            return {'answer': 'You do not have permission to access finance information.', **self.meta('permission_denied')}
        if not any(x in q for x in ('fee', 'fees', 'invoice', 'invoices', 'payment', 'payments', 'financial', 'finance', 'receivable', 'outstanding', 'revenue', 'collection')):
            return None
        try:
            from finance.models import Invoice, Payment
            if any(x in q for x in ('payment', 'payments', 'collection', 'collected', 'revenue')):
                qs = Payment.objects.filter(invoice__school=self.school)
                if 'confirmed' in q:
                    qs = qs.filter(status='CONFIRMED')
                total = qs.filter(status='CONFIRMED').aggregate(v=Sum('amount'))['v'] or 0
                count = qs.count()
                answer = (
                    f"## Payments\n\nThere are **{count:,} payment records** in the school database. "
                    f"Confirmed payments total **GH₵{total:,.2f}**."
                )
                return {'answer': answer, 'data': {'payment_records': count, 'confirmed_amount': str(total)}, **self.meta()}
            qs = Invoice.objects.filter(school=self.school)
            count = qs.count()
            total = qs.aggregate(v=Sum('total_amount'))['v'] or 0
            paid = qs.aggregate(v=Sum('amount_paid'))['v'] or 0
            outstanding = total - paid
            answer = (
                f"## Finance Summary\n\n"
                f"- **Invoices:** {count:,}\n"
                f"- **Total billed:** **GH₵{total:,.2f}**\n"
                f"- **Total paid:** **GH₵{paid:,.2f}**\n"
                f"- **Outstanding:** **GH₵{outstanding:,.2f}**"
            )
            return {'answer': answer, 'data': {'invoices': count, 'billed': str(total), 'paid': str(paid), 'outstanding': str(outstanding)}, **self.meta()}
        except Exception:
            logger.exception('Finance database intelligence failed')
            return {'answer': 'I could not safely verify the requested finance information from the school database.', **self.meta('database_error')}

    def _attendance_question(self, q):
        if not self._can('attendance'):
            return {'answer': 'You do not have permission to access attendance information.', **self.meta('permission_denied')}
        if 'attendance' not in q and not any(x in q for x in ('present today', 'absent today', 'late today', 'who is absent', 'who are absent')):
            return None
        try:
            from attendance.models import Attendance
            today = timezone.localdate()
            qs = Attendance.objects.filter(school=self.school, date=today)
            counts = {s: qs.filter(status=s).count() for s in ('PRESENT', 'ABSENT', 'LATE', 'EXCUSED')}
            total = qs.values('student_id').distinct().count()
            answer = (
                f"## Today's Attendance — {today:%d %B %Y}\n\n"
                f"**{total:,} students** have attendance recorded.\n\n"
                f"- Present: **{counts['PRESENT']:,}**\n"
                f"- Absent: **{counts['ABSENT']:,}**\n"
                f"- Late: **{counts['LATE']:,}**\n"
                f"- Excused: **{counts['EXCUSED']:,}**"
            )
            return {'answer': answer, 'data': {'date': today.isoformat(), 'recorded_students': total, **{k.lower(): v for k, v in counts.items()}}, **self.meta()}
        except Exception:
            logger.exception('Attendance database intelligence failed')
            return {'answer': 'I could not safely verify attendance from the school database.', **self.meta('database_error')}

    def _assessment_question(self, q):
        if not self._can('academics'):
            return {'answer': 'You do not have permission to access academic results.', **self.meta('permission_denied')}
        if not any(x in q for x in ('result', 'results', 'assessment', 'assessments', 'exam', 'exams', 'grade', 'grades', 'mark', 'marks', 'score', 'scores')):
            return None
        if not any(x in q for x in ('how many', 'number of', 'count', 'total', 'average', 'highest', 'lowest', 'list', 'show', 'what is', 'what are')):
            return None
        try:
            from assessments.models import Grade, Assessment, TerminalResult
            grade_count = Grade.objects.filter(assessment__school=self.school).count()
            assessment_count = Assessment.objects.filter(school=self.school).count()
            terminal_count = TerminalResult.objects.filter(school=self.school).count()
            if 'assessment' in q or 'exam' in q:
                answer = (
                    f"## Academic Records\n\n"
                    f"- **Assessments:** {assessment_count:,}\n"
                    f"- **Grades recorded:** {grade_count:,}\n"
                    f"- **Terminal results:** {terminal_count:,}"
                )
                return {'answer': answer, 'data': {'assessments': assessment_count, 'grades': grade_count, 'terminal_results': terminal_count}, **self.meta()}
            avg = Grade.objects.filter(assessment__school=self.school).aggregate(v=Avg('score_achieved'))['v']
            answer = f"## Academic Results\n\nThere are **{grade_count:,} grade records** and **{terminal_count:,} terminal results** in the school database."
            if avg is not None:
                answer += f" The average recorded assessment score is **{avg:.2f}**."
            return {'answer': answer, 'data': {'grades': grade_count, 'terminal_results': terminal_count, 'average_score': str(avg) if avg is not None else None}, **self.meta()}
        except Exception:
            logger.exception('Assessment database intelligence failed')
            return {'answer': 'I could not safely verify the requested academic data from the school database.', **self.meta('database_error')}

    # ------------------------------------------------------------------
    # SCHOOL STRUCTURE / LIBRARY / COMMUNICATION
    # ------------------------------------------------------------------
    def _simple_model_question(self, q):
        # model, singular/plural aliases, capability, queryset, label
        specs = []
        try:
            from staff.models import Department, StaffGrade, LeaveType
            specs += [
                (Department, ('department', 'departments'), 'staff', 'departments'),
                (StaffGrade, ('staff grade', 'staff grades', 'grade'), 'staff', 'staff grades'),
                (LeaveType, ('leave type', 'leave types'), 'staff', 'leave types'),
            ]
        except Exception:
            pass
        try:
            from school.models import AcademicYear, AcademicTerm
            specs += [
                (AcademicYear, ('academic year', 'academic years'), 'school_intelligence', 'academic years'),
                (AcademicTerm, ('academic term', 'academic terms', 'terms'), 'school_intelligence', 'academic terms'),
            ]
        except Exception:
            pass
        try:
            from library.models import Book, BookCategory
            specs += [
                (Book, ('book', 'books', 'library book', 'library books'), 'school_intelligence', 'books'),
                (BookCategory, ('book category', 'book categories'), 'school_intelligence', 'book categories'),
            ]
        except Exception:
            pass
        try:
            from communication.models import Announcement
            specs.append((Announcement, ('announcement', 'announcements'), 'school_intelligence', 'announcements'))
        except Exception:
            pass
        action = any(x in q for x in ('how many', 'number of', 'count', 'total', 'list', 'show', 'which', 'what are'))
        if not action:
            return None
        for model, aliases, capability, label in specs:
            if any(a in q for a in aliases):
                if not self._can(capability):
                    return {'answer': f'You do not have permission to access {label}.', **self.meta('permission_denied')}
                try:
                    qs = model.objects.filter(school=self.school)
                except Exception:
                    try:
                        # AcademicTerm is linked through AcademicYear.
                        qs = model.objects.filter(academic_year__school=self.school)
                    except Exception:
                        continue
                if hasattr(model, 'is_active'):
                    if 'inactive' in q: qs = qs.filter(is_active=False)
                    elif 'active' in q: qs = qs.filter(is_active=True)
                count = qs.count()
                if any(x in q for x in ('list', 'show', 'which', 'what are')):
                    rows = qs[:100]
                    lines = [f"## {label.title()}\n\n**{count:,} {label}** match your query.", '']
                    for i, obj in enumerate(rows, 1):
                        lines.append(f'{i}. **{str(obj)}**')
                    if count > 100: lines.append(f'\n*Showing the first 100 of {count:,} records.*')
                    return {'answer': '\n'.join(lines), 'data': {'count': count}, **self.meta()}
                return {'answer': f"There are **{count:,} {label}** in the school database.", 'data': {'count': count}, **self.meta()}
        return None

    # ------------------------------------------------------------------
    # GENERIC SCHOOL-DATA GUARD
    # ------------------------------------------------------------------
    def looks_like_school_fact(self, q):
        entity_terms = (
            'school', 'student', 'students', 'staff', 'teacher', 'employee', 'class', 'subject',
            'attendance', 'fee', 'fees', 'payment', 'invoice', 'payroll', 'salary', 'leave',
            'result', 'results', 'exam', 'assessment', 'book', 'library', 'announcement',
            'department', 'academic year', 'academic term', 'timetable', 'promotion',
        )
        action_terms = (
            'how many', 'how much', 'who', 'which', 'what is', 'what are', 'show', 'list',
            'give me', 'tell me', 'total', 'count', 'number of', 'available', 'current',
            'today', 'this term', 'this year', 'outstanding', 'balance', 'owing', 'owe',
        )
        return any(e in q for e in entity_terms) and any(a in q for a in action_terms)

    def answer(self, question):
        q = self.norm(question)
        if not q:
            return None
        # Exact school identity is always authoritative.
        if any(x in q for x in ('what is the name of this school', 'what is the school name', 'what is our school name', 'which school is this')):
            name = str(getattr(self.school, 'name', '') or '').strip()
            return {'answer': f'## School Information\n\nThe name of this school is **{name}**.', 'data': {'school_name': name}, **self.meta()}
        for handler in (self._staff_question, self._student_question, self._class_question, self._subject_question, self._finance_question, self._attendance_question, self._assessment_question, self._simple_model_question):
            try:
                result = handler(q)
                if result is not None:
                    return result
            except Exception:
                logger.exception('Database intelligence handler failed for %r', q)
                # Never convert a database exception into a guessed answer.
                return {'answer': 'I could not safely verify that information from the school database. No unverified answer was provided.', **self.meta('database_error')}
        return None
