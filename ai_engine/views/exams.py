# ai_engine/views/exams.py
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
import json
from accounts.access import role_allows

from ai_engine.models import GeneratedExam, GeneratedQuestion
from ai_engine.services.exam_engine import ExamGeneratorService, ExamGenerationError
from assessments.models import Assessment, AssessmentQuestion
from academics.models import SchoolClass, Subject
# FIXED: Import GradeLevel from students.models
from students.models import GradeLevel
from school.models import AcademicTerm

EXAM_ROLES = ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER']


@login_required
def exam_dashboard(request):
    if request.user.role not in EXAM_ROLES:
        messages.error(request, "You don't have permission to view exam generation.")
        return redirect('dashboard')

    school = request.user.school
    exams = GeneratedExam.objects.filter(school=school).select_related(
        'created_by', 'school_class', 'school_class__grade_level'
    ).prefetch_related('questions').order_by('-created_at')

    context = {'exams': exams}
    return render(request, 'ai_engine/exam_dashboard.html', context)


@login_required
def create_exam(request):
    if request.user.role not in EXAM_ROLES:
        messages.error(request, "You don't have permission to generate exams.")
        return redirect('dashboard')

    school = request.user.school

    if request.method != 'POST':
        # Get school classes and subjects for the dropdowns
        school_classes = SchoolClass.objects.filter(school=school).select_related(
            'grade_level'
        ).order_by('grade_level__order', 'name')
        subjects = Subject.objects.filter(school=school).order_by('name')

        return render(request, 'ai_engine/exam_create.html', {
            'question_types': GeneratedQuestion.TYPE_CHOICES,
            'school_classes': school_classes,
            'subjects': subjects,
            'stage_choices': GradeLevel.STAGE_CHOICES,  # FIXED: GradeLevel is now imported
        })

    # Handle POST request
    title = request.POST.get('title', '').strip()
    subject_id = request.POST.get('subject', '').strip()
    topic = request.POST.get('topic', '').strip()
    school_class_id = request.POST.get('school_class', '').strip()
    grade_level = request.POST.get('grade_level_display', '').strip()
    difficulty = request.POST.get('difficulty', 'MEDIUM')

    try:
        num_questions = int(request.POST.get('num_questions', 10))
    except ValueError:
        num_questions = 10
    num_questions = max(1, min(num_questions, 30))
    question_types = request.POST.getlist('question_types') or ['MCQ']

    # Validate required fields
    if not all([title, subject_id, school_class_id]):
        messages.error(request, "Title, Subject, and School Class are required.")
        school_classes = SchoolClass.objects.filter(school=school).select_related('grade_level').order_by(
            'grade_level__order', 'name')
        subjects = Subject.objects.filter(school=school).order_by('name')
        return render(request, 'ai_engine/exam_create.html', {
            'question_types': GeneratedQuestion.TYPE_CHOICES,
            'school_classes': school_classes,
            'subjects': subjects,
            'form_data': request.POST,
            'stage_choices': GradeLevel.STAGE_CHOICES,
        })

    try:
        # Get the selected subject
        subject = get_object_or_404(Subject, id=subject_id, school=school)
        school_class = get_object_or_404(SchoolClass, id=school_class_id, school=school)
        if request.user.role == 'TEACHER':
            from academics.models import TeacherAssignment
            if not TeacherAssignment.objects.filter(school=school, teacher=request.user.teacher_profile, school_class=school_class, subject=subject, is_active=True).exists():
                raise ExamGenerationError('You can only create exams for classes and subjects assigned to you.')

        # Use the grade level name for display
        grade_level = grade_level or school_class.grade_level.name

        # GES stage (KG/PRIMARY/JHS/SHS) drives NaCCA-curriculum-aligned
        # prompting in ExamGeneratorService
        ges_stage = school_class.grade_level.stage

        # Generate questions using the subject name and grade level
        questions_data = ExamGeneratorService.generate(
            subject=subject.name,
            topic=topic,
            grade_level=grade_level,
            difficulty=difficulty,
            num_questions=num_questions,
            question_types=question_types,
            ges_stage=ges_stage,
        )
    except ExamGenerationError as exc:
        messages.error(request, str(exc))
        school_classes = SchoolClass.objects.filter(school=school).select_related('grade_level').order_by(
            'grade_level__order', 'name')
        subjects = Subject.objects.filter(school=school).order_by('name')
        return render(request, 'ai_engine/exam_create.html', {
            'question_types': GeneratedQuestion.TYPE_CHOICES,
            'school_classes': school_classes,
            'subjects': subjects,
            'form_data': request.POST,
            'stage_choices': GradeLevel.STAGE_CHOICES,
        })

    # Create the exam with subject reference
    exam = GeneratedExam.objects.create(
        school=school,
        created_by=request.user,
        title=title,
        subject=subject.name,
        subject_ref=subject,
        topic=topic,
        school_class=school_class,
        grade_level=grade_level,
        difficulty=difficulty,
        ges_stage=ges_stage,
    )

    # Create questions
    GeneratedQuestion.objects.bulk_create([
        GeneratedQuestion(
            exam=exam,
            order=i,
            question_type=q['type'],
            question_text=q['question'],
            options=q.get('options') or [],
            correct_answer=q['correct_answer'],
            points=q.get('points', 1),
        )
        for i, q in enumerate(questions_data)
    ])

    stage_display = dict(GradeLevel.STAGE_CHOICES).get(ges_stage, '')
    stage_label = f" ({stage_display})" if stage_display else ''

    messages.success(
        request,
        f"Generated {len(questions_data)} question(s) for {school_class.name} - {subject.name}{stage_label}. "
        "Review before using in class."
    )
    return redirect('ai_engine:exam_detail', exam_id=exam.id)


