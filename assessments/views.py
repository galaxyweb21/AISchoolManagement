# assessments/views.py
import json
from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import role_allows
from academics.models import SchoolClass, Subject, TeacherAssignment, ClassSubject, TeacherClassAssignment
from ai_engine.services.services import AIService
from attendance.models import Attendance
from school.models import AcademicTerm
from students.models import Student
from .models import Assessment, AssessmentQuestion, Grade, TerminalResult



def _can(user, action='view'):
    return role_allows(user, 'exams', action)


def _teacher_homeroom_class_ids(user, school):
    """Return only the classes where this teacher is the registered class/homeroom teacher.

    The project supports two existing assignment paths:
    1. SchoolClass.homeroom_teacher
    2. TeacherClassAssignment

    Both are treated as authoritative so schools using either workflow work correctly.
    """
    if getattr(user, 'role', None) != 'TEACHER':
        return set()
    try:
        teacher = user.teacher_profile
    except Exception:
        return set()

    ids = set(SchoolClass.objects.filter(
        school=school,
        is_active=True,
        homeroom_teacher=teacher,
    ).values_list('id', flat=True))

    ids.update(TeacherClassAssignment.objects.filter(
        school=school,
        teacher=teacher,
        is_active=True,
    ).values_list('school_class_id', flat=True))
    return ids


def _teacher_scope(user, school):
    """Return classes the teacher can work with; admins see all active classes.

    A teacher can work in a class when they either teach a subject there or are
    the registered class/homeroom teacher. This is used by the grading portal.
    """
    classes = SchoolClass.objects.filter(school=school, is_active=True)
    if user.role != 'TEACHER':
        return classes
    try:
        teacher = user.teacher_profile
    except Exception:
        return classes.none()

    class_ids = set(TeacherAssignment.objects.filter(
        school=school, teacher=teacher, is_active=True
    ).values_list('school_class_id', flat=True))
    class_ids.update(_teacher_homeroom_class_ids(user, school))
    return classes.filter(id__in=class_ids)


def _teacher_subjects(user, school, school_class=None):
    """Return subjects available to the current user/class.

    For a normal subject teacher, subjects come from TeacherAssignment.
    For a class/homeroom teacher, ALL subjects configured for the class are
    available, even where the teacher has no separate TeacherAssignment row.
    This is essential for Ghanaian class-teacher workflows in lower levels and
    for schools that record class-teacher responsibility separately.
    """
    if user.role != 'TEACHER':
        qs = Subject.objects.filter(school=school, is_active=True)
        if school_class:
            qs = qs.filter(
                class_subjects__school_class=school_class,
                class_subjects__is_active=True,
            )
        return qs.distinct().order_by('name')

    try:
        teacher = user.teacher_profile
    except Exception:
        return Subject.objects.none()

    # Subjects directly assigned to the teacher.
    assignment_qs = Subject.objects.filter(
        school=school,
        is_active=True,
        teacher_assignments__teacher=teacher,
        teacher_assignments__is_active=True,
    )

    # Class-teacher subjects: all active subjects offered by the homeroom class.
    homeroom_ids = _teacher_homeroom_class_ids(user, school)
    class_subject_qs = Subject.objects.none()
    if school_class and school_class.id in homeroom_ids:
        class_subject_qs = Subject.objects.filter(
            school=school,
            is_active=True,
            class_subjects__school_class=school_class,
            class_subjects__is_active=True,
        )
        # If the class has not yet been configured in ClassSubject, use the
        # teacher's direct assignments for that class as a safe fallback.
        if not class_subject_qs.exists():
            class_subject_qs = Subject.objects.filter(
                school=school,
                is_active=True,
                teacher_assignments__teacher=teacher,
                teacher_assignments__school_class=school_class,
                teacher_assignments__is_active=True,
            )
        # Last-resort class-teacher fallback: the class teacher is responsible
        # for the class as a whole, so expose the school's active subjects when
        # no class-subject/assignment records exist yet. This keeps data entry
        # usable during initial school setup; the class-subject manager can
        # subsequently be used to narrow the curriculum.
        if not class_subject_qs.exists():
            class_subject_qs = Subject.objects.filter(school=school, is_active=True)
    elif school_class:
        assignment_qs = assignment_qs.filter(
            teacher_assignments__school_class=school_class,
        )

    if school_class and school_class.id in homeroom_ids:
        return (assignment_qs | class_subject_qs).distinct().order_by('name')
    return assignment_qs.distinct().order_by('name')


