# ai_engine/views/automation.py
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone

from ai_engine.models import AIAutomationTask
from ai_engine.services.workflow_engine import WorkflowEngine


@login_required
@require_POST
def approve_task(request, task_id):
    school = request.user.school
    task = get_object_or_404(
        AIAutomationTask,
        id=task_id,
        school=school,
    )

    task.status = "APPROVED"
    task.approved_by = request.user
    task.approved_at = timezone.now()
    task.save()

    WorkflowEngine.execute(task)

    messages.success(request, "Automation executed successfully.")
    return redirect("ai_engine:ai_command_center")