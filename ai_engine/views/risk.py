# ai_engine/views/risk.py
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
import json

from ai_engine.models import RiskAssessmentRun, StudentRiskAssessment
from ai_engine.services.risk_batch import RiskBatchService
from ai_engine.tasks import run_risk_assessment_task
from school.models import AcademicTerm


@login_required
def risk_dashboard(request):
    """
    Early-warning dashboard: shows the most recent risk-assessment run for
    the active term, students sorted highest-risk first, filterable by
    band. Only Admins/Teachers should be triaging this list.
    """
    school = request.user.school
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER']:
        messages.error(request, "You don't have permission to view the risk dashboard.")
        return redirect('dashboard:dashboard')

    active_term = AcademicTerm.objects.filter(
        academic_year__school=school, academic_year__is_active=True, is_active=True
    ).first()

    latest_run = None
    if active_term:
        latest_run = RiskAssessmentRun.objects.filter(school=school, academic_term=active_term).first()

    assessments = []
    if latest_run and latest_run.status == 'COMPLETE':
        assessments = StudentRiskAssessment.objects.filter(run=latest_run).select_related('student__user')
        band_filter = request.GET.get('band')
        if band_filter:
            assessments = assessments.filter(risk_band=band_filter)

    context = {
        'active_term': active_term,
        'latest_run': latest_run,
        'assessments': assessments,
        'selected_band': request.GET.get('band', ''),
        'can_trigger': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
    }
    return render(request, 'ai_engine/risk_dashboard.html', context)


@login_required
@require_POST
def trigger_risk_assessment(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to run a risk assessment.")
        return redirect('ai_engine:risk_dashboard')

    school = request.user.school
    active_term = AcademicTerm.objects.filter(
        academic_year__school=school, academic_year__is_active=True, is_active=True
    ).first()

    if not active_term:
        messages.error(request, "No active academic term is configured. Set one up in School Settings first.")
        return redirect('ai_engine:risk_dashboard')

    run = RiskBatchService.create_pending(school=school, academic_term=active_term, triggered_by=request.user)

    try:
        run_risk_assessment_task.delay(str(run.id))
        messages.info(request, "Risk assessment started. This page will update automatically.")
    except Exception:
        messages.warning(
            request,
            "Background worker unavailable - running inline instead. "
            "Start the Celery worker (see README) for a faster response on larger schools."
        )
        RiskBatchService.run(run)

    return redirect('ai_engine:risk_dashboard')


@login_required
def student_risk_detail(request, assessment_id):
    school = request.user.school
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER']:
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard')

    assessment = get_object_or_404(
        StudentRiskAssessment.objects.select_related('student__user', 'run'), id=assessment_id, school=school
    )
    history = StudentRiskAssessment.objects.filter(
        school=school, student=assessment.student
    ).exclude(id=assessment.id).select_related('run').order_by('-run__computed_at')[:6]

    context = {'assessment': assessment, 'history': history}
    return render(request, 'ai_engine/student_risk_detail.html', context)