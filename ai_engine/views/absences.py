# ai_engine/views/absences.py
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
import json

from staff.models import Teacher, TeacherAbsence
from ai_engine.models import SubstituteAssignment
from ai_engine.services.substitute_engine import CoverPlanService, SubstituteMatchService, SubstituteCoverError

COVER_ROLES = ['SUPER_ADMIN', 'SCHOOL_ADMIN']


@login_required
def absence_list(request):
    if request.user.role not in COVER_ROLES:
        messages.error(request, "You don't have permission to view absence cover.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    absences = TeacherAbsence.objects.filter(school=school).select_related('teacher__user').prefetch_related(
        'substitute_assignments'
    )
    teachers = Teacher.objects.filter(school=school, is_active=True).select_related('user')
    context = {'absences': absences, 'teachers': teachers}
    return render(request, 'ai_engine/absence_list.html', context)


from django.utils.dateparse import parse_date


@login_required
@require_POST
def report_absence(request):
    if request.user.role not in COVER_ROLES:
        messages.error(request, "You don't have permission to report an absence.")
        return redirect('ai_engine:absence_list')

    school = request.user.school
    teacher = get_object_or_404(Teacher, id=request.POST.get('teacher_id'), school=school)
    absence_date = parse_date(request.POST.get('date', ''))
    reason = request.POST.get('reason', 'OTHER')
    notes = request.POST.get('notes', '').strip()

    if not absence_date:
        messages.error(request, "Please provide a valid date.")
        return redirect('ai_engine:absence_list')

    absence, created = TeacherAbsence.objects.get_or_create(
        school=school, teacher=teacher, date=absence_date,
        defaults={'reason': reason, 'notes': notes, 'reported_by': request.user},
    )
    if not created:
        messages.info(request, "This teacher was already marked absent that day - showing the existing cover plan.")
        return redirect('ai_engine:cover_plan_detail', absence_id=absence.id)

    try:
        CoverPlanService.generate_for_absence(absence, generated_by=request.user)
        messages.success(request, "Absence recorded and cover plan generated.")
    except SubstituteCoverError as exc:
        messages.warning(request, f"Absence recorded, but a cover plan couldn't be generated: {exc}")

    return redirect('ai_engine:cover_plan_detail', absence_id=absence.id)


@login_required
def cover_plan_detail(request, absence_id):
    school = request.user.school
    if request.user.role not in COVER_ROLES:
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard')

    absence = get_object_or_404(TeacherAbsence.objects.select_related('teacher__user'), id=absence_id, school=school)
    assignments = SubstituteAssignment.objects.filter(absence=absence).select_related(
        'timetable_entry__subject', 'timetable_entry__school_class', 'timetable_entry__timeslot',
        'timetable_entry__room', 'suggested_substitute__user', 'confirmed_substitute__user',
    )

    _, published = CoverPlanService._find_published_timetable(school, absence.date)
    rows = []
    for a in assignments:
        candidates = SubstituteMatchService.find_candidates(a.timetable_entry, absence, published) if published else []
        rows.append({'assignment': a, 'candidates': candidates})

    context = {'absence': absence, 'rows': rows, 'has_published_timetable': bool(published)}
    return render(request, 'ai_engine/cover_plan_detail.html', context)


@login_required
@require_POST
def regenerate_cover_plan(request, absence_id):
    school = request.user.school
    if request.user.role not in COVER_ROLES:
        messages.error(request, "You don't have permission to do this.")
        return redirect('ai_engine:cover_plan_detail', absence_id=absence_id)

    absence = get_object_or_404(TeacherAbsence, id=absence_id, school=school)
    try:
        CoverPlanService.generate_for_absence(absence, generated_by=request.user)
        messages.success(request, "Cover plan refreshed. Confirmed assignments were left untouched.")
    except SubstituteCoverError as exc:
        messages.error(request, str(exc))
    return redirect('ai_engine:cover_plan_detail', absence_id=absence.id)


@login_required
@require_POST
def confirm_substitute(request, assignment_id):
    school = request.user.school
    if request.user.role not in COVER_ROLES:
        messages.error(request, "You don't have permission to do this.")
        return redirect('dashboard')

    assignment = get_object_or_404(SubstituteAssignment, id=assignment_id, school=school)
    chosen_id = request.POST.get('substitute_id')
    chosen = get_object_or_404(Teacher, id=chosen_id, school=school) if chosen_id else assignment.suggested_substitute

    if not chosen:
        messages.error(request, "No substitute selected - nothing to confirm.")
        return redirect('ai_engine:cover_plan_detail', absence_id=assignment.absence_id)

    assignment.confirmed_substitute = chosen
    assignment.status = 'CONFIRMED'
    assignment.confirmed_by = request.user
    assignment.confirmed_at = timezone.now()
    assignment.save(update_fields=['confirmed_substitute', 'status', 'confirmed_by', 'confirmed_at'])
    messages.success(request, f"{chosen.user.get_full_name()} confirmed to cover this period.")
    return redirect('ai_engine:cover_plan_detail', absence_id=assignment.absence_id)


@login_required
@require_POST
def unconfirm_substitute(request, assignment_id):
    school = request.user.school
    if request.user.role not in COVER_ROLES:
        messages.error(request, "You don't have permission to do this.")
        return redirect('dashboard')

    assignment = get_object_or_404(SubstituteAssignment, id=assignment_id, school=school)
    assignment.status = 'SUGGESTED' if assignment.suggested_substitute else 'UNCOVERED'
    assignment.confirmed_substitute = None
    assignment.confirmed_by = None
    assignment.confirmed_at = None
    assignment.save(update_fields=['status', 'confirmed_substitute', 'confirmed_by', 'confirmed_at'])
    messages.info(request, "Confirmation undone - you can pick a different substitute.")
    return redirect('ai_engine:cover_plan_detail', absence_id=assignment.absence_id)


@login_required
@require_POST
def save_handover_note(request, assignment_id):
    school = request.user.school
    assignment = get_object_or_404(SubstituteAssignment, id=assignment_id, school=school)
    assignment.handover_note = request.POST.get('handover_note', '').strip()
    assignment.note_edited_by = request.user
    assignment.note_edited_at = timezone.now()
    assignment.save(update_fields=['handover_note', 'note_edited_by', 'note_edited_at'])
    messages.success(request, "Handover note updated.")
    return redirect('ai_engine:cover_plan_detail', absence_id=assignment.absence_id)