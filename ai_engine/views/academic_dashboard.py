from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q
from django.shortcuts import redirect, render
from django.contrib import messages

from ai_engine.models import AcademicInterventionPlan
from ai_engine.services.copilot_context import allowed_students
from ai_engine.services.permissions import get_ai_permissions
from assessments.models import TerminalResult
from school.models import AcademicTerm


@login_required
def academic_performance_dashboard(request):
    """School-scoped academic overview using completed terminal results only."""
    school = getattr(request.user, 'school', None)
    permissions = get_ai_permissions(request.user)
    if not school or not permissions.can_view_risk:
        messages.error(request, 'You do not have permission to view academic performance intelligence.')
        return redirect('dashboard:dashboard')

    students = allowed_students(request.user, school)
    visible_student_ids = students.values_list('pk', flat=True)
    terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')
    selected_term_id = request.GET.get('term', '').strip()
    active_term = AcademicTerm.objects.filter(
        academic_year__school=school, academic_year__is_active=True, is_active=True
    ).first()
    selected_term = active_term
    if selected_term_id:
        try:
            selected_term = terms.filter(pk=selected_term_id).first()
        except (TypeError, ValueError, ValidationError):
            selected_term = active_term
    if not selected_term:
        selected_term = terms.first()

    empty = TerminalResult.objects.none()
    results = empty
    if selected_term:
        results = TerminalResult.objects.filter(
            school=school, academic_term=selected_term,
            student_id__in=visible_student_ids, status='COMPLETE', final_score__isnull=False,
        )

    overall = results.aggregate(
        average=Avg('final_score'),
        result_count=Count('pk'),
        student_count=Count('student_id', distinct=True),
        below_50=Count('pk', filter=Q(final_score__lt=50)),
    )
    subject_rows = list(results.values('subject').annotate(
        average=Avg('final_score'), result_count=Count('pk'),
        below_50=Count('pk', filter=Q(final_score__lt=50)),
        student_count=Count('student_id', distinct=True),
    ).order_by('average', 'subject'))
    class_rows = list(results.values('school_class__name').annotate(
        average=Avg('final_score'), result_count=Count('pk'),
        student_count=Count('student_id', distinct=True),
    ).order_by('-average', 'school_class__name'))

    previous_term = None
    if selected_term:
        previous_term = terms.filter(end_date__lt=selected_term.start_date).order_by('-end_date').first()
    previous_average = None
    average_change = None
    if previous_term:
        previous_average = TerminalResult.objects.filter(
            school=school, academic_term=previous_term, student_id__in=visible_student_ids,
            status='COMPLETE', final_score__isnull=False,
        ).aggregate(value=Avg('final_score'))['value']
        if previous_average is not None and overall['average'] is not None:
            average_change = overall['average'] - previous_average

    plans = AcademicInterventionPlan.objects.filter(school=school, student_id__in=visible_student_ids)
    intervention_summary = {
        'active': plans.filter(status='ACTIVE').count(),
        'overdue': plans.filter(status='ACTIVE', review_date__lt=date.today()).count(),
        'completed': plans.filter(status='COMPLETED').count(),
        'total': plans.count(),
    }
    context = {
        'selected_term': selected_term,
        'terms': terms,
        'previous_term': previous_term,
        'overall': overall,
        'subject_rows': subject_rows,
        'class_rows': class_rows,
        'previous_average': previous_average,
        'average_change': average_change,
        'intervention_summary': intervention_summary,
        'has_results': bool(overall['result_count']),
        'today': date.today(),
    }
    return render(request, 'ai_engine/academic_performance_dashboard.html', context)
