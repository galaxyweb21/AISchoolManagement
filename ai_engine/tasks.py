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