def _teacher_subject_names(user, school):
    return set(_teacher_subjects(user, school).values_list('name', flat=True)) if user.role == 'TEACHER' else None


def _teacher_assignment_exists(user, school, school_class, subject_name):
    """Check whether a teacher may work with a class/subject pair.

    A registered class teacher may work with every subject of their homeroom
    class. Subject teachers remain limited to explicit TeacherAssignment rows.
    """
    if user.role != 'TEACHER':
        return True
    try:
        teacher = user.teacher_profile
        if school_class.id in _teacher_homeroom_class_ids(user, school):
            return Subject.objects.filter(
                school=school,
                name__iexact=subject_name,
                is_active=True,
            ).exists()
        return TeacherAssignment.objects.filter(
            school=school,
            teacher=teacher,
            school_class=school_class,
            subject__name__iexact=subject_name,
            is_active=True,
        ).exists()
    except Exception:
        return False


def _assessment_allowed(user, assessment, action='view'):
    if not _can(user, action):
        return False
    if user.role != 'TEACHER':
        return True
    if not assessment.school_class_id:
        return False
    return _teacher_assignment_exists(user, assessment.school, assessment.school_class, assessment.subject)


def _grade_for_score(score):
    if score is None:
        return '', ''
    value = float(score)
    if value >= 90:
        return 'A+', 'Outstanding'
    if value >= 80:
        return 'A', 'Excellent'
    if value >= 70:
        return 'B', 'Very Good'
    if value >= 60:
        return 'C', 'Good'
    if value >= 50:
        return 'D', 'Satisfactory'
    if value >= 40:
        return 'E', 'Pass'
    return 'F', 'Needs Improvement'


def _decimal_or_none(value, label):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'Invalid {label}.')


def _convert_component(raw_value, mode, maximum, weight, label):
    value = _decimal_or_none(raw_value, label)
    if value is None:
        return None, None, None
    maximum = Decimal(str(maximum))
    if maximum <= 0:
        raise ValueError(f'{label} maximum must be greater than zero.')
    if value < 0 or value > maximum:
        raise ValueError(f'{label} must be between 0 and {maximum}.')
    if mode == 'RAW':
        weighted = (value / maximum) * Decimal(str(weight))
        return weighted.quantize(Decimal('0.01')), value, maximum
    return value, value, maximum


def _legacy_component_values(student, school_class, subject, term):
    """Fallback for V8 data that predates TerminalResult."""
    qs = Grade.objects.filter(
        student=student,
        assessment__school=student.school,
        assessment__school_class=school_class,
        assessment__subject__iexact=subject,
        assessment__academic_term=term,
    ).select_related('assessment')
    ca_values, exam_values = [], []
    for grade in qs:
        assessment = grade.assessment
        if not assessment.max_score:
            continue
        pct = Decimal(str(grade.score_achieved)) / Decimal(str(assessment.max_score)) * Decimal('100')
        if assessment.score_component == 'EXAM' or assessment.assessment_type == 'EXAM':
            exam_values.append(pct)
        elif assessment.score_component == 'CA' or assessment.assessment_type != 'EXAM':
            ca_values.append(pct)
    class_score = (sum(ca_values) / Decimal(len(ca_values)) * Decimal('0.30')) if ca_values else None
    exam_score = (sum(exam_values) / Decimal(len(exam_values)) * Decimal('0.70')) if exam_values else None
    return (
        class_score.quantize(Decimal('0.01')) if class_score is not None else None,
        exam_score.quantize(Decimal('0.01')) if exam_score is not None else None,
    )


