import csv
import json
from urllib.parse import urlencode
from types import SimpleNamespace
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from academics.models import TeacherAssignment, TeacherClassAssignment
from assessments.models import Assessment, Grade
from .forms import OnlineExamForm, OnlineExamQuestionForm
from .models import OnlineExam, OnlineExamQuestion, ExamAttempt, ExamAnswer
from students.models import Student
from ai_engine.services.exam_engine import ExamGeneratorService, ExamGenerationError

MANAGER_ROLES = {'SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD'}


def _school_or_deny(user):
    school = getattr(user, 'school', None)
    if not school:
        raise PermissionDenied('Your account must be assigned to a school to use online examinations.')
    return school


def _is_manager(user):
    return getattr(user, 'role', '') in MANAGER_ROLES


def _can_manage_exam(user, exam):
    if exam.school_id != getattr(user, 'school_id', None):
        return False
    if _is_manager(user):
        return True
    if getattr(user, 'role', '') != 'TEACHER':
        return False
    return exam.created_by_id == user.id


def _get_student(user):
    if getattr(user, 'role', '') != 'STUDENT':
        raise PermissionDenied('This page is for student accounts.')
    try:
        student = user.student
    except Exception:
        student = None
    if not student or not student.school_class_id or student.school_id != user.school_id:
        raise PermissionDenied('Your student profile or class assignment is missing. Please contact the school office.')
    return student


def _exam_queryset_for_staff(user, school):
    qs = OnlineExam.objects.filter(school=school).select_related('school_class', 'subject', 'academic_term', 'created_by')
    if _is_manager(user):
        return qs
    if getattr(user, 'role', '') == 'TEACHER':
        return qs.filter(created_by=user)
    raise PermissionDenied('You do not have permission to manage online examinations.')


def _finalize_attempt(attempt, expired=False):
    if attempt.status != 'IN_PROGRESS':
        return attempt
    questions = list(attempt.exam.questions.all())
    answers_by_question = {answer.question_id: answer for answer in attempt.answers.all()}
    objective_marks = 0
    total_marks = 0
    needs_review = False
    for question in questions:
        total_marks += question.marks
        answer = answers_by_question.get(question.pk)
        if answer is None:
            answer = ExamAnswer.objects.create(attempt=attempt, question=question, answer_text='')
            answers_by_question[question.pk] = answer
        value = (answer.answer_text or '').strip()
        if question.question_type in ('MCQ', 'TRUE_FALSE'):
            correct = value.casefold() == (question.correct_answer or '').strip().casefold() and bool(value)
            answer.is_correct = correct
            answer.marks_awarded = question.marks if correct else 0
            answer.save(update_fields=['is_correct', 'marks_awarded', 'saved_at'])
            objective_marks += answer.marks_awarded
        elif question.question_type == 'SHORT_ANSWER' and question.correct_answer.strip():
            correct = value.casefold() == question.correct_answer.strip().casefold() and bool(value)
            answer.is_correct = correct
            answer.marks_awarded = question.marks if correct else 0
            answer.save(update_fields=['is_correct', 'marks_awarded', 'saved_at'])
            objective_marks += answer.marks_awarded
        else:
            answer.is_correct = None
            answer.marks_awarded = None
            answer.save(update_fields=['is_correct', 'marks_awarded', 'saved_at'])
            needs_review = True
    attempt.status = 'EXPIRED' if expired else 'SUBMITTED'
    attempt.submitted_at = timezone.now()
    attempt.score_awarded = objective_marks
    attempt.total_marks = total_marks
    attempt.grading_status = 'REVIEW_REQUIRED' if needs_review else 'GRADED'
    attempt.save(update_fields=['status', 'submitted_at', 'score_awarded', 'total_marks', 'grading_status', 'updated_at'])
    return attempt


@login_required
def exam_list(request):
    school = _school_or_deny(request.user)
    if getattr(request.user, 'role', '') == 'STUDENT':
        student = _get_student(request.user)
        exams = OnlineExam.objects.filter(
            school=school, school_class=student.school_class, student_access_enabled=True, status__in=['PUBLISHED', 'CLOSED']
        ).select_related('school_class', 'subject', 'academic_term').order_by('-opens_at')
        page_obj = Paginator(exams, 12).get_page(request.GET.get('page'))
        return render(request, 'online_exams/student_exam_list.html', {'exams': page_obj.object_list, 'page_obj': page_obj})
    base_qs = _exam_queryset_for_staff(request.user, school)
    exams = base_qs
    status_filter = request.GET.get('status', '').strip().upper()
    if status_filter in {'DRAFT', 'PUBLISHED', 'CLOSED'}:
        exams = exams.filter(status=status_filter)
    total_count = exams.count()
    page_obj = Paginator(exams, 20).get_page(request.GET.get('page'))
    return render(request, 'online_exams/exam_list.html', {
        'exams': page_obj.object_list, 'page_obj': page_obj, 'status_filter': status_filter,
        'total_count': total_count,
        'draft_count': base_qs.filter(status='DRAFT').count(),
        'published_count': base_qs.filter(status='PUBLISHED').count(),
    })


@login_required
def student_results(request):
    """Show a student's submitted attempts without leaking unreleased scores."""
    school = _school_or_deny(request.user)
    student = _get_student(request.user)
    attempts = ExamAttempt.objects.filter(
        student=student,
        exam__school=school,
        exam__school_class=student.school_class,
        exam__student_access_enabled=True,
        status__in=['SUBMITTED', 'EXPIRED'],
    ).select_related('exam', 'exam__subject', 'exam__academic_term').order_by('-submitted_at', '-started_at')
    page_obj = Paginator(attempts, 12).get_page(request.GET.get('page'))
    visible_attempts = list(page_obj.object_list)
    for attempt in visible_attempts:
        attempt.result_is_visible = bool(attempt.exam.results_released and attempt.grading_status == 'GRADED')
        attempt.result_passed_reference = bool(attempt.result_is_visible and attempt.percentage >= 50)
    return render(request, 'online_exams/student_results.html', {
        'attempts': visible_attempts,
        'page_obj': page_obj,
        'released_count': attempts.filter(exam__results_released=True, grading_status='GRADED').count(),
        'pending_count': attempts.exclude(exam__results_released=True, grading_status='GRADED').count(),
        'reference_pass_threshold': 50,
    })


