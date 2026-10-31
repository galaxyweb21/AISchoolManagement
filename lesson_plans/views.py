from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponseForbidden, HttpResponse, JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from academics.models import TeacherAssignment
from school.models import AcademicTerm
from staff.models import Teacher
from .forms import WeeklyLessonPlanForm
from .models import WeeklyLessonPlan

ADMIN_ROLES = {'SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD'}


def _school_for(request):
    return getattr(request.user, 'school', None)


def _is_reviewer(user):
    return getattr(user, 'role', '') in ADMIN_ROLES


def _teacher_for(request):
    school = _school_for(request)
    if not school:
        return None
    return Teacher.objects.filter(user=request.user, school=school, is_active=True).first()


def _teacher_has_assignment(teacher, school_class, subject, school):
    return TeacherAssignment.objects.filter(
        school=school, teacher=teacher, school_class=school_class,
        subject=subject, is_active=True,
    ).exists()


@login_required
def lesson_plan_list(request):
    school = _school_for(request)
    if not school:
        messages.error(request, 'Your account is not assigned to a school.')
        return redirect('dashboard:dashboard')
    if _is_reviewer(request.user):
        plans = WeeklyLessonPlan.objects.filter(school=school).select_related(
            'teacher__user', 'academic_term__academic_year', 'school_class', 'subject', 'reviewer'
        )
        status = request.GET.get('status', '').strip()
        if status in dict(WeeklyLessonPlan.STATUS_CHOICES):
            plans = plans.filter(status=status)
        teacher = None
    else:
        teacher = _teacher_for(request)
        if not teacher:
            messages.error(request, 'Your account does not have an active teacher profile. Please contact the school administrator.')
            return redirect('dashboard:dashboard')
        plans = WeeklyLessonPlan.objects.filter(school=school, teacher=teacher).select_related(
            'academic_term__academic_year', 'school_class', 'subject', 'reviewer'
        )
    context = {
        'plans': plans,
        'pending_count': plans.filter(status=WeeklyLessonPlan.STATUS_SUBMITTED).count(),
        'approved_count': plans.filter(status=WeeklyLessonPlan.STATUS_APPROVED).count(),
        'is_reviewer': _is_reviewer(request.user),
        'status_choices': WeeklyLessonPlan.STATUS_CHOICES,
        'selected_status': request.GET.get('status', ''),
        'teacher': teacher,
        'active_tab': 'lesson_plans',
    }
    return render(request, 'lesson_plans/lesson_plan_list.html', context)


@login_required
def lesson_plan_create(request):
    school = _school_for(request)
    teacher = _teacher_for(request)
    if not school or not teacher:
        messages.error(request, 'Only an active teacher assigned to this school can create lesson notes.')
        return redirect('lesson_plans:lesson_plan_list')
    if request.method == 'POST':
        form = WeeklyLessonPlanForm(request.POST, request.FILES, school=school, teacher=teacher)
        action = request.POST.get('action', 'draft')
        if form.is_valid():
            cleaned = form.cleaned_data
            if cleaned['week_start'].weekday() != 0:
                form.add_error('week_start', 'Choose the Monday date for the teaching week.')
            elif cleaned['academic_term'].academic_year.school_id != school.id:
                form.add_error('academic_term', 'Choose a term belonging to your school.')
            elif cleaned['school_class'].school_id != school.id or cleaned['subject'].school_id != school.id:
                form.add_error(None, 'Choose a class and subject belonging to your school.')
            elif not _teacher_has_assignment(teacher, cleaned['school_class'], cleaned['subject'], school):
                form.add_error('subject', 'You can only submit notes for a class and subject assigned to you.')
            if form.is_valid():
                plan = form.save(commit=False)
                plan.school = school
                plan.teacher = teacher
                if action == 'submit':
                    plan.mark_submitted()
                try:
                    plan.save()
                    messages.success(request, 'Lesson note submitted for review.' if action == 'submit' else 'Lesson note saved as a draft.')
                    return redirect('lesson_plans:lesson_plan_list')
                except IntegrityError:
                    form.add_error(None, 'A lesson note already exists for this teacher, term, week, class and subject. Open the existing note to update it.')
        else:
            pass
    else:
        form = WeeklyLessonPlanForm(school=school, teacher=teacher, initial={'week_start': timezone.localdate() - timedelta(days=timezone.localdate().weekday())})
    return render(request, 'lesson_plans/lesson_plan_form.html', {'form': form, 'is_edit': False, 'read_only': False})