@login_required
def exam_detail(request, exam_id):
    school = request.user.school
    if request.user.role not in EXAM_ROLES:
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard')

    exam = get_object_or_404(
        GeneratedExam.objects.select_related('school_class', 'school_class__grade_level'),
        id=exam_id,
        school=school
    )
    questions = exam.questions.all().order_by('order')
    total_points = sum(q.points for q in questions)

    context = {
        'exam': exam,
        'questions': questions,
        'total_points': total_points,
        'can_manage': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
        'stage_display': dict(GradeLevel.STAGE_CHOICES).get(exam.ges_stage, ''),
    }
    return render(request, 'ai_engine/exam_detail.html', context)


@login_required
@require_POST
def save_exam_question(request, exam_id, question_id):
    school = request.user.school
    question = get_object_or_404(GeneratedQuestion, id=question_id, exam__id=exam_id, exam__school=school)

    question.question_text = request.POST.get('question_text', '').strip()
    question.correct_answer = request.POST.get('correct_answer', '').strip()
    try:
        question.points = max(1, int(request.POST.get('points', 1)))
    except ValueError:
        question.points = 1

    if question.question_type == 'MCQ':
        options = [o.strip() for o in request.POST.getlist('options') if o.strip()]
        question.options = options

    question.edited_by = request.user
    question.edited_at = timezone.now()
    question.save(update_fields=['question_text', 'correct_answer', 'points', 'options', 'edited_by', 'edited_at'])
    messages.success(request, "Question updated.")
    return redirect('ai_engine:exam_detail', exam_id=exam_id)


@login_required
@require_POST
def regenerate_exam_question(request, exam_id, question_id):
    school = request.user.school
    question = get_object_or_404(GeneratedQuestion, id=question_id, exam__id=exam_id, exam__school=school)
    exam = question.exam

    try:
        new_q = ExamGeneratorService.generate_replacement_question(exam, question)
    except ExamGenerationError as exc:
        messages.error(request, str(exc))
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    question.question_text = new_q['question']
    question.options = new_q.get('options') or []
    question.correct_answer = new_q['correct_answer']
    question.points = new_q.get('points', question.points)
    question.is_ai_generated = True
    question.edited_by = None
    question.edited_at = None
    question.save(update_fields=['question_text', 'options', 'correct_answer', 'points',
                                 'is_ai_generated', 'edited_by', 'edited_at'])
    messages.success(request, "Question regenerated.")
    return redirect('ai_engine:exam_detail', exam_id=exam_id)


@login_required
@require_POST
def delete_exam_question(request, exam_id, question_id):
    school = request.user.school
    question = get_object_or_404(GeneratedQuestion, id=question_id, exam__id=exam_id, exam__school=school)
    question.delete()
    messages.success(request, "Question removed.")
    return redirect('ai_engine:exam_detail', exam_id=exam_id)


