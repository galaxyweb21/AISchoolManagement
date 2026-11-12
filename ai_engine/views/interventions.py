from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils.dateparse import parse_date

from ai_engine.models import AcademicInterventionPlan, InterventionProgressEntry
from ai_engine.services.permissions import get_ai_permissions
from ai_engine.services.copilot_context import allowed_students
from school.models import AcademicTerm
from assessments.models import TerminalResult
from ai_engine.services.intervention_outcomes import compare_terminal_scores


def _access(request):
    permissions = get_ai_permissions(request.user)
    school = getattr(request.user, 'school', None)
    if not school or not permissions.can_view_risk:
        return None, None
    students = allowed_students(request.user, school)
    return school, students


def _can_manage(user):
    return getattr(user, 'role', '') in {'SUPER_ADMIN', 'SCHOOL_ADMIN', 'HEADMASTER', 'PRINCIPAL', 'TEACHER', 'HOD'}


def _current_followup_term(school):
    """Return the explicitly active term, falling back to the latest school term."""
    active_term = AcademicTerm.objects.filter(
        academic_year__school=school, academic_year__is_active=True, is_active=True
    ).select_related('academic_year').order_by('-start_date').first()
    if active_term:
        return active_term
    return AcademicTerm.objects.filter(
        academic_year__school=school
    ).select_related('academic_year').order_by('-start_date').first()