def _get_or_create_terminal_assessment(school, school_class, term, subject, component):
    """Keep direct terminal entry compatible with the existing Grade/report infrastructure."""
    if component == 'EXAM':
        title = f'End of Term Examination — {subject}'
        assessment_type = 'EXAM'
        max_score = 70
    else:
        title = f'Terminal Class Score — {subject}'
        assessment_type = 'QUIZ'
        max_score = 30
    assessment = Assessment.objects.filter(
        school=school,
        school_class=school_class,
        academic_term=term,
        subject__iexact=subject,
        score_component=component,
    ).order_by('-created_at').first()
    if assessment:
        return assessment
    return Assessment.objects.create(
        school=school,
        school_class=school_class,
        academic_term=term,
        title=title,
        subject=subject,
        assessment_type=assessment_type,
        score_component=component,
        max_score=max_score,
    )


@login_required
def teacher_grading_portal(request):
    """V8.2 Ghana Terminal Results Centre.

    This is intentionally still the existing /assessments/portal/ URL so the
    sidebar/bookmarks do not break. It now provides explicit Class /30 and
    Examination /70 entry while retaining assessment/question management.
    """
    if not _can(request.user, 'view'):
        messages.error(request, "You don't have permission to view the results centre.")
        return redirect('dashboard')

    school = request.user.school
    classes = _teacher_scope(request.user, school).select_related('grade_level').order_by(
        'grade_level__order', 'name'
    )
    class_id = request.GET.get('class_id', '').strip()
    subject_name = request.GET.get('subject', '').strip()
    term_id = request.GET.get('term_id', '').strip()
    assessment_id = request.GET.get('assessment_id', '').strip()

    homeroom_ids = _teacher_homeroom_class_ids(request.user, school)
    preferred_homeroom = classes.filter(id__in=homeroom_ids).order_by('grade_level__order', 'name').first() if homeroom_ids else None
    selected_class = classes.filter(id=class_id).first() if class_id else (preferred_homeroom or classes.first())
    terms = AcademicTerm.objects.filter(
        academic_year__school=school
    ).select_related('academic_year').order_by('-start_date')
    active_term = terms.filter(
        academic_year__is_active=True, is_active=True
    ).first()
    selected_term = terms.filter(id=term_id).first() if term_id else active_term

    subjects = _teacher_subjects(request.user, school, selected_class)
    selected_subject = subjects.filter(name__iexact=subject_name).first() if subject_name else subjects.first()
    subject_name = selected_subject.name if selected_subject else subject_name

    students = Student.objects.filter(
        school=school, is_active=True, school_class=selected_class
    ).select_related('user', 'school_class', 'grade_level').order_by(
        'user__last_name', 'user__first_name'
    ) if selected_class else Student.objects.none()

    result_map = {}
    if selected_class and selected_subject and selected_term:
        result_map = {
            row.student_id: row for row in TerminalResult.objects.filter(
                school=school,
                academic_term=selected_term,
                school_class=selected_class,
                subject__iexact=selected_subject.name,
                student__in=students,
            )
        }
        for student in students:
            result = result_map.get(student.id)
            if result is None:
                ca, exam = _legacy_component_values(student, selected_class, selected_subject.name, selected_term)
                result = {
                    'class_score': ca,
                    'exam_score': exam,
                    'final_score': (ca + exam) if ca is not None and exam is not None else None,
                    'grade': _grade_for_score(ca + exam)[0] if ca is not None and exam is not None else '',
                    'remark': _grade_for_score(ca + exam)[1] if ca is not None and exam is not None else '',
                    'id': '', 'status': 'DRAFT', 'teacher_note': '',
                }
            student.terminal_result = result

    # Optional assessment selection is retained for question review/detail.
    assessments = Assessment.objects.filter(school=school).select_related(
        'school_class', 'academic_term'
    ).order_by('-created_at')
    if request.user.role == 'TEACHER':
        allowed_class_ids = list(classes.values_list('id', flat=True))
        allowed_subject_names = set(
            _teacher_subjects(request.user, school, selected_class).values_list('name', flat=True)
        ) if selected_class else set(
            _teacher_subjects(request.user, school).values_list('name', flat=True)
        )
        assessments = assessments.filter(school_class_id__in=allowed_class_ids)
        if allowed_subject_names:
            assessments = assessments.filter(subject__in=allowed_subject_names)
        else:
            assessments = assessments.none()
    if selected_class:
        assessments = assessments.filter(school_class=selected_class)
    if selected_term:
        assessments = assessments.filter(academic_term=selected_term)
    if selected_subject:
        assessments = assessments.filter(subject__iexact=selected_subject.name)

    active_assessment = assessments.filter(id=assessment_id).first() if assessment_id else None
    questions = active_assessment.questions.all() if active_assessment else []

    return render(request, 'assessments/grading_portal.html', {
        'students': students,
        'assessments': assessments,
        'active_assessment': active_assessment,
        'terms': terms,
        'selected_term': selected_term,
        'school_classes': classes,
        'subjects': subjects,
        'selected_class_id': class_id,
        'selected_subject': subject_name,
        'selected_term_id': str(selected_term.id) if selected_term else '',
        'selected_class': selected_class,
        'homeroom_classes': classes.filter(id__in=homeroom_ids) if homeroom_ids else classes.none(),
        'is_class_teacher': bool(homeroom_ids),
        'questions': questions,
        'can_manage_questions': bool(active_assessment and _assessment_allowed(request.user, active_assessment, 'edit')),
        'can_create': _can(request.user, 'create'),
        'can_edit_results': _can(request.user, 'edit'),
    })