@login_required
@require_POST
def add_exam_question(request, exam_id):
    school = request.user.school
    exam = get_object_or_404(GeneratedExam, id=exam_id, school=school)
    next_order = exam.questions.count()
    GeneratedQuestion.objects.create(
        exam=exam,
        order=next_order,
        question_type='SHORT_ANSWER',
        question_text='New question - edit me',
        correct_answer='',
        points=1,
        is_ai_generated=False,
        edited_by=request.user,
        edited_at=timezone.now(),
    )
    messages.success(request, "Blank question added - edit it below.")
    return redirect('ai_engine:exam_detail', exam_id=exam_id)


@login_required
@require_POST
def link_exam_to_assessment(request, exam_id):
    school = request.user.school
    if request.user.role not in EXAM_ROLES:
        messages.error(request, "You don't have permission to do this.")
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    exam = get_object_or_404(GeneratedExam, id=exam_id, school=school)
    if exam.linked_assessment_id:
        messages.info(request, "This exam is already linked to a gradebook assessment.")
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    total_points = sum(q.points for q in exam.questions.all()) or 100
    active_term = AcademicTerm.objects.filter(academic_year__school=school, academic_year__is_active=True, is_active=True).first()
    assessment = Assessment.objects.create(
        school=school,
        academic_term=active_term,
        school_class=exam.school_class,
        title=exam.title,
        subject=exam.subject,
        assessment_type='EXAM',
        score_component='EXAM',
        max_score=total_points,
    )
    AssessmentQuestion.objects.bulk_create([
        AssessmentQuestion(
            assessment=assessment, order=q.order, question_type=q.question_type,
            question_text=q.question_text, options=q.options or [],
            correct_answer=q.correct_answer or '', marks=q.points
        ) for q in exam.questions.all()
    ])
    exam.linked_assessment = assessment
    exam.save(update_fields=['linked_assessment'])
    messages.success(request, "Linked to a new gradebook assessment - you can now record grades for it.")
    return redirect('ai_engine:exam_detail', exam_id=exam_id)


# ============================================================
# DELETE ALL QUESTIONS FOR AN EXAM
# ============================================================

@login_required
@require_POST
def delete_all_exam_questions(request, exam_id):
    """Delete all questions for a specific exam."""
    school = request.user.school
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to delete exam questions.")
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    exam = get_object_or_404(GeneratedExam, id=exam_id, school=school)

    # Count questions before deletion
    question_count = exam.questions.count()

    if question_count == 0:
        messages.warning(request, "This exam has no questions to delete.")
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    # Delete all questions
    exam.questions.all().delete()

    messages.success(request, f"Successfully deleted all {question_count} question(s) from '{exam.title}'.")
    return redirect('ai_engine:exam_detail', exam_id=exam_id)


# ============================================================
# DELETE EXAM COMPLETELY
# ============================================================

@login_required
@require_POST
def delete_exam(request, exam_id):
    """Delete an exam and all its questions."""
    school = request.user.school
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to delete an exam.")
        return redirect('ai_engine:exam_dashboard')

    exam = get_object_or_404(GeneratedExam, id=exam_id, school=school)
    exam_title = exam.title

    # Check if exam is linked to an assessment
    if exam.linked_assessment:
        messages.warning(
            request,
            f"Cannot delete '{exam_title}' because it is linked to a gradebook assessment. "
            f"Unlink it first or delete the assessment separately."
        )
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    # Delete exam (cascades to questions)
    exam.delete()
    messages.success(request, f"Exam '{exam_title}' and all its questions have been deleted successfully.")
    return redirect('ai_engine:exam_dashboard')


@login_required
@require_POST
def unlink_exam_from_assessment(request, exam_id):
    """Unlink an exam from its gradebook assessment."""
    school = request.user.school
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to unlink this exam.")
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    exam = get_object_or_404(GeneratedExam, id=exam_id, school=school)

    if not exam.linked_assessment:
        messages.info(request, "This exam is not linked to any assessment.")
        return redirect('ai_engine:exam_detail', exam_id=exam_id)

    # Get the assessment before unlinking
    assessment = exam.linked_assessment
    assessment_title = assessment.title

    # Unlink the exam from the assessment
    exam.linked_assessment = None
    exam.save(update_fields=['linked_assessment'])

    messages.success(
        request,
        f"Successfully unlinked '{exam.title}' from gradebook assessment '{assessment_title}'."
    )
    return redirect('ai_engine:exam_detail', exam_id=exam_id)