# ai_engine/tasks.py
from celery import shared_task


@shared_task
def run_risk_assessment_task(run_id):
    """Runs the dropout-risk batch scan in the background - it touches
    attendance, grades and invoices for every active student, so on a
    larger school this is worth keeping off the request/response cycle,
    same reasoning as the AI timetabler."""
    from ai_engine.models import RiskAssessmentRun
    from ai_engine.services.risk_batch import RiskBatchService

    try:
        run = RiskAssessmentRun.objects.get(id=run_id)
    except RiskAssessmentRun.DoesNotExist:
        return

    RiskBatchService.run(run)


@shared_task
def run_report_card_batch_task(batch_id):
    """Runs report-card generation for every active student in the
    background - one Groq call per non-finalized student, which adds up on
    a large school."""
    from ai_engine.models import ReportCardBatch
    from ai_engine.services.report_card_batch import ReportCardBatchService

    try:
        batch = ReportCardBatch.objects.get(id=batch_id)
    except ReportCardBatch.DoesNotExist:
        return

    ReportCardBatchService.run(batch)


@shared_task
def run_report_comment_batch_task(batch_id):
    """Generate teacher/headteacher comments without blocking the browser request."""
    from ai_engine.models import ReportCommentBatch
    from ai_engine.services.report_comment_service import ReportCommentService
    try:
        batch = ReportCommentBatch.objects.get(id=batch_id)
    except ReportCommentBatch.DoesNotExist:
        return
    ReportCommentService.run_batch(batch)

@shared_task
def run_report_card_release_task(release_batch_id):
    from ai_engine.models import ReportCardReleaseBatch
    from ai_engine.services.report_card_release import ReportCardReleaseService
    try:
        batch = ReportCardReleaseBatch.objects.get(id=release_batch_id)
    except ReportCardReleaseBatch.DoesNotExist:
        return
    ReportCardReleaseService.run(batch, user=batch.triggered_by)


@shared_task
def auto_release_due_report_cards():
    """Scheduled end-of-term release hook.

    Terms whose end date has passed are processed once. Incomplete results are
    left PARTIAL rather than silently issuing an official report with missing marks.
    """
    from django.utils import timezone
    from django.conf import settings
    from ai_engine.models import ReportCardReleaseBatch
    from school.models import AcademicTerm
    from ai_engine.services.report_card_release import ReportCardReleaseService

    today = timezone.localdate()
    for term in AcademicTerm.objects.filter(end_date__lte=today).select_related('academic_year__school'):
        batch = (ReportCardReleaseBatch.objects
                 .filter(academic_term=term)
                 .order_by('-created_at')
                 .first())
        if batch and batch.status in ['COMPLETE', 'RUNNING']:
            continue
        if not batch or batch.status == 'FAILED':
            batch = ReportCardReleaseBatch.objects.create(
                school=term.academic_year.school, academic_term=term, triggered_by=None,
                auto_finalize=True, email_parents=True, generate_print_pack=True,
            )
        if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
            ReportCardReleaseService.run(batch, user=None)
        else:
            run_report_card_release_task.delay(str(batch.id))


@shared_task
def retry_failed_report_card_deliveries():
    """Retry failed parent report-card emails using bounded exponential backoff."""
    from django.conf import settings
    from django.utils import timezone
    from ai_engine.models import ReportCardDelivery
    from ai_engine.services.email_monitoring import EmailMonitoringService

    max_retries = max(1, int(getattr(settings, 'REPORT_CARD_EMAIL_MAX_RETRIES', 3)))
    now = timezone.now()
    deliveries = (ReportCardDelivery.objects
                  .filter(status='FAILED', retry_count__lt=max_retries, next_retry_at__isnull=False, next_retry_at__lte=now)
                  .select_related('report_card__student__user', 'report_card__student__parent', 'release_batch__school'))[:100]
    processed = 0
    for delivery in deliveries:
        result = EmailMonitoringService.send_report_card_delivery(delivery)
        processed += 1
        try:
            EmailMonitoringService.refresh_batch_counts(delivery.release_batch)
        except Exception:
            pass
    return processed
