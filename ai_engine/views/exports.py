# ai_engine/views/exports.py
"""
Export views for AI-generated content
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.contrib import messages
from accounts.access import role_allows

from ai_engine.models import GeneratedExam, ReportCard, StudentRiskAssessment
from ai_engine.services.export_service import ExportService
from ai_engine.services.finance_engine import FinanceInsightService


@login_required
@require_GET
def export_exam(request, exam_id, format='pdf'):
    """Export an exam to PDF or DOC format"""
    school = request.user.school
    if not role_allows(request.user, 'exams', 'export'):
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    exam = get_object_or_404(GeneratedExam, id=exam_id, school=school)
    questions = exam.questions.all().order_by('order')

    if format == 'pdf':
        return ExportService.export_exam_to_pdf(exam, questions)
    elif format == 'doc':
        return ExportService.export_exam_to_doc(exam, questions)
    else:
        return JsonResponse({'error': 'Unsupported format'}, status=400)


@login_required
@require_GET
def export_report_card(request, report_card_id, format='pdf'):
    """Export a report card to PDF or DOC format"""
    school = request.user.school
    if not role_allows(request.user, 'reports', 'export'):
        return JsonResponse({'error': 'Permission denied.'}, status=403)
    report_card = get_object_or_404(ReportCard, id=report_card_id, school=school)

    if format == 'pdf':
        return ExportService.export_report_card_to_pdf(report_card)
    elif format == 'doc':
        return ExportService.export_report_card_to_doc(report_card)
    else:
        return JsonResponse({'error': 'Unsupported format'}, status=400)


@login_required
@require_GET
def export_risk_assessment(request, assessment_id, format='pdf'):
    """Export a risk assessment to PDF or DOC format"""
    school = request.user.school
    assessment = get_object_or_404(StudentRiskAssessment, id=assessment_id, school=school)

    if format == 'pdf':
        return ExportService.export_risk_assessment_to_pdf(assessment)
    elif format == 'doc':
        return ExportService.export_risk_assessment_to_doc(assessment)
    else:
        return JsonResponse({'error': 'Unsupported format'}, status=400)


@login_required
@require_GET
def export_finance_insights(request, format='pdf'):
    """Export finance insights to PDF"""
    school = request.user.school
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to export finance insights.")
        return redirect('dashboard:dashboard')

    snapshot = FinanceInsightService.compute_school_snapshot(school)
    snapshot['school_name'] = school.name

    if format == 'pdf':
        return ExportService.export_finance_insight_to_pdf(snapshot, snapshot['assessments'])
    else:
        return JsonResponse({'error': 'Unsupported format'}, status=400)