@login_required
def lesson_plan_edit(request, plan_id):
    school = _school_for(request)
    plan = get_object_or_404(WeeklyLessonPlan.objects.select_related('teacher__user'), id=plan_id, school=school)
    reviewer = _is_reviewer(request.user)
    teacher = _teacher_for(request)
    if not reviewer and (not teacher or plan.teacher_id != teacher.id):
        return HttpResponseForbidden('You can only edit your own lesson notes.')
    read_only = reviewer or plan.status in (WeeklyLessonPlan.STATUS_SUBMITTED, WeeklyLessonPlan.STATUS_APPROVED)
    if request.method == 'POST' and not read_only:
        form = WeeklyLessonPlanForm(request.POST, request.FILES, instance=plan, school=school, teacher=teacher)
        action = request.POST.get('action', 'draft')
        if form.is_valid():
            cleaned = form.cleaned_data
            if cleaned['week_start'].weekday() != 0:
                form.add_error('week_start', 'Choose the Monday date for the teaching week.')
            elif not _teacher_has_assignment(teacher, cleaned['school_class'], cleaned['subject'], school):
                form.add_error('subject', 'You can only submit notes for a class and subject assigned to you.')
            if form.is_valid():
                obj = form.save(commit=False)
                obj.school = school
                obj.teacher = teacher
                if action == 'submit':
                    obj.mark_submitted()
                try:
                    obj.save()
                    messages.success(request, 'Lesson note submitted for review.' if action == 'submit' else 'Draft updated.')
                    return redirect('lesson_plans:lesson_plan_list')
                except IntegrityError:
                    form.add_error(None, 'Another lesson note already exists for this week, class and subject.')
    else:
        form = WeeklyLessonPlanForm(instance=plan, school=school, teacher=plan.teacher)
    return render(request, 'lesson_plans/lesson_plan_form.html', {
        'form': form, 'is_edit': True, 'plan': plan, 'read_only': read_only,
        'is_reviewer': reviewer,
    })