@login_required
def student_result_detail(request, exam_id):
    """Show result and answer feedback only after the school releases graded results."""
    school = _school_or_deny(request.user)
    student = _get_student(request.user)
    exam = get_object_or_404(
        OnlineExam,
        pk=exam_id,
        school=school,
        school_class=student.school_class,
        student_access_enabled=True,
        status__in=['PUBLISHED', 'CLOSED'],
    )
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related('exam', 'student'),
        exam=exam,
        student=student,
        status__in=['SUBMITTED', 'EXPIRED'],
    )
    if not exam.results_released or attempt.grading_status != 'GRADED':
        messages.info(request, 'Your result and answer review will be available after the school releases your graded results.')
        return redirect('online_exams:student_results')
    answers = list(attempt.answers.select_related('question').order_by('question__order'))
    return render(request, 'online_exams/student_result_detail.html', {
        'exam': exam,
        'attempt': attempt,
        'answers': answers,
        'reference_pass_threshold': 50,
        'passed_reference': attempt.percentage >= 50,
    })


@login_required
def exam_create(request):
    school = _school_or_deny(request.user)
    if getattr(request.user, 'role', '') not in MANAGER_ROLES | {'TEACHER'}:
        raise PermissionDenied('You do not have permission to create an examination.')
    if request.method == 'POST':
        form = OnlineExamForm(request.POST, user=request.user)
        if form.is_valid():
            exam = form.save(commit=False)
            exam.school = school
            exam.created_by = request.user
            exam.save()
            messages.success(request, 'Examination draft created. Add questions, review it, then publish when ready.')
            return redirect('online_exams:exam_detail', exam_id=exam.pk)
    else:
        now = timezone.localtime(timezone.now())
        opens_at = (now + timedelta(minutes=15)).replace(second=0, microsecond=0)
        closes_at = opens_at + timedelta(minutes=45)
        active_year = school.academic_years.filter(is_active=True).first()
        active_term = active_year.terms.filter(is_active=True).first() if active_year else None
        form = OnlineExamForm(user=request.user, initial={
            'academic_term': active_term.pk if active_term else None,
            'duration_minutes': 45,
            'opens_at': opens_at,
            'closes_at': closes_at,
            'student_access_enabled': True,
        })
    return render(request, 'online_exams/exam_form.html', {'form': form, 'page_title': 'Create online examination'})


