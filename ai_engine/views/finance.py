from django.utils import timezone
import json
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from ai_engine.services.services import AIService
from ai_engine.models import RiskAssessmentRun, StudentRiskAssessment
from ai_engine.services.risk_batch import RiskBatchService
from ai_engine.tasks import run_risk_assessment_task
from school.models import AcademicTerm

from ai_engine.models import ReportCardBatch, ReportCard
from ai_engine.services.report_card_batch import ReportCardBatchService
from ai_engine.tasks import run_report_card_batch_task
from ai_engine.services.ai_router import AIRouter
from ai_engine.models import PaymentReminder
from ai_engine.services.finance_engine import FinanceInsightService
from finance.models import Invoice
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

# Updated to include BURSAR role
FINANCE_ROLES = ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'BURSAR']


@login_required
def finance_insights_dashboard(request):
    """
    Cash-flow snapshot + non-payment risk table, computed live on every
    load (cheap arithmetic over the school's own invoices - no batch/run
    needed, unlike the timetabler or dropout-risk engine).
    """
    school = request.user.school
    if request.user.role not in FINANCE_ROLES:
        messages.error(request, "You don't have permission to view finance insights.")
        return redirect('dashboard:dashboard')

    snapshot = FinanceInsightService.compute_school_snapshot(school)

    assessments = snapshot['assessments']
    band_filter = request.GET.get('band')
    if band_filter:
        assessments = [a for a in assessments if a['risk_band'] == band_filter]

    context = {
        'snapshot': snapshot,
        'assessments': assessments,
        'selected_band': band_filter or '',
    }
    return render(request, 'ai_engine/finance_insights_dashboard.html', context)


@login_required
def invoice_risk_detail(request, invoice_id):
    school = request.user.school
    if request.user.role not in FINANCE_ROLES:
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard:dashboard')

    invoice = get_object_or_404(
        Invoice.objects.select_related('student__user', 'academic_term').prefetch_related(
            'line_items__fee_category'
        ),
        id=invoice_id, school=school
    )
    assessment = FinanceInsightService.assess_invoice(invoice)
    reminders = PaymentReminder.objects.filter(invoice=invoice).select_related('generated_by', 'sent_by')

    context = {'invoice': invoice, 'assessment': assessment, 'reminders': reminders}
    return render(request, 'ai_engine/invoice_risk_detail.html', context)


@login_required
@require_POST
def generate_reminder(request, invoice_id):
    school = request.user.school
    if request.user.role not in FINANCE_ROLES:
        messages.error(request, "You don't have permission to draft a reminder.")
        return redirect('ai_engine:invoice_risk_detail', invoice_id=invoice_id)

    invoice = get_object_or_404(
        Invoice.objects.select_related('student__user').prefetch_related('line_items__fee_category'),
        id=invoice_id, school=school
    )
    today = timezone.localdate()
    overdue_days = max((today - invoice.due_date).days, 0)

    line_item_categories = [li.fee_category.name for li in invoice.line_items.all()]
    fee_category_name = ', '.join(dict.fromkeys(line_item_categories)) or 'Fees'

    message = AIService.generate_payment_reminder(
        student_name=invoice.student.user.get_full_name(),
        fee_category_name=fee_category_name,
        total_amount=invoice.total_amount,
        balance_due=invoice.balance_due,
        overdue_days=overdue_days,
        due_date=invoice.due_date,
    )
    PaymentReminder.objects.create(
        school=school, invoice=invoice, student=invoice.student, message=message, generated_by=request.user,
    )
    messages.success(request, "Reminder draft generated. Review and edit before sending.")
    return redirect('ai_engine:invoice_risk_detail', invoice_id=invoice.id)


@login_required
@require_POST
def save_reminder(request, reminder_id):
    school = request.user.school
    reminder = get_object_or_404(PaymentReminder, id=reminder_id, school=school)
    if reminder.is_sent:
        messages.error(request, "This reminder was already marked as sent and can't be edited.")
        return redirect('ai_engine:invoice_risk_detail', invoice_id=reminder.invoice_id)

    reminder.message = request.POST.get('message', '').strip()
    reminder.edited_by = request.user
    reminder.edited_at = timezone.now()
    reminder.save(update_fields=['message', 'edited_by', 'edited_at'])
    messages.success(request, "Reminder updated.")
    return redirect('ai_engine:invoice_risk_detail', invoice_id=reminder.invoice_id)


@login_required
@require_POST
def mark_reminder_sent(request, reminder_id):
    school = request.user.school
    reminder = get_object_or_404(PaymentReminder, id=reminder_id, school=school)
    reminder.is_sent = True
    reminder.sent_by = request.user
    reminder.sent_at = timezone.now()
    reminder.save(update_fields=['is_sent', 'sent_by', 'sent_at'])
    messages.success(request, "Marked as sent.")
    return redirect('ai_engine:invoice_risk_detail', invoice_id=reminder.invoice_id)