@login_required
def lesson_plan_export_pdf(request, plan_id):
    """Export a lesson note to a printable PDF, respecting school and owner permissions."""
    school = _school_for(request)
    plan = get_object_or_404(
        WeeklyLessonPlan.objects.select_related('teacher__user', 'academic_term__academic_year', 'school_class', 'subject'),
        id=plan_id, school=school,
    )
    teacher = _teacher_for(request)
    if not _is_reviewer(request.user) and (not teacher or plan.teacher_id != teacher.id):
        return HttpResponseForbidden('You can only export your own lesson notes.')
    # If the teacher uploaded an actual PDF, export that original PDF rather than a summary.
    if plan.submission_method == WeeklyLessonPlan.METHOD_UPLOAD and plan.supporting_document:
        source_name = plan.supporting_document.name.rsplit('/', 1)[-1]
        if source_name.lower().endswith('.pdf'):
            response = FileResponse(plan.supporting_document.open('rb'), content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="{}"'.format(source_name.replace('"', ''))
            response['X-Content-Type-Options'] = 'nosniff'
            return response
    try:
        from xhtml2pdf import pisa
        from io import BytesIO
        html = render_to_string('lesson_plans/lesson_plan_pdf.html', {'plan': plan, 'school': school, 'request': request})
        output = BytesIO()
        result = pisa.CreatePDF(src=html, dest=output, encoding='utf-8')
        if result.err:
            return HttpResponse('The PDF could not be generated. Please use Print and choose Save as PDF.', status=500, content_type='text/plain')
        filename = 'lesson-note-{}.pdf'.format(str(plan.topic).lower().replace(' ', '-')[:60] or 'lesson')
        response = HttpResponse(output.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename.replace('"', ''))
        return response
    except ImportError:
        return HttpResponse('PDF export requires xhtml2pdf. Install the dependencies listed in requirements.txt, or use Print and choose Save as PDF.', status=503, content_type='text/plain')


@login_required
def lesson_plan_document(request, plan_id):
    """Serve lesson attachments only to the owning teacher or school reviewers."""
    school = _school_for(request)
    plan = get_object_or_404(WeeklyLessonPlan, id=plan_id, school=school)
    reviewer = _is_reviewer(request.user)
    teacher = _teacher_for(request)
    if not reviewer and (not teacher or plan.teacher_id != teacher.id):
        return HttpResponseForbidden('You do not have permission to view this lesson note document.')
    if not plan.supporting_document:
        return HttpResponse('No supporting document is attached.', status=404)
    import mimetypes
    filename = plan.supporting_document.name.rsplit('/', 1)[-1]
    content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    response = FileResponse(plan.supporting_document.open('rb'), content_type=content_type)
    response['Content-Disposition'] = 'inline; filename="{}"'.format(filename.replace('"', ''))
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_POST
def lesson_plan_generate_ai(request):
    """Generate editable lesson-note content from the teacher's selected context."""
    import json
    from django.utils.html import strip_tags
    school = _school_for(request)
    teacher = _teacher_for(request)
    if not school or not teacher:
        return JsonResponse({'success': False, 'error': 'An active teacher profile is required.'}, status=403)

    data = request.POST
    term_id = data.get('academic_term')
    class_id = data.get('school_class')
    subject_id = data.get('subject')
    topic = strip_tags((data.get('topic') or '').strip())[:200]
    subtopic = strip_tags((data.get('subtopic') or '').strip())[:200]
    if not all([term_id, class_id, subject_id, topic]):
        return JsonResponse({'success': False, 'error': 'Select academic year/term, class, subject and enter a topic first.'}, status=400)

    term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)
    from academics.models import SchoolClass, Subject
    school_class = get_object_or_404(SchoolClass, id=class_id, school=school, is_active=True)
    subject = get_object_or_404(Subject, id=subject_id, school=school, is_active=True)
    if not _teacher_has_assignment(teacher, school_class, subject, school):
        return JsonResponse({'success': False, 'error': 'You can only generate notes for a class and subject assigned to you.'}, status=403)

    academic_year = getattr(term.academic_year, 'name', str(term.academic_year))
    prompt = (
        'Create a practical, age-appropriate weekly lesson note for a Ghanaian school. '
        'Return ONLY a valid JSON object with string keys: learning_objectives, teaching_resources, '
        'introduction, lesson_development, conclusion, assessment, reflection. Make objectives measurable, '
        'sequence teacher and learner activities, include inclusive learning and formative assessment. '
        'Do not invent exact curriculum standards. Reflection should be a prompt for after the lesson, not a claim.\n\n'
        f'School class/grade: {school_class.name}\nAcademic year: {academic_year}\n'
        f'Academic term: {term.name}\nSubject: {subject.name}\nTopic: {topic}\n'
        f'Subtopic: {subtopic or "Not specified"}\nUse clear teacher-ready language. No markdown fences.'
    )
    try:
        from ai_engine.services.services import AIService
        from django.conf import settings
        generated = AIService._call_groq(
            'You are an experienced Ghanaian basic-school teacher and lesson-planning specialist. Return valid JSON only.',
            prompt, max_tokens=1800, temperature=0.35,
            model=getattr(settings, 'GROQ_MODEL', 'openai/gpt-oss-20b'),
        )
        if not generated:
            return JsonResponse({'success': False, 'error': 'AI lesson generation is unavailable. Check the Groq API configuration or try again later.'}, status=503)
        cleaned = generated.strip()
        if cleaned.startswith('```'):
            cleaned = cleaned.split('\n', 1)[-1]
            if cleaned.endswith('```'):
                cleaned = cleaned[:-3]
        content = json.loads(cleaned)
        fields = ('learning_objectives', 'teaching_resources', 'introduction', 'lesson_development', 'conclusion', 'assessment', 'reflection')
        result = {key: str(content.get(key, '') or '').strip() for key in fields}
        if not result['learning_objectives'] or not result['lesson_development'] or not result['assessment']:
            raise ValueError('The generated note was incomplete.')
        return JsonResponse({'success': True, 'content': result, 'message': 'Draft generated. Review and edit every section before saving.'})
    except Exception:
        return JsonResponse({'success': False, 'error': 'The AI could not return a usable lesson note. Please retry or complete the note manually.'}, status=502)


@login_required
@require_POST
def lesson_plan_review(request, plan_id):
    school = _school_for(request)
    if not school or not _is_reviewer(request.user):
        return HttpResponseForbidden('You do not have permission to review lesson notes.')
    plan = get_object_or_404(WeeklyLessonPlan, id=plan_id, school=school)
    if plan.status != WeeklyLessonPlan.STATUS_SUBMITTED:
        messages.error(request, 'Only submitted lesson notes can be reviewed.')
        return redirect('lesson_plans:lesson_plan_list')
    action = request.POST.get('decision')
    comment = request.POST.get('reviewer_comment', '').strip()
    if action not in ('approve', 'revision'):
        messages.error(request, 'Choose approve or request revision.')
        return redirect('lesson_plans:lesson_plan_list')
    if action == 'revision' and not comment:
        messages.error(request, 'Please add a comment explaining the requested revision.')
        return redirect('lesson_plans:lesson_plan_list')
    plan.reviewer = request.user
    plan.reviewer_comment = comment
    plan.reviewed_at = timezone.now()
    plan.status = WeeklyLessonPlan.STATUS_APPROVED if action == 'approve' else WeeklyLessonPlan.STATUS_REVISION
    plan.save(update_fields=['reviewer', 'reviewer_comment', 'reviewed_at', 'status', 'updated_at'])
    messages.success(request, 'Lesson note approved.' if action == 'approve' else 'Revision requested. The teacher can update and resubmit the note.')
    return redirect('lesson_plans:lesson_plan_list')