@login_required
def exam_edit(request, exam_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    if exam.status != 'DRAFT':
        messages.warning(request, 'Published examinations are locked. Close the examination before making administrative changes.')
        return redirect('online_exams:exam_detail', exam_id=exam.pk)
    if request.method == 'POST':
        form = OnlineExamForm(request.POST, instance=exam, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Examination settings updated.')
            return redirect('online_exams:exam_detail', exam_id=exam.pk)
    else:
        form = OnlineExamForm(instance=exam, user=request.user)
    return render(request, 'online_exams/exam_form.html', {'form': form, 'exam': exam, 'page_title': 'Edit examination'})


def _prepare_generated_questions(generated, allowed_types=None):
    """Validate AI output before it can alter a draft examination."""
    allowed_types = allowed_types or {'MCQ', 'TRUE_FALSE', 'SHORT_ANSWER', 'ESSAY'}
    prepared = []
    for item in generated:
        kind = str(item.get('type', '')).upper()
        text = str(item.get('question', '')).strip()
        answer = str(item.get('correct_answer', '')).strip()
        options = item.get('options') or []
        if kind not in allowed_types or not text or not answer:
            raise ExamGenerationError('The AI returned a question with missing or unsupported fields. Please try again.')
        if kind == 'MCQ':
            if not isinstance(options, list):
                raise ExamGenerationError('The AI returned invalid multiple-choice options. Please try again.')
            options = [str(option).strip() for option in options if str(option).strip()]
            if len(options) < 2 or answer not in options:
                raise ExamGenerationError('A generated multiple-choice answer does not match its options. Please regenerate.')
        elif kind == 'TRUE_FALSE':
            options = ['True', 'False']
            if answer.casefold() not in {'true', 'false'}:
                raise ExamGenerationError('The AI returned an invalid True/False answer. Please regenerate.')
            answer = 'True' if answer.casefold() == 'true' else 'False'
        else:
            options = []
        try:
            marks = int(item.get('points', 1))
        except (TypeError, ValueError):
            marks = 1
        prepared.append({
            'question_type': kind,
            'question_text': text,
            'correct_answer': answer,
            'options': options,
            'marks': max(1, min(100, marks)),
        })
    if not prepared:
        raise ExamGenerationError('The AI did not return any usable questions. Try again.')
    return prepared


def _generate_for_online_exam(exam, count, question_types, difficulty):
    grade = getattr(exam.school_class, 'grade_level', None)
    grade_name = getattr(grade, 'name', None) or exam.school_class.name
    ges_stage = getattr(grade, 'stage', None) or 'OTHER'
    generated = ExamGeneratorService.generate(
        subject=exam.subject.name,
        topic=(exam.topic or exam.title).strip(),
        grade_level=grade_name,
        difficulty=difficulty,
        num_questions=count,
        question_types=question_types,
        ges_stage=ges_stage,
    )
    prepared = _prepare_generated_questions(generated)
    if len(prepared) != count:
        raise ExamGenerationError(
            'The AI returned {} question(s), but {} were requested. No questions were changed; try again.'.format(len(prepared), count)
        )
    return prepared


def _prepare_exam_for_authoring(exam):
    """Allow edits to drafts and published exams with zero attempts only.

    Reopening a published exam automatically disables student access and moves it
    back to Draft before a question mutation, preventing mid-exam content changes.
    """
    if exam.status == 'DRAFT':
        return True
    if exam.status == 'PUBLISHED' and not exam.attempts.exists():
        exam.status = 'DRAFT'
        exam.student_access_enabled = False
        exam.save(update_fields=['status', 'student_access_enabled'])
        return True
    return False


@login_required
def exam_detail(request, exam_id):
    school = _school_or_deny(request.user)
    if getattr(request.user, 'role', '') == 'STUDENT':
        student = _get_student(request.user)
        exam = get_object_or_404(OnlineExam, pk=exam_id, school=school, school_class=student.school_class, student_access_enabled=True, status__in=['PUBLISHED', 'CLOSED'])
        attempt = ExamAttempt.objects.filter(exam=exam, student=student).first()
        return render(request, 'online_exams/student_exam_detail.html', {'exam': exam, 'attempt': attempt})
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    question_form = OnlineExamQuestionForm()
    if request.method == 'POST' and request.POST.get('action') == 'generate_ai_questions':
        if not _prepare_exam_for_authoring(exam):
            messages.error(request, 'Questions cannot be changed after students have started an attempt or the exam is closed.')
        else:
            try:
                try:
                    num_questions = int(request.POST.get('num_questions', '5'))
                except (TypeError, ValueError):
                    num_questions = 0
                if not 1 <= num_questions <= 20:
                    raise ExamGenerationError('Choose between 1 and 20 questions per generation request.')

                allowed_types = {'MCQ', 'TRUE_FALSE', 'SHORT_ANSWER', 'ESSAY'}
                question_types = [value for value in request.POST.getlist('question_types') if value in allowed_types]
                if not question_types:
                    raise ExamGenerationError('Select at least one question type.')

                grade = getattr(exam.school_class, 'grade_level', None)
                grade_name = getattr(grade, 'name', None) or exam.school_class.name
                ges_stage = getattr(grade, 'stage', None) or 'OTHER'
                difficulty = request.POST.get('difficulty', 'MEDIUM').upper()
                if difficulty not in {'EASY', 'MEDIUM', 'HARD'}:
                    difficulty = 'MEDIUM'

                generated = ExamGeneratorService.generate(
                    subject=exam.subject.name,
                    topic=(exam.topic or exam.title).strip(),
                    grade_level=grade_name,
                    difficulty=difficulty,
                    num_questions=num_questions,
                    question_types=question_types,
                    ges_stage=ges_stage,
                )

                # Validate the complete response before saving anything. AI output is
                # untrusted input and must never create malformed questions.
                prepared = []
                for index, item in enumerate(generated, start=1):
                    kind = str(item.get('type', '')).upper()
                    text = str(item.get('question', '')).strip()
                    answer = str(item.get('correct_answer', '')).strip()
                    options = item.get('options') or []
                    if kind not in allowed_types or not text or not answer:
                        raise ExamGenerationError('The AI returned a question with missing or unsupported fields. Please try again.')
                    if kind == 'MCQ':
                        if not isinstance(options, list):
                            raise ExamGenerationError('The AI returned invalid multiple-choice options. Please try again.')
                        options = [str(option).strip() for option in options if str(option).strip()]
                        if len(options) < 2 or answer not in options:
                            raise ExamGenerationError('The AI returned a multiple-choice question whose answer does not match its options. Please regenerate the questions.')
                    elif kind == 'TRUE_FALSE':
                        options = ['True', 'False']
                        if answer.casefold() not in {'true', 'false'}:
                            raise ExamGenerationError('The AI returned an invalid True/False answer. Please regenerate the questions.')
                        answer = 'True' if answer.casefold() == 'true' else 'False'
                    else:
                        options = []
                    try:
                        marks = int(item.get('points', 1))
                    except (TypeError, ValueError):
                        marks = 1
                    marks = max(1, min(100, marks))
                    prepared.append({
                        'question_type': kind,
                        'question_text': text,
                        'correct_answer': answer,
                        'options': options,
                        'marks': marks,
                    })

                with transaction.atomic():
                    next_order = (exam.questions.order_by('-order').values_list('order', flat=True).first() or 0) + 1
                    OnlineExamQuestion.objects.bulk_create([
                        OnlineExamQuestion(exam=exam, order=next_order + offset, **item)
                        for offset, item in enumerate(prepared)
                    ])
                messages.success(request, 'Generated {} questions. Review every question and answer before publishing.'.format(len(prepared)))
                return redirect('online_exams:exam_detail', exam_id=exam.pk)
            except ExamGenerationError as exc:
                messages.error(request, str(exc))
            except Exception as exc:
                # Keep provider/JSON failures recoverable without exposing stack traces.
                messages.error(request, 'AI question generation failed. Check the AI provider configuration or try again later.')
    elif request.method == 'POST' and request.POST.get('action') == 'regenerate_all_questions':
        if not _prepare_exam_for_authoring(exam):
            messages.error(request, 'Questions cannot be changed after students have started an attempt or the exam is closed.')
        elif not exam.questions.exists():
            messages.error(request, 'There are no questions to regenerate. Generate or add questions first.')
        else:
            try:
                existing = list(exam.questions.order_by('order'))
                count = len(existing)
                if count > 30:
                    raise ExamGenerationError('Regenerate all supports up to 30 questions at once. Reduce the draft to 30 questions or fewer first.')
                allowed_types = {'MCQ', 'TRUE_FALSE', 'SHORT_ANSWER', 'ESSAY'}
                selected_types = []
                for question in existing:
                    if question.question_type in allowed_types and question.question_type not in selected_types:
                        selected_types.append(question.question_type)
                difficulty = request.POST.get('difficulty', 'MEDIUM').upper()
                if difficulty not in {'EASY', 'MEDIUM', 'HARD'}:
                    difficulty = 'MEDIUM'
                prepared = _generate_for_online_exam(exam, count, selected_types or ['MCQ'], difficulty)
                # Validate first; then replace the current draft question set atomically.
                with transaction.atomic():
                    for question, item in zip(existing, prepared):
                        for field, value in item.items():
                            setattr(question, field, value)
                        question.save(update_fields=['question_type', 'question_text', 'correct_answer', 'options', 'marks'])
                messages.success(request, 'Regenerated all {} questions. Review the new questions, answers and marks before publishing.'.format(count))
                return redirect('online_exams:exam_detail', exam_id=exam.pk)
            except ExamGenerationError as exc:
                messages.error(request, str(exc))
            except Exception:
                messages.error(request, 'Question regeneration failed. No complete replacement was made; check the AI provider and try again.')
    elif request.method == 'POST' and request.POST.get('action') == 'add_question':
        if not _prepare_exam_for_authoring(exam):
            messages.error(request, 'Questions cannot be changed after students have started an attempt or the exam is closed.')
        else:
            question_form = OnlineExamQuestionForm(request.POST)
            if question_form.is_valid():
                question = question_form.save(commit=False)
                question.exam = exam
                question.order = (exam.questions.order_by('-order').values_list('order', flat=True).first() or 0) + 1
                question.save()
                messages.success(request, 'Question added.')
                return redirect('online_exams:exam_detail', exam_id=exam.pk)
    all_attempts = exam.attempts.select_related('student__user').order_by('-started_at')
    attempt_total = all_attempts.count()
    in_progress_count = all_attempts.filter(status='IN_PROGRESS').count()
    graded_count = all_attempts.filter(status__in=['SUBMITTED', 'EXPIRED'], grading_status='GRADED').count()
    pending_review_count = all_attempts.exclude(grading_status='GRADED').exclude(status='IN_PROGRESS').count()
    submitted_count = all_attempts.exclude(status='IN_PROGRESS').count()

    # Keep filters constrained to known values and paginate the full attempt list.
    grading_filter = request.GET.get('grading', 'ALL').upper()
    status_filter = request.GET.get('attempt_status', 'ALL').upper()
    attempts = all_attempts
    if grading_filter in {'PENDING', 'REVIEW_REQUIRED', 'GRADED'}:
        attempts = attempts.filter(grading_status=grading_filter)
    else:
        grading_filter = 'ALL'
    if status_filter in {'IN_PROGRESS', 'SUBMITTED', 'EXPIRED'}:
        attempts = attempts.filter(status=status_filter)
    else:
        status_filter = 'ALL'
    attempt_page = Paginator(attempts, 20).get_page(request.GET.get('page'))

    can_edit_questions = exam.status == 'DRAFT' or (exam.status == 'PUBLISHED' and attempt_total == 0)
    can_release_results = (
        exam.status == 'CLOSED' and attempt_total > 0 and in_progress_count == 0
        and pending_review_count == 0 and submitted_count > 0
    )
    can_export_results = can_release_results and exam.results_released
    return render(request, 'online_exams/exam_detail.html', {
        'exam': exam, 'question_form': question_form, 'attempts': attempt_page.object_list,
        'attempt_page': attempt_page, 'attempt_total': attempt_total,
        'in_progress_count': in_progress_count, 'graded_count': graded_count,
        'pending_review_count': pending_review_count, 'submitted_count': submitted_count,
        'grading_filter': grading_filter, 'status_filter': status_filter,
        'can_release_results': can_release_results,
        'can_export_results': can_export_results, 'can_edit_questions': can_edit_questions,
    })


@login_required
@require_POST
def question_update(request, exam_id, question_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    question = get_object_or_404(OnlineExamQuestion, pk=question_id, exam=exam)
    if not _prepare_exam_for_authoring(exam):
        messages.error(request, 'Questions cannot be changed after students have started an attempt or the exam is closed.')
        return redirect('online_exams:exam_detail', exam_id=exam.pk)
    form = OnlineExamQuestionForm(request.POST, instance=question)
    if form.is_valid():
        form.save()
        messages.success(request, 'Question {}, answer options and marks updated.'.format(question.order))
    else:
        details = '; '.join('{}: {}'.format(label, ', '.join(errors)) for label, errors in form.errors.items())
        messages.error(request, 'Question was not saved. {}'.format(details or 'Check the entered values.'))
    return redirect('online_exams:exam_detail', exam_id=exam.pk)


@login_required
@require_POST
def question_regenerate(request, exam_id, question_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    question = get_object_or_404(OnlineExamQuestion, pk=question_id, exam=exam)
    if not _prepare_exam_for_authoring(exam):
        messages.error(request, 'Questions cannot be changed after students have started an attempt or the exam is closed.')
        return redirect('online_exams:exam_detail', exam_id=exam.pk)
    grade = getattr(exam.school_class, 'grade_level', None)
    grade_name = getattr(grade, 'name', None) or exam.school_class.name
    adapter_exam = SimpleNamespace(
        subject=exam.subject.name,
        topic=exam.topic or exam.title,
        title=exam.title,
        grade_level=grade_name,
        difficulty=request.POST.get('difficulty', 'MEDIUM').upper(),
        school_class=exam.school_class,
    )
    if adapter_exam.difficulty not in {'EASY', 'MEDIUM', 'HARD'}:
        adapter_exam.difficulty = 'MEDIUM'
    try:
        generated = ExamGeneratorService.generate_replacement_question(adapter_exam, question)
        prepared = _prepare_generated_questions([generated])[0]
        if prepared['question_type'] != question.question_type:
            raise ExamGenerationError('The AI returned a different question type. Nothing was changed; try regenerating again.')
        for field, value in prepared.items():
            setattr(question, field, value)
        question.save(update_fields=['question_type', 'question_text', 'correct_answer', 'options', 'marks'])
        messages.success(request, 'Question {} regenerated. Review the answer and marks before publishing.'.format(question.order))
    except ExamGenerationError as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, 'Could not regenerate this question. Check the AI provider and try again.')
    return redirect('online_exams:exam_detail', exam_id=exam.pk)


@login_required
@require_POST
def question_delete(request, exam_id, question_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    if not _prepare_exam_for_authoring(exam):
        messages.error(request, 'Questions cannot be changed after students have started an attempt or the exam is closed.')
    else:
        get_object_or_404(OnlineExamQuestion, pk=question_id, exam=exam).delete()
        messages.success(request, 'Question removed.')
    return redirect('online_exams:exam_detail', exam_id=exam.pk)


@login_required
@require_POST
def exam_publish(request, exam_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    if exam.status != 'DRAFT':
        messages.info(request, 'This examination is not a draft.')
    elif not exam.questions.exists():
        messages.error(request, 'Add at least one question before publishing.')
    elif exam.closes_at <= exam.opens_at:
        messages.error(request, 'The closing time must be later than the opening time.')
    elif exam.closes_at <= timezone.now():
        messages.error(request, 'The closing time has already passed. Update the schedule before publishing.')
    else:
        exam.status = 'PUBLISHED'
        exam.published_at = timezone.now()
        exam.save(update_fields=['status', 'published_at', 'updated_at'])
        if exam.student_access_enabled:
            messages.success(request, 'Examination published. Students in the selected class can see it during the scheduled window.')
        else:
            messages.success(request, 'Examination published for staff management only. It is not visible in the student online examination portal.')
    return redirect('online_exams:exam_detail', exam_id=exam.pk)


@login_required
@require_POST
def exam_close(request, exam_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    if exam.status != 'PUBLISHED':
        messages.info(request, 'Only a published examination can be closed.')
        return redirect('online_exams:exam_detail', exam_id=exam.pk)
    with transaction.atomic():
        for active_attempt in ExamAttempt.objects.select_for_update().filter(exam=exam, status='IN_PROGRESS'):
            _finalize_attempt(active_attempt, expired=True)
        exam.status = 'CLOSED'
        exam.save(update_fields=['status', 'updated_at'])
    messages.success(request, 'Examination closed. Any in-progress attempts were submitted using their saved answers.')
    return redirect('online_exams:exam_detail', exam_id=exam.pk)


@login_required
@require_POST
def exam_release_results(request, exam_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    if exam.status != 'CLOSED':
        messages.error(request, 'Close the examination first so no new attempts can begin before releasing results.')
    elif not exam.attempts.exists():
        messages.error(request, 'There are no submitted attempts to release results for yet.')
    elif exam.attempts.filter(status='IN_PROGRESS').exists():
        messages.error(request, 'There are still attempts in progress. Close the examination again to finalize saved answers.')
    elif exam.attempts.exclude(grading_status='GRADED').exists():
        messages.error(request, 'Results cannot be released until all submitted attempts have been graded or reviewed.')
    else:
        exam.results_released = True
        exam.save(update_fields=['results_released', 'updated_at'])
        messages.success(request, 'Results released to students who have submitted an attempt.')
    return redirect('online_exams:exam_detail', exam_id=exam.pk)


@login_required
@require_POST
def exam_export_results(request, exam_id):
    """Export a fully reviewed and released online exam into the existing gradebook.

    This is deliberately explicit and idempotent: it creates one linked Assessment
    record per online exam and upserts each student's Grade. It does not overwrite
    explicit TerminalResult rows or change the 30/70 result calculation code.
    """
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)

    if exam.status != 'CLOSED' or not exam.results_released:
        messages.error(request, 'Close the examination, finish all marking, and release results before exporting to the gradebook.')
        return redirect('online_exams:exam_detail', exam_id=exam.pk)

    with transaction.atomic():
        exam = OnlineExam.objects.select_for_update().get(pk=exam.pk, school=school)
        attempts = list(ExamAttempt.objects.select_for_update().filter(exam=exam).select_related('student'))
        if not attempts:
            messages.error(request, 'There are no student attempts to export.')
            return redirect('online_exams:exam_detail', exam_id=exam.pk)
        if any(a.status == 'IN_PROGRESS' for a in attempts):
            messages.error(request, 'An attempt is still in progress. Close the examination before exporting results.')
            return redirect('online_exams:exam_detail', exam_id=exam.pk)
        if any(a.grading_status != 'GRADED' for a in attempts):
            messages.error(request, 'All submitted attempts must be graded before exporting results.')
            return redirect('online_exams:exam_detail', exam_id=exam.pk)

        max_score = int(exam.total_marks)
        if max_score <= 0:
            messages.error(request, 'This examination has no valid total marks and cannot be exported.')
            return redirect('online_exams:exam_detail', exam_id=exam.pk)

        assessment = exam.assessment_record
        if assessment is None:
            assessment = Assessment.objects.create(
                school=school,
                school_class=exam.school_class,
                academic_term=exam.academic_term,
                title='Online Examination — {}'.format(exam.title)[:200],
                subject=exam.subject.name,
                assessment_type='EXAM',
                score_component='EXAM',
                max_score=max_score,
            )
            exam.assessment_record = assessment
            exam.save(update_fields=['assessment_record', 'updated_at'])
        else:
            # Keep the linked assessment aligned with the authoritative exam scale.
            assessment.school = school
            assessment.school_class = exam.school_class
            assessment.academic_term = exam.academic_term
            assessment.subject = exam.subject.name
            assessment.assessment_type = 'EXAM'
            assessment.score_component = 'EXAM'
            assessment.max_score = max_score
            assessment.save(update_fields=['school', 'school_class', 'academic_term', 'subject', 'assessment_type', 'score_component', 'max_score'])

        for attempt in attempts:
            score = min(max(0, int(attempt.score_awarded)), max_score)
            Grade.objects.update_or_create(
                assessment=assessment, student=attempt.student,
                defaults={
                    'score_achieved': score,
                    'teacher_notes': 'Imported from online examination: {} (attempt {}).'.format(exam.title, attempt.pk),
                    'graded_by': request.user,
                },
            )

    messages.success(request, 'Exported {} reviewed student result(s) to the existing Assessment Gradebook.'.format(len(attempts)))
    return redirect('online_exams:exam_detail', exam_id=exam.pk)



def _csv_safe(value):
    value = '' if value is None else str(value)
    if value.startswith(('=', '+', '-', '@', '\t', '\r')):
        return "'" + value
    return value


def _percentage_band(value):
    """Return a descriptive score band without claiming it is the school's official grade."""
    if value < 40:
        return 'Below 40%'
    if value < 50:
        return '40–49%'
    if value < 60:
        return '50–59%'
    if value < 70:
        return '60–69%'
    if value < 80:
        return '70–79%'
    return '80–100%'


def _exam_analytics_data(exam):
    attempts = list(
        ExamAttempt.objects.filter(exam=exam)
        .select_related('student__user')
        .prefetch_related('answers__question')
        .order_by('student__user__last_name', 'student__user__first_name', 'student__user__username')
    )
    completed = [a for a in attempts if a.status != 'IN_PROGRESS']
    graded = [a for a in completed if a.grading_status == 'GRADED']
    pending_review = [a for a in completed if a.grading_status != 'GRADED']
    roster_count = Student.objects.filter(
        school=exam.school, school_class=exam.school_class, is_active=True
    ).count()

    percentages = [a.percentage for a in graded if a.total_marks > 0]
    average_percentage = round(sum(percentages) / len(percentages), 1) if percentages else 0
    sorted_percentages = sorted(percentages)
    if sorted_percentages:
        middle = len(sorted_percentages) // 2
        median_percentage = (
            sorted_percentages[middle] if len(sorted_percentages) % 2
            else round((sorted_percentages[middle - 1] + sorted_percentages[middle]) / 2, 1)
        )
    else:
        median_percentage = 0

    # This is a reference indicator only, not an official school grading rule.
    at_or_above_50 = sum(1 for score in percentages if score >= 50)
    reference_pass_rate = round((at_or_above_50 / len(percentages)) * 100, 1) if percentages else 0

    band_specs = [
        ('Below 40%', 0, 40), ('40–49%', 40, 50), ('50–59%', 50, 60),
        ('60–69%', 60, 70), ('70–79%', 70, 80), ('80–100%', 80, 101),
    ]
    distribution = []
    for label, lower, upper in band_specs:
        count = sum(1 for score in percentages if lower <= score < upper)
        distribution.append({
            'label': label,
            'count': count,
            'percent': round((count / len(percentages)) * 100, 1) if percentages else 0,
        })

    questions = list(exam.questions.all())
    question_stats = []
    for question in questions:
        graded_answers = []
        for attempt in graded:
            answer = next((a for a in attempt.answers.all() if a.question_id == question.pk), None)
            if answer is not None:
                graded_answers.append(answer)
        possible = len(graded) * question.marks
        awarded = sum(int(answer.marks_awarded or 0) for answer in graded_answers)
        responded = sum(1 for answer in graded_answers if (answer.answer_text or '').strip())
        correct = sum(1 for answer in graded_answers if answer.is_correct is True)
        question_stats.append({
            'question': question,
            'graded_responses': len(graded_answers),
            'responded': responded,
            'unanswered': max(0, len(graded) - responded),
            'correct': correct,
            'average_percent': round((awarded / possible) * 100, 1) if possible else 0,
            'has_correctness': any(answer.is_correct is not None for answer in graded_answers),
        })

    student_rows = []
    for attempt in completed:
        student = attempt.student
        user = student.user
        student_name = (user.get_full_name() or user.get_username()).strip()
        student_rows.append({
            'attempt': attempt,
            'student_name': student_name,
            'admission_number': getattr(student, 'admission_number', ''),
            'has_score': attempt.grading_status == 'GRADED',
            'percentage': attempt.percentage if attempt.grading_status == 'GRADED' else None,
            'band': _percentage_band(attempt.percentage) if attempt.grading_status == 'GRADED' else 'Awaiting review',
        })

    return {
        'attempts': attempts,
        'completed_count': len(completed),
        'graded_count': len(graded),
        'pending_review_count': len(pending_review),
        'in_progress_count': sum(1 for a in attempts if a.status == 'IN_PROGRESS'),
        'roster_count': roster_count,
        'not_attempted_count': max(0, roster_count - len(attempts)),
        'participation_rate': round((len({a.student_id for a in completed}) / roster_count) * 100, 1) if roster_count else 0,
        'average_percentage': average_percentage,
        'median_percentage': median_percentage,
        'reference_pass_rate': reference_pass_rate,
        'at_or_above_50_count': at_or_above_50,
        'distribution': distribution,
        'question_stats': question_stats,
        'student_rows': student_rows,
    }


@login_required
def exam_analytics(request, exam_id):
    """Show internal performance analytics to authorized staff after an exam closes."""
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    if exam.status != 'CLOSED':
        messages.info(request, 'Performance analytics are available after the examination is closed.')
        return redirect('online_exams:exam_detail', exam_id=exam.pk)

    data = _exam_analytics_data(exam)
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="online-exam-{}-results.csv"'.format(exam.pk)
        response.write('\ufeff')  # Excel-friendly UTF-8 BOM.
        writer = csv.writer(response)
        writer.writerow(['Examination', _csv_safe(exam.title)])
        writer.writerow(['Class', _csv_safe(exam.school_class.name)])
        writer.writerow(['Subject', _csv_safe(exam.subject.name)])
        writer.writerow(['Academic term', str(exam.academic_term)])
        writer.writerow([])
        writer.writerow(['Admission number', 'Student', 'Attempt status', 'Grading status', 'Marks awarded', 'Total marks', 'Percentage', 'Submitted at'])
        for row in data['student_rows']:
            attempt = row['attempt']
            writer.writerow([
                _csv_safe(row['admission_number']), _csv_safe(row['student_name']), attempt.get_status_display(),
                attempt.get_grading_status_display(),
                attempt.score_awarded if attempt.grading_status == 'GRADED' else '',
                attempt.total_marks if attempt.grading_status == 'GRADED' else '',
                attempt.percentage if attempt.grading_status == 'GRADED' else '',
                timezone.localtime(attempt.submitted_at).strftime('%Y-%m-%d %H:%M') if attempt.submitted_at else '',
            ])
        return response

    data.update({'exam': exam, 'reference_pass_threshold': 50})
    return render(request, 'online_exams/exam_analytics.html', data)


@login_required
def exam_take(request, exam_id):
    school = _school_or_deny(request.user)
    student = _get_student(request.user)
    exam = get_object_or_404(OnlineExam, pk=exam_id, school=school, school_class=student.school_class, student_access_enabled=True, status='PUBLISHED')
    attempt = ExamAttempt.objects.filter(exam=exam, student=student).first()
    if request.method == 'POST' and request.POST.get('action') == 'start':
        now = timezone.now()
        if not (exam.opens_at <= now < exam.closes_at):
            messages.error(request, 'This examination is not currently open.')
            return redirect('online_exams:exam_detail', exam_id=exam.pk)
        if attempt:
            return redirect('online_exams:exam_take', exam_id=exam.pk)
        try:
            attempt = ExamAttempt.objects.create(exam=exam, student=student)
        except IntegrityError:
            attempt = ExamAttempt.objects.get(exam=exam, student=student)
        return redirect('online_exams:exam_take', exam_id=exam.pk)
    if not attempt:
        return redirect('online_exams:exam_detail', exam_id=exam.pk)
    if attempt.status != 'IN_PROGRESS':
        return render(request, 'online_exams/exam_submitted.html', {'exam': exam, 'attempt': attempt})
    if timezone.now() >= attempt.deadline or exam.status != 'PUBLISHED':
        _finalize_attempt(attempt, expired=True)
        messages.warning(request, 'Your examination time has ended. Your saved answers have been submitted.')
        return redirect('online_exams:exam_take', exam_id=exam.pk)
    questions = list(exam.questions.all())
    if exam.randomize_questions:
        # Stable per attempt order: do not reshuffle on each refresh.
        import random
        random.Random(str(attempt.pk)).shuffle(questions)
    saved = {str(answer.question_id): answer.answer_text for answer in attempt.answers.all()}
    question_rows = [{'question': question, 'answer': saved.get(str(question.pk), '')} for question in questions]
    remaining_seconds = max(0, int((attempt.deadline - timezone.now()).total_seconds()))
    if request.method == 'POST' and request.POST.get('action') == 'submit':
        for question in questions:
            value = request.POST.get('answer_{}'.format(question.pk), '').strip()
            ExamAnswer.objects.update_or_create(attempt=attempt, question=question, defaults={'answer_text': value})
        is_late = timezone.now() >= attempt.deadline
        _finalize_attempt(attempt, expired=is_late)
        if is_late:
            messages.warning(request, 'The examination deadline had passed. Your saved answers have been submitted as expired.')
        else:
            messages.success(request, 'Your answers have been submitted. Results will appear after the school releases them.')
        return redirect('online_exams:exam_take', exam_id=exam.pk)
    return render(request, 'online_exams/exam_take.html', {
        'exam': exam, 'attempt': attempt, 'questions': questions, 'question_rows': question_rows,
        'remaining_seconds': remaining_seconds,
    })


@login_required
@require_POST
def answer_autosave(request, exam_id):
    student = _get_student(request.user)
    try:
        payload = json.loads(request.body.decode('utf-8'))
        question_id = payload.get('question_id')
        value = str(payload.get('answer', ''))[:20000]
    except (ValueError, AttributeError, TypeError):
        return HttpResponseBadRequest('Invalid answer payload.')
    attempt = get_object_or_404(ExamAttempt, exam_id=exam_id, student=student, status='IN_PROGRESS')
    if timezone.now() >= attempt.deadline or attempt.exam.status != 'PUBLISHED':
        _finalize_attempt(attempt, expired=True)
        return JsonResponse({'ok': False, 'expired': True, 'message': 'Time has ended; saved answers were submitted.'}, status=409)
    question = get_object_or_404(OnlineExamQuestion, pk=question_id, exam=attempt.exam)
    ExamAnswer.objects.update_or_create(attempt=attempt, question=question, defaults={'answer_text': value})
    return JsonResponse({'ok': True, 'saved_at': timezone.localtime().strftime('%H:%M:%S')})


@login_required
@require_POST
def exam_bulk_finalize_reviews(request, exam_id):
    """Finalize selected attempts with complete, valid written-response marks."""
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    gradebook_params = {}
    for key in ('q', 'grading', 'attempt_status', 'sort', 'page_size', 'page'):
        value = request.POST.get(key, '').strip()
        if value:
            gradebook_params[key] = value

    def return_to_gradebook():
        url = redirect('online_exams:exam_gradebook', exam_id=exam.pk).url
        return redirect(url + ('?' + urlencode(gradebook_params) if gradebook_params else ''))

    if exam.results_released:
        messages.error(request, 'Results have been released. Grading is locked.')
        return return_to_gradebook()

    selected_ids = list(dict.fromkeys(request.POST.getlist('attempt_ids')))
    if not selected_ids:
        messages.warning(request, 'Select at least one submitted attempt first.')
        return return_to_gradebook()

    completed = 0
    already_graded = 0
    missing_marks = 0
    invalid_marks = 0
    not_eligible = 0
    processed_ids = set()

    with transaction.atomic():
        selected = ExamAttempt.objects.select_for_update().filter(
            exam=exam, pk__in=selected_ids, status__in=['SUBMITTED', 'EXPIRED']
        ).prefetch_related('answers__question')
        for attempt in selected:
            processed_ids.add(str(attempt.pk))
            if attempt.grading_status == 'GRADED':
                already_graded += 1
                continue

            answers = list(attempt.answers.all())
            written_questions = exam.questions.filter(question_type__in=('SHORT_ANSWER', 'ESSAY'))
            answers_by_question = {a.question_id: a for a in answers}
            # Every written question must have an answer record and a teacher-entered mark.
            if any(
                question.pk not in answers_by_question or
                answers_by_question[question.pk].marks_awarded is None
                for question in written_questions
            ):
                missing_marks += 1
                continue

            invalid = any(
                a.marks_awarded is not None and
                (a.marks_awarded < 0 or a.marks_awarded > a.question.marks)
                for a in answers
            )
            if invalid:
                invalid_marks += 1
                continue

            attempt.score_awarded = sum(int(a.marks_awarded or 0) for a in answers)
            attempt.total_marks = sum(exam.questions.values_list('marks', flat=True))
            attempt.grading_status = 'GRADED'
            attempt.save(update_fields=['score_awarded', 'total_marks', 'grading_status', 'updated_at'])
            completed += 1

    not_eligible = len(set(map(str, selected_ids)) - processed_ids)
    if completed:
        messages.success(request, 'Finalized {} selected attempt(s).'.format(completed))
    if already_graded:
        messages.info(request, '{} attempt(s) skipped because they were already graded.'.format(already_graded))
    if missing_marks:
        messages.warning(request, '{} attempt(s) skipped because one or more written responses still need marks.'.format(missing_marks))
    if invalid_marks:
        messages.error(request, '{} attempt(s) skipped because one or more marks are outside the allowed range.'.format(invalid_marks))
    if not_eligible:
        messages.warning(request, '{} selected item(s) were not eligible submitted attempts for this examination.'.format(not_eligible))
    if not any((completed, already_graded, missing_marks, invalid_marks, not_eligible)):
        messages.warning(request, 'No eligible submitted attempts were found.')
    return return_to_gradebook()


@login_required
def exam_gradebook_csv(request, exam_id):
    """Download a staff-authorized CSV snapshot of this exam's gradebook."""
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="online-exam-gradebook-{}.csv"'.format(exam.pk)
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Examination', _csv_safe(exam.title)])
    writer.writerow(['Class', _csv_safe(exam.school_class.name), 'Subject', _csv_safe(exam.subject.name), 'Maximum marks', exam.total_marks])
    writer.writerow([])
    writer.writerow(['Student name', 'Username', 'Student ID', 'Attempt status', 'Grading status', 'Submitted at', 'Score', 'Maximum marks', 'Percentage'])
    # Keep CSV exports aligned with the active gradebook search, filters and sort.
    attempts = ExamAttempt.objects.filter(exam=exam).select_related('student__user')
    grading_filter = request.GET.get('grading', 'ALL').strip().upper()
    status_filter = request.GET.get('attempt_status', 'ALL').strip().upper()
    search_query = request.GET.get('q', '').strip()[:100]
    sort_by = request.GET.get('sort', 'student').strip().lower()
    if grading_filter in {'PENDING', 'REVIEW_REQUIRED', 'GRADED'}:
        attempts = attempts.filter(grading_status=grading_filter)
    if status_filter in {'IN_PROGRESS', 'SUBMITTED', 'EXPIRED'}:
        attempts = attempts.filter(status=status_filter)
    if search_query:
        attempts = attempts.filter(
            Q(student__user__first_name__icontains=search_query)
            | Q(student__user__last_name__icontains=search_query)
            | Q(student__user__username__icontains=search_query)
            | Q(student__admission_number__icontains=search_query)
        )
    export_ordering = {
        'recent': '-started_at',
        'oldest': 'started_at',
        'student': 'student__user__last_name',
        'score_high': '-score_awarded',
        'score_low': 'score_awarded',
    }
    attempts = attempts.order_by(export_ordering.get(sort_by, 'student__user__last_name'),
                                 'student__user__first_name', 'student__user__username')
    for attempt in attempts.iterator():
        student_user = attempt.student.user
        score = attempt.score_awarded if attempt.status != 'IN_PROGRESS' else ''
        maximum = attempt.total_marks if attempt.status != 'IN_PROGRESS' else ''
        percentage = attempt.percentage if attempt.status != 'IN_PROGRESS' else ''
        submitted = timezone.localtime(attempt.submitted_at).strftime('%Y-%m-%d %H:%M') if attempt.submitted_at else ''
        writer.writerow([
            _csv_safe(student_user.get_full_name() or student_user.username),
            _csv_safe(student_user.username),
            _csv_safe(getattr(attempt.student, 'student_id', '') or attempt.student.pk),
            attempt.get_status_display(), attempt.get_grading_status_display(), submitted, score, maximum, percentage,
        ])
    return response



@login_required
def exam_gradebook(request, exam_id):
    """Dedicated teacher/admin workspace for an exam's student attempts."""
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    attempts = exam.attempts.select_related('student__user')

    grading_filter = request.GET.get('grading', 'ALL').strip().upper()
    status_filter = request.GET.get('attempt_status', 'ALL').strip().upper()
    search_query = request.GET.get('q', '').strip()[:100]
    sort_by = request.GET.get('sort', 'recent').strip().lower()
    try:
        page_size = int(request.GET.get('page_size', '20'))
    except (TypeError, ValueError):
        page_size = 20
    if page_size not in {20, 50, 100}:
        page_size = 20
    allowed_grading = {'ALL', 'PENDING', 'REVIEW_REQUIRED', 'GRADED'}
    allowed_status = {'ALL', 'IN_PROGRESS', 'SUBMITTED', 'EXPIRED'}
    allowed_sort = {
        'recent': '-started_at',
        'oldest': 'started_at',
        'student': 'student__user__last_name',
        'score_high': '-score_awarded',
        'score_low': 'score_awarded',
    }
    if grading_filter not in allowed_grading:
        grading_filter = 'ALL'
    if status_filter not in allowed_status:
        status_filter = 'ALL'
    if sort_by not in allowed_sort:
        sort_by = 'recent'
    if grading_filter != 'ALL':
        attempts = attempts.filter(grading_status=grading_filter)
    if status_filter != 'ALL':
        attempts = attempts.filter(status=status_filter)
    if search_query:
        attempts = attempts.filter(
            Q(student__user__first_name__icontains=search_query)
            | Q(student__user__last_name__icontains=search_query)
            | Q(student__user__username__icontains=search_query)
            | Q(student__admission_number__icontains=search_query)
        )
    attempts = attempts.order_by(allowed_sort[sort_by], 'student__user__first_name', 'student__user__last_name')

    summary_qs = exam.attempts.all()
    total_attempts = summary_qs.count()
    submitted_count = summary_qs.filter(status__in=['SUBMITTED', 'EXPIRED']).count()
    pending_count = summary_qs.filter(status__in=['SUBMITTED', 'EXPIRED']).exclude(grading_status='GRADED').count()
    graded_count = summary_qs.filter(grading_status='GRADED').count()
    in_progress_count = summary_qs.filter(status='IN_PROGRESS').count()
    page_obj = Paginator(attempts, page_size).get_page(request.GET.get('page'))
    return render(request, 'online_exams/exam_gradebook.html', {
        'exam': exam, 'attempts': page_obj.object_list, 'page_obj': page_obj,
        'grading_filter': grading_filter, 'status_filter': status_filter,
        'search_query': search_query, 'sort_by': sort_by, 'page_size': page_size,
        'total_attempts': total_attempts, 'submitted_count': submitted_count,
        'pending_count': pending_count, 'graded_count': graded_count,
        'in_progress_count': in_progress_count,
        'can_export_results': (exam.status == 'CLOSED' and exam.results_released and total_attempts > 0
            and in_progress_count == 0 and pending_count == 0),
    })


@login_required
def attempt_review(request, exam_id, attempt_id):
    school = _school_or_deny(request.user)
    exam = get_object_or_404(_exam_queryset_for_staff(request.user, school), pk=exam_id)
    attempt = get_object_or_404(ExamAttempt.objects.select_related('student__user'), pk=attempt_id, exam=exam)
    if attempt.status == 'IN_PROGRESS':
        messages.warning(request, 'This attempt has not been submitted yet.')
        return redirect('online_exams:exam_detail', exam_id=exam.pk)
    answers = list(attempt.answers.select_related('question').order_by('question__order'))
    if exam.results_released and request.method == 'POST':
        messages.error(request, 'Results have already been released. Marks are locked to preserve the published gradebook.')
        return redirect('online_exams:attempt_review', exam_id=exam.pk, attempt_id=attempt.pk)
    if request.method == 'POST':
        for answer in answers:
            field = 'marks_{}'.format(answer.pk)
            if answer.question.question_type in ('SHORT_ANSWER', 'ESSAY'):
                raw = request.POST.get(field, '').strip()
                if raw == '':
                    answer.marks_awarded = 0
                else:
                    try:
                        marks = int(raw)
                    except ValueError:
                        messages.error(request, 'Marks must be whole numbers.')
                        return render(request, 'online_exams/attempt_review.html', {'exam': exam, 'attempt': attempt, 'answers': answers, 'read_only': exam.results_released})
                    if marks < 0 or marks > answer.question.marks:
                        messages.error(request, 'Marks must be between 0 and the maximum for that question.')
                        return render(request, 'online_exams/attempt_review.html', {'exam': exam, 'attempt': attempt, 'answers': answers, 'read_only': exam.results_released})
                    answer.marks_awarded = marks
                answer.save(update_fields=['marks_awarded', 'saved_at'])
        attempt.score_awarded = sum(answer.marks_awarded or 0 for answer in attempt.answers.all())
        attempt.total_marks = sum(exam.questions.values_list('marks', flat=True))
        attempt.grading_status = 'GRADED'
        attempt.save(update_fields=['score_awarded', 'total_marks', 'grading_status', 'updated_at'])
        messages.success(request, 'Attempt reviewed and graded.')
        # When review was opened from the gradebook, return to that same filtered
        # gradebook view instead of unexpectedly sending the teacher to exam detail.
        if request.GET.get('from_gradebook') == '1':
            params = {}
            for key in ('q', 'grading', 'attempt_status', 'sort', 'page_size', 'page'):
                value = request.GET.get(key, '').strip()
                if value:
                    params[key] = value[:100]
            return_url = redirect('online_exams:exam_gradebook', exam_id=exam.pk).url
            return redirect(return_url + ('?' + urlencode(params) if params else ''))
        return redirect('online_exams:exam_detail', exam_id=exam.pk)
    return render(request, 'online_exams/attempt_review.html', {'exam': exam, 'attempt': attempt, 'answers': answers, 'read_only': exam.results_released})