@login_required
def intervention_plans(request):
    school, students = _access(request)
    if not school:
        messages.error(request, 'You do not have permission to manage academic interventions.')
        return redirect('dashboard:dashboard')

    all_visible_plans = AcademicInterventionPlan.objects.filter(school=school, student__in=students)
    active_count = all_visible_plans.filter(status='ACTIVE').count()
    completed_count = all_visible_plans.filter(status='COMPLETED').count()
    overdue_count = all_visible_plans.filter(status='ACTIVE', review_date__lt=date.today()).count()
    plans = all_visible_plans.select_related(
        'student__user', 'student__school_class', 'assigned_to', 'academic_term'
    ).prefetch_related('progress_entries')
    status = request.GET.get('status', '').strip().upper()
    search = request.GET.get('q', '').strip()
    if status in dict(AcademicInterventionPlan.STATUS_CHOICES):
        plans = plans.filter(status=status)
    if search:
        plans = plans.filter(Q(student__user__first_name__icontains=search) |
                             Q(student__user__last_name__icontains=search) |
                             Q(student__admission_number__icontains=search) |
                             Q(title__icontains=search))

    paginator = Paginator(plans, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    active_term = _current_followup_term(school)
    baseline_terms = AcademicTerm.objects.none()
    if active_term:
        baseline_terms = AcademicTerm.objects.filter(
            academic_year__school=school,
            end_date__lt=active_term.start_date,
        ).exclude(pk=active_term.pk).select_related('academic_year').order_by('-start_date')
    context = {
        'plans': page_obj, 'page_obj': page_obj, 'selected_status': status, 'search': search,
        'active_term': active_term, 'students': students.order_by('user__first_name', 'user__last_name'),
        'can_create': _can_manage(request.user),
        'open_create_modal': request.GET.get('create') == '1' and _can_manage(request.user),
        'active_count': active_count,
        'completed_count': completed_count,
        'overdue_count': overdue_count,
        'status_choices': AcademicInterventionPlan.STATUS_CHOICES,
        'priority_choices': AcademicInterventionPlan.PRIORITY_CHOICES,
        'terms': baseline_terms,
        'has_baseline_terms': baseline_terms.exists(),
        'followup_term': active_term,
    }
    return render(request, 'ai_engine/intervention_plans.html', context)


@login_required
@require_POST
def create_intervention_plan(request):
    school, students = _access(request)
    if not school or not _can_manage(request.user):
        messages.error(request, 'You are not authorized to create intervention plans.')
        return redirect('ai_engine:intervention_plans')

    try:
        student = students.filter(pk=request.POST.get('student')).first()
    except (TypeError, ValueError, ValidationError):
        student = None
    title = request.POST.get('title', '').strip()
    concern = request.POST.get('concern', '').strip()
    goal = request.POST.get('goal', '').strip()
    strategies = request.POST.get('strategies', '').strip()
    if not student or not all([title, concern, goal, strategies]):
        messages.error(request, 'Select an authorized student and complete the required plan fields.')
        return redirect('ai_engine:intervention_plans')

    term_id = request.POST.get('academic_term', '').strip()
    if term_id:
        try:
            term = AcademicTerm.objects.filter(pk=term_id, academic_year__school=school).first()
        except (TypeError, ValueError, ValidationError):
            term = None
        if not term:
            messages.error(request, 'The selected academic term is not valid for this school.')
            return redirect('ai_engine:intervention_plans')
    else:
        term = _current_followup_term(school)

    baseline_term_id = request.POST.get('baseline_term', '').strip()
    subject = request.POST.get('subject', '').strip()[:150]
    baseline_term = None
    if baseline_term_id:
        try:
            baseline_term = AcademicTerm.objects.filter(
                pk=baseline_term_id, academic_year__school=school
            ).first()
        except (TypeError, ValueError, ValidationError):
            baseline_term = None
        if not baseline_term:
            messages.error(request, 'The selected baseline term is not valid for this school.')
            return redirect('ai_engine:intervention_plans')
    if bool(subject) != bool(baseline_term):
        messages.error(request, 'To compare academic results, select both a subject and a baseline term. You can leave both blank for a general support plan.')
        return redirect('ai_engine:intervention_plans')
    if baseline_term and (not term or baseline_term.end_date >= term.start_date):
        messages.error(request, 'The baseline term must end before the intervention follow-up term begins.')
        return redirect('ai_engine:intervention_plans')

    priority = request.POST.get('priority', 'MEDIUM').upper()
    if priority not in dict(AcademicInterventionPlan.PRIORITY_CHOICES):
        priority = 'MEDIUM'
    review_date_raw = request.POST.get('review_date', '').strip()
    review_date = parse_date(review_date_raw) if review_date_raw else None
    if review_date_raw and not review_date:
        messages.error(request, 'The review date is invalid. Please use the date picker and try again.')
        return redirect('ai_engine:intervention_plans')
    try:
        AcademicInterventionPlan.objects.create(
            school=school, student=student, academic_term=term, baseline_term=baseline_term,
            subject=subject, title=title[:180], concern=concern,
            baseline=request.POST.get('baseline', '').strip()[:240], goal=goal, strategies=strategies,
            priority=priority, review_date=review_date, assigned_to=request.user, created_by=request.user,
        )
    except (TypeError, ValueError):
        messages.error(request, 'The review date is invalid. Please use the date picker and try again.')
        return redirect('ai_engine:intervention_plans')
    messages.success(request, 'Academic intervention plan created successfully.')
    return redirect('ai_engine:intervention_plans')


@login_required
def intervention_plan_detail(request, plan_id):
    school, students = _access(request)
    if not school:
        messages.error(request, 'You do not have permission to view this intervention.')
        return redirect('dashboard:dashboard')
    plan = get_object_or_404(
        AcademicInterventionPlan.objects.select_related('student__user', 'assigned_to', 'academic_term', 'baseline_term').prefetch_related('progress_entries__recorded_by'),
        pk=plan_id, school=school, student__in=students,
    )
    score_comparison = None
    if plan.subject and plan.baseline_term_id and plan.academic_term_id:
        baseline_result = TerminalResult.objects.filter(
            school=school, student=plan.student, academic_term=plan.baseline_term,
            subject__iexact=plan.subject, status='COMPLETE', final_score__isnull=False,
        ).order_by('-updated_at').first()
        followup_result = TerminalResult.objects.filter(
            school=school, student=plan.student, academic_term=plan.academic_term,
            subject__iexact=plan.subject, status='COMPLETE', final_score__isnull=False,
        ).order_by('-updated_at').first()
        score_comparison = {
            'subject': plan.subject,
            'baseline_term': plan.baseline_term,
            'followup_term': plan.academic_term,
            'baseline_score': baseline_result.final_score if baseline_result else None,
            'followup_score': followup_result.final_score if followup_result else None,
            'baseline_grade': baseline_result.grade if baseline_result else '',
            'followup_grade': followup_result.grade if followup_result else '',
        }
        score_comparison.update(compare_terminal_scores(
            baseline_result.final_score if baseline_result else None,
            followup_result.final_score if followup_result else None,
        ))

    return render(request, 'ai_engine/intervention_plan_detail.html', {
        'plan': plan, 'can_manage': _can_manage(request.user),
        'status_choices': AcademicInterventionPlan.STATUS_CHOICES,
        'score_comparison': score_comparison,
    })


@login_required
@require_POST
def add_intervention_progress(request, plan_id):
    school, students = _access(request)
    if not school or not _can_manage(request.user):
        messages.error(request, 'You are not authorized to update this intervention.')
        return redirect('ai_engine:intervention_plans')
    plan = get_object_or_404(AcademicInterventionPlan, pk=plan_id, school=school, student__in=students)
    activity = request.POST.get('activity', '').strip()
    observation = request.POST.get('observation', '').strip()
    if not activity or not observation:
        messages.error(request, 'Enter the support activity and the progress observed.')
        return redirect('ai_engine:intervention_plan_detail', plan_id=plan.id)
    session_date_raw = request.POST.get('session_date', '').strip() or date.today().isoformat()
    session_date = parse_date(session_date_raw)
    if not session_date:
        messages.error(request, 'The session date is invalid.')
        return redirect('ai_engine:intervention_plan_detail', plan_id=plan.id)
    try:
        InterventionProgressEntry.objects.create(
            plan=plan, activity=activity[:180], observation=observation,
            next_step=request.POST.get('next_step', '').strip(), session_date=session_date, recorded_by=request.user,
        )
    except (TypeError, ValueError):
        messages.error(request, 'The session date is invalid.')
        return redirect('ai_engine:intervention_plan_detail', plan_id=plan.id)
    messages.success(request, 'Progress update recorded.')
    return redirect('ai_engine:intervention_plan_detail', plan_id=plan.id)


@login_required
@require_POST
def update_intervention_status(request, plan_id):
    school, students = _access(request)
    if not school or not _can_manage(request.user):
        messages.error(request, 'You are not authorized to update this intervention.')
        return redirect('ai_engine:intervention_plans')
    plan = get_object_or_404(AcademicInterventionPlan, pk=plan_id, school=school, student__in=students)
    status = request.POST.get('status', '').upper()
    if status not in dict(AcademicInterventionPlan.STATUS_CHOICES):
        messages.error(request, 'Choose a valid intervention status.')
        return redirect('ai_engine:intervention_plan_detail', plan_id=plan.id)
    plan.status = status
    plan.outcome = request.POST.get('outcome', '').strip() if status == 'COMPLETED' else plan.outcome
    plan.save(update_fields=['status', 'outcome', 'updated_at'])
    messages.success(request, 'Intervention status updated.')
    return redirect('ai_engine:intervention_plan_detail', plan_id=plan.id)
