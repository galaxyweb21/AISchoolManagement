# ai_engine/views/parents.py
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
import json

from ai_engine.models import ParentChatMessage
from ai_engine.services.parent_assistant_engine import ParentAssistantService, ParentAssistantError
from students.models import Student


@login_required
def parent_children_list(request):
    """
    Landing page for a parent: their children, each linking to a separate
    chat thread. Skips straight to the thread if there's only one child -
    no reason to make the common case click through an extra page.
    """
    if request.user.role != 'PARENT':
        messages.error(request, "This assistant is for parent accounts.")
        return redirect('dashboard')

    children = Student.objects.filter(parent=request.user, school=request.user.school).select_related('user')
    if children.count() == 1:
        return redirect('ai_engine:parent_chat_thread', student_id=children.first().id)

    return render(request, 'ai_engine/parent_children_list.html', {'children': children})


@login_required
def parent_chat_thread(request, student_id):
    """
    Scoped to this parent's own child at the queryset level
    (parent=request.user, not just student.parent_id checked after the
    fact) - a parent can never even fetch another child's row here, let
    alone see their data.
    """
    if request.user.role != 'PARENT':
        messages.error(request, "This assistant is for parent accounts.")
        return redirect('dashboard')

    student = get_object_or_404(
        Student, id=student_id, parent=request.user, school=request.user.school
    )

    if request.method == 'POST':
        question = request.POST.get('question', '').strip()
        if question:
            history = ParentChatMessage.objects.filter(parent=request.user, student=student).order_by('created_at')
            ParentChatMessage.objects.create(
                school=request.user.school, parent=request.user, student=student,
                sender='PARENT', content=question,
            )
            try:
                answer = ParentAssistantService.ask(
                    parent=request.user, student=student, question=question, history_messages=history
                )
            except ParentAssistantError as exc:
                answer = str(exc)
            ParentChatMessage.objects.create(
                school=request.user.school, parent=request.user, student=student,
                sender='ASSISTANT', content=answer,
            )
        return redirect('ai_engine:parent_chat_thread', student_id=student.id)

    thread = ParentChatMessage.objects.filter(parent=request.user, student=student).order_by('created_at')
    other_children = Student.objects.filter(parent=request.user, school=request.user.school).exclude(id=student.id)
    context = {'student': student, 'thread': thread, 'other_children': other_children}
    return render(request, 'ai_engine/parent_chat_thread.html', context)