@login_required
@require_POST
def api_save_terminal_results(request):
    """Bulk-save Ghana terminal Class /30 and Exam /70 marks."""
    if not _can(request.user, 'edit'):
        return JsonResponse({'success': False, 'error': "You don't have permission to enter results."}, status=403)
    try:
        data = json.loads(request.body or '{}')
        school = request.user.school
        class_id = data.get('school_class_id')
        term_id = data.get('academic_term_id')
        subject = (data.get('subject') or '').strip()
        mode = (data.get('entry_mode') or 'WEIGHTED').upper()
        rows = data.get('results') or []
        if not class_id or not term_id or not subject:
            raise ValueError('Class, academic term and subject are required.')
        if mode not in ('WEIGHTED', 'RAW'):
            raise ValueError('Invalid result entry mode.')

        school_class = get_object_or_404(SchoolClass, id=class_id, school=school, is_active=True)
        term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)
        if not _teacher_assignment_exists(request.user, school, school_class, subject):
            return JsonResponse({'success': False, 'error': 'This class and subject are outside your teaching assignment.'}, status=403)
        if not rows:
            raise ValueError('No student results were supplied.')

        allowed_students = {
            str(s.id): s for s in Student.objects.filter(
                school=school, school_class=school_class, is_active=True,
                id__in=[r.get('student_id') for r in rows if r.get('student_id')]
            ).select_related('user')
        }
        saved = 0
        complete = 0
        with transaction.atomic():
            for row in rows:
                student = allowed_students.get(str(row.get('student_id')))
                if not student:
                    raise ValueError('One or more students are outside the selected class.')

                class_raw_max = _decimal_or_none(row.get('class_raw_max'), 'class-score maximum')
                exam_raw_max = _decimal_or_none(row.get('exam_raw_max'), 'exam-score maximum')
                class_input = row.get('class_score')
                exam_input = row.get('exam_score')

                class_score, class_raw, class_max = _convert_component(
                    class_input,
                    mode,
                    class_raw_max if mode == 'RAW' and class_raw_max is not None else 30,
                    30,
                    'Class Score',
                )
                exam_score, exam_raw, exam_max = _convert_component(
                    exam_input,
                    mode,
                    exam_raw_max if mode == 'RAW' and exam_raw_max is not None else 70,
                    70,
                    'Examination Score',
                )

                # Empty rows are ignored, so a teacher can save a partially completed class sheet.
                if class_score is None and exam_score is None and not row.get('teacher_note'):
                    continue

                result, _ = TerminalResult.objects.get_or_create(
                    school=school,
                    academic_term=term,
                    school_class=school_class,
                    student=student,
                    subject=subject,
                )
                result.class_score = class_score
                result.exam_score = exam_score
                result.class_raw_score = class_raw
                result.class_raw_max = class_max
                result.exam_raw_score = exam_raw
                result.exam_raw_max = exam_max
                result.entry_mode = mode
                result.teacher_note = (row.get('teacher_note') or '').strip()
                result.entered_by = request.user
                result.save()

                # Mirror the explicit component scores into Grade so legacy reports,
                # exports and other gradebook consumers remain compatible.
                if class_score is not None:
                    ca_assessment = _get_or_create_terminal_assessment(school, school_class, term, subject, 'CA')
                    Grade.objects.update_or_create(
                        assessment=ca_assessment,
                        student=student,
                        defaults={'score_achieved': class_score, 'teacher_notes': result.teacher_note, 'graded_by': request.user},
                    )
                if exam_score is not None:
                    exam_assessment = _get_or_create_terminal_assessment(school, school_class, term, subject, 'EXAM')
                    Grade.objects.update_or_create(
                        assessment=exam_assessment,
                        student=student,
                        defaults={'score_achieved': exam_score, 'teacher_notes': result.teacher_note, 'graded_by': request.user},
                    )
                saved += 1
                if result.status == 'COMPLETE':
                    complete += 1

        return JsonResponse({'success': True, 'saved': saved, 'complete': complete})
    except (ValueError, InvalidOperation, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({'success': False, 'error': 'Unable to save terminal results.'}, status=500)


@login_required
@require_POST
def api_submit_grade(request):
    """Backward-compatible single-assessment grade endpoint."""
    if not _can(request.user, 'edit'):
        return JsonResponse({'success': False, 'error': "You don't have permission to enter grades."}, status=403)
    try:
        data = json.loads(request.body or '{}')
        school = request.user.school
        assessment = get_object_or_404(Assessment, id=data.get('assessment_id'), school=school)
        if not _assessment_allowed(request.user, assessment, 'edit'):
            return JsonResponse({'success': False, 'error': 'This assessment is outside your assigned teaching scope.'}, status=403)
        student = get_object_or_404(Student, id=data.get('student_id'), school=school, is_active=True)
        if assessment.school_class_id and student.school_class_id != assessment.school_class_id:
            return JsonResponse({'success': False, 'error': 'This student is not in the assessment class.'}, status=400)
        raw = data.get('score')
        if raw in (None, ''):
            raise ValueError('Score is required.')
        score = Decimal(str(raw))
        if score < 0 or score > assessment.max_score:
            raise ValueError(f'Score must be between 0 and {assessment.max_score}.')
        grade, _ = Grade.objects.update_or_create(
            student=student, assessment=assessment,
            defaults={'score_achieved': score, 'teacher_notes': (data.get('notes') or '').strip(), 'graded_by': request.user},
        )
        return JsonResponse({'success': True, 'grade_id': str(grade.id), 'score': str(grade.score_achieved), 'percentage': float(grade.percentage)})
    except (InvalidOperation, ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


@login_required
@require_POST
def api_create_assessment(request):
    if not _can(request.user, 'create'):
        return JsonResponse({'success': False, 'error': "You don't have permission to create assessments."}, status=403)
    try:
        data = json.loads(request.body or '{}')
        title = (data.get('title') or '').strip()
        subject = (data.get('subject') or '').strip()
        assessment_type = data.get('assessment_type') or 'EXAM'
        score_component = (data.get('score_component') or ('EXAM' if assessment_type == 'EXAM' else 'CA')).upper()
        term_id = data.get('academic_term_id') or None
        class_id = data.get('school_class_id') or None
        max_score = int(data.get('max_score') or (70 if score_component == 'EXAM' else 30))
        if not title or not subject or max_score <= 0:
            raise ValueError('Title, subject and a positive maximum score are required.')
        if assessment_type not in dict(Assessment.TYPE_CHOICES):
            raise ValueError('Invalid assessment type.')
        if score_component not in dict(Assessment.SCORE_COMPONENT_CHOICES):
            raise ValueError('Invalid terminal score component.')
        school = request.user.school
        term = AcademicTerm.objects.filter(id=term_id, academic_year__school=school).first() if term_id else None
        school_class = SchoolClass.objects.filter(id=class_id, school=school, is_active=True).first() if class_id else None
        if not term:
            raise ValueError('Academic term is required.')
        if not school_class:
            raise ValueError('School class is required.')
        if not _teacher_assignment_exists(request.user, school, school_class, subject):
            raise ValueError('You may only create assessments for classes and subjects assigned to you.')
        assessment = Assessment.objects.create(
            school=school, academic_term=term, school_class=school_class,
            title=title, subject=subject, assessment_type=assessment_type,
            score_component=score_component, max_score=max_score,
        )
        return JsonResponse({'success': True, 'assessment': {
            'id': str(assessment.id), 'title': assessment.title, 'subject': assessment.subject,
            'max_score': assessment.max_score, 'score_component': assessment.score_component,
            'school_class': school_class.name,
        }})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    except Exception:
        return JsonResponse({'success': False, 'error': 'Unable to create assessment.'}, status=500)


@login_required
@require_POST
def api_save_question(request):
    if not _can(request.user, 'edit'):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    try:
        data = json.loads(request.body or '{}')
        assessment = get_object_or_404(Assessment, id=data.get('assessment_id'), school=request.user.school)
        if not _assessment_allowed(request.user, assessment, 'edit'):
            return JsonResponse({'success': False, 'error': 'This assessment is outside your teaching scope.'}, status=403)
        qid = data.get('question_id')
        question = AssessmentQuestion.objects.filter(id=qid, assessment=assessment).first() if qid else None
        qtype = data.get('question_type') or 'SHORT_ANSWER'
        text = (data.get('question_text') or '').strip()
        marks = int(data.get('marks') or 1)
        if qtype not in dict(AssessmentQuestion.TYPE_CHOICES):
            raise ValueError('Invalid question type.')
        if not text or marks <= 0:
            raise ValueError('Question text and positive marks are required.')
        options = [str(x).strip() for x in (data.get('options') or []) if str(x).strip()]
        if qtype == 'MCQ' and len(options) < 2:
            raise ValueError('MCQ questions require at least two options.')
        if question is None:
            question = AssessmentQuestion(assessment=assessment, order=assessment.questions.count())
        question.question_type = qtype
        question.question_text = text
        question.options = options
        question.correct_answer = (data.get('correct_answer') or '').strip()
        question.marks = marks
        question.save()
        return JsonResponse({'success': True, 'question_id': str(question.id), 'order': question.order})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


@login_required
@require_POST
def api_delete_question(request, question_id):
    if not _can(request.user, 'edit'):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    question = get_object_or_404(AssessmentQuestion, id=question_id, assessment__school=request.user.school)
    if not _assessment_allowed(request.user, question.assessment, 'edit'):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    question.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def api_generate_ai_grade_feedback(request):
    if not _can(request.user, 'edit'):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    try:
        data = json.loads(request.body or '{}')
        grade = get_object_or_404(Grade, id=data.get('grade_id'), assessment__school=request.user.school)
        if not _assessment_allowed(request.user, grade.assessment, 'edit'):
            return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        attendance_records = Attendance.objects.filter(
            student=grade.student,
            date__gte=timezone.localdate() - timedelta(days=30),
        )
        attendance_percentage = round(
            attendance_records.filter(status__in=['PRESENT', 'LATE']).count() / attendance_records.count() * 100
        ) if attendance_records.exists() else 'N/A'
        feedback = AIService.generate_student_report(
            student_name=grade.student.user.get_full_name(),
            subject=grade.assessment.subject,
            grade=f'{grade.percentage}%',
            attendance_percentage=attendance_percentage,
            teacher_notes=grade.teacher_notes or 'No teacher note supplied.',
        )
        grade.ai_feedback = feedback
        grade.save(update_fields=['ai_feedback'])
        return JsonResponse({'success': True, 'ai_feedback': feedback})
    except Exception as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


# ============================================================================
# V8.2 TERMINAL RESULTS REGISTER / STUDENT TERMINAL REPORT
# ============================================================================

def _results_staff_allowed(user):
    """Only school staff with report visibility can use the results register."""
    if getattr(user, 'role', None) in {'STUDENT', 'PARENT'}:
        return False
    return _can(user, 'view')


def _results_class_scope(user, school):
    """Return the classes a user may review in the Terminal Results Register.

    Administrators/HOD/registrar/secretary can review the school's results.
    Teachers are restricted to their registered class/homeroom assignments.
    Both SchoolClass.homeroom_teacher and TeacherClassAssignment are supported.
    """
    classes = SchoolClass.objects.filter(school=school, is_active=True)
    if getattr(user, 'role', None) == 'TEACHER':
        ids = _teacher_homeroom_class_ids(user, school)
        if not ids:
            return classes.none()
        classes = classes.filter(id__in=ids)
    return classes.select_related('grade_level').order_by('grade_level__order', 'name')


@login_required
def terminal_results_register(request):
    """Enterprise register for reviewing all entered terminal results.

    Admins see the whole school. Class teachers see only their assigned
    homeroom class(es). The register is read-only; score entry stays on the
    Terminal Results Centre so there is one authoritative write workflow.
    """
    if not _results_staff_allowed(request.user):
        messages.error(request, "You don't have permission to view terminal results.")
        return redirect('dashboard')

    school = request.user.school
    classes = _results_class_scope(request.user, school)
    terms = AcademicTerm.objects.filter(
        academic_year__school=school
    ).select_related('academic_year').order_by('-start_date')

    active_term = terms.filter(
        academic_year__is_active=True, is_active=True
    ).first()
    term_id = request.GET.get('term_id', '').strip()
    class_id = request.GET.get('class_id', '').strip()
    search = request.GET.get('q', '').strip()

    selected_term = terms.filter(id=term_id).first() if term_id else active_term
    selected_class = classes.filter(id=class_id).first() if class_id else classes.first()

    results = TerminalResult.objects.none()
    students = Student.objects.none()
    subjects = []
    summary = {
        'students': 0,
        'subjects': 0,
        'entries': 0,
        'complete': 0,
        'incomplete': 0,
    }

    if selected_term and selected_class:
        students = Student.objects.filter(
            school=school,
            school_class=selected_class,
            is_active=True,
        ).select_related('user', 'school_class', 'grade_level').order_by(
            'user__last_name', 'user__first_name'
        )

        if search:
            students = students.filter(
                Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(admission_number__icontains=search)
            )

        results = TerminalResult.objects.filter(
            school=school,
            academic_term=selected_term,
            school_class=selected_class,
            student__in=students,
        ).select_related('student__user').order_by(
            'student__user__last_name', 'student__user__first_name', 'subject'
        )

        # Start from the class curriculum so the register shows every subject
        # even before the first result has been entered. Then union any legacy
        # or manually-entered result subjects that are not yet in ClassSubject.
        curriculum_subjects = list(
            Subject.objects.filter(
                school=school,
                is_active=True,
                class_subjects__school_class=selected_class,
                class_subjects__is_active=True,
            ).values_list('name', flat=True).distinct().order_by('name')
        )
        entered_subjects = list(
            results.values_list('subject', flat=True).distinct().order_by('subject')
        )
        subjects = list(curriculum_subjects)
        existing_lower = {str(name).lower() for name in subjects}
        for name in entered_subjects:
            if str(name).lower() not in existing_lower:
                subjects.append(name)
                existing_lower.add(str(name).lower())

        result_map = {}
        for row in results:
            result_map[(row.student_id, row.subject.lower())] = row

        register_rows = []
        for student in students:
            student_results = [
                result_map.get((student.id, subject.lower()))
                for subject in subjects
            ]
            student_results = [r for r in student_results if r is not None]
            complete_count = sum(1 for r in student_results if r.status == 'COMPLETE')
            final_scores = [float(r.final_score) for r in student_results if r.final_score is not None]
            average = round(sum(final_scores) / len(final_scores), 2) if final_scores else None
            register_rows.append({
                'student': student,
                'results': [result_map.get((student.id, subject.lower())) for subject in subjects],
                'entry_count': len(student_results),
                'complete_count': complete_count,
                'average': average,
                'complete': bool(student_results) and complete_count == len(student_results),
            })

        students = register_rows
        summary['students'] = len(register_rows)
        summary['subjects'] = len(subjects)
        summary['entries'] = results.count()
        summary['complete'] = results.filter(status='COMPLETE').count()
        summary['incomplete'] = results.filter(status='DRAFT').count()

    return render(request, 'assessments/terminal_results_register.html', {
        'classes': classes,
        'terms': terms,
        'selected_class': selected_class,
        'selected_term': selected_term,
        'students': students,
        'subjects': subjects,
        'summary': summary,
        'search_query': search,
        'is_teacher_scope': getattr(request.user, 'role', None) == 'TEACHER',
    })


@login_required
def terminal_student_report(request, student_id):
    """Read-only terminal report built directly from authoritative TerminalResult rows."""
    if not _results_staff_allowed(request.user):
        messages.error(request, "You don't have permission to view terminal reports.")
        return redirect('dashboard')

    school = request.user.school
    classes = _results_class_scope(request.user, school)
    student = get_object_or_404(
        Student.objects.select_related('user', 'school_class', 'grade_level'),
        id=student_id,
        school=school,
        is_active=True,
    )

    if not classes.filter(id=student.school_class_id).exists():
        messages.error(request, 'This student is outside your results scope.')
        return redirect('assessments:terminal_results_register')

    terms = AcademicTerm.objects.filter(
        academic_year__school=school
    ).select_related('academic_year').order_by('-start_date')
    active_term = terms.filter(
        academic_year__is_active=True, is_active=True
    ).first()
    term_id = request.GET.get('term_id', '').strip()
    selected_term = terms.filter(id=term_id).first() if term_id else active_term

    terminal_results = []
    overall_average = None
    overall_grade = ''
    complete_count = 0
    subject_count = 0

    if selected_term:
        terminal_results = list(
            TerminalResult.objects.filter(
                school=school,
                academic_term=selected_term,
                school_class=student.school_class,
                student=student,
            ).order_by('subject')
        )
        complete_scores = [
            float(r.final_score) for r in terminal_results if r.final_score is not None
        ]
        if complete_scores:
            overall_average = round(sum(complete_scores) / len(complete_scores), 2)
            # Reuse the same scale as terminal score entry.
            overall_grade, _ = _grade_for_score(overall_average)
        subject_count = len(terminal_results)
        complete_count = sum(1 for r in terminal_results if r.status == 'COMPLETE')

    report_card = None
    try:
        from ai_engine.models import ReportCard
        report_card = ReportCard.objects.filter(
            school=school, student=student, academic_term=selected_term
        ).first() if selected_term else None
    except Exception:
        report_card = None

    return render(request, 'assessments/terminal_student_report.html', {
        'student': student,
        'terms': terms,
        'selected_term': selected_term,
        'terminal_results': terminal_results,
        'overall_average': overall_average,
        'overall_grade': overall_grade,
        'subject_count': subject_count,
        'complete_count': complete_count,
        'report_card': report_card,
    })
