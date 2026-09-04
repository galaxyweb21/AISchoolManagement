from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import role_allows
from academics.models import TeacherAssignment, TeacherClassAssignment, SchoolClass
from ai_engine.models import ReportCardBatch, ReportCard, ReportCommentBatch
from ai_engine.services.report_card_batch import ReportCardBatchService
from ai_engine.services.report_card_engine import ReportCardEngine
from ai_engine.services.report_comment_service import ReportCommentService
from ai_engine.tasks import run_report_card_batch_task, run_report_comment_batch_task
from core.pagination import paginate_queryset
from school.models import AcademicTerm


def _school(request):
    return request.user.school


def _can_view(user):
    return role_allows(user, 'reports', 'view')


def _teacher_scope_class_ids(user, school):
    ids = set()
    try:
        teacher = user.teacher_profile
        ids.update(TeacherAssignment.objects.filter(school=school, teacher=teacher, is_active=True).values_list('school_class_id', flat=True))
        ids.update(TeacherClassAssignment.objects.filter(school=school, teacher=teacher, is_active=True).values_list('school_class_id', flat=True))
        ids.update(teacher.homerooms.filter(school=school, is_active=True).values_list('id', flat=True))
    except Exception:
        pass
    return ids


def _can_edit(user, card):
    if card.is_finalized:
        return False
    if user.role in ('SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD'):
        return True
    if user.role != 'TEACHER':
        return False
    return card.student.school_class_id in _teacher_scope_class_ids(user, user.school)


def _can_generate_headteacher(user):
    return role_allows(user, 'reports', 'approve')


def _can_generate_teacher(user, card):
    return _can_edit(user, card)


@login_required
def report_card_dashboard(request):
    if not _can_view(request.user):
        messages.error(request, "You don't have permission to view report cards.")
        return redirect('dashboard')
    school = _school(request)
    active_term = AcademicTerm.objects.filter(academic_year__school=school, academic_year__is_active=True, is_active=True).first()
    page_obj = []
    latest_batch = latest_comment_batch = None
    comment_counts = {'total': 0, 'teacher_missing': 0, 'head_missing': 0, 'complete': 0}
    accessible_classes = SchoolClass.objects.filter(school=school, is_active=True).order_by('name')
    if request.user.role == 'TEACHER':
        accessible_classes = accessible_classes.filter(id__in=_teacher_scope_class_ids(request.user, school))
    if active_term:
        latest_batch = ReportCardBatch.objects.filter(school=school, academic_term=active_term).first()
        latest_comment_batch = ReportCommentBatch.objects.filter(school=school, academic_term=active_term).first()
        qs = ReportCard.objects.filter(school=school, academic_term=active_term).select_related('student__user', 'student__school_class')
        if request.user.role == 'TEACHER':
            qs = qs.filter(student__school_class_id__in=_teacher_scope_class_ids(request.user, school))
        class_filter = request.GET.get('class_id', '').strip()
        if class_filter:
            qs = qs.filter(student__school_class_id=class_filter)
        status_filter = request.GET.get('status')
        if status_filter == 'finalized': qs = qs.filter(is_finalized=True)
        elif status_filter == 'draft': qs = qs.filter(is_finalized=False)
        elif status_filter == 'edited': qs = qs.filter(is_finalized=False, edited_by__isnull=False)
        elif status_filter == 'comments_missing': qs = qs.filter(Q(teacher_comment='') | Q(headteacher_comment=''))
        search = request.GET.get('q', '').strip()
        if search:
            qs = qs.filter(Q(student__user__first_name__icontains=search) | Q(student__user__last_name__icontains=search) | Q(student__admission_number__icontains=search))
        comment_counts['total'] = qs.count()
        comment_counts['teacher_missing'] = qs.filter(teacher_comment='').count()
        comment_counts['head_missing'] = qs.filter(headteacher_comment='').count()
        comment_counts['complete'] = qs.exclude(teacher_comment='').exclude(headteacher_comment='').count()
        page_obj = paginate_queryset(qs, request)
    return render(request, 'ai_engine/report_card_dashboard.html', {
        'active_term': active_term, 'latest_batch': latest_batch, 'latest_comment_batch': latest_comment_batch,
        'report_cards': page_obj, 'page_obj': page_obj, 'selected_status': request.GET.get('status', ''),
        'search_query': request.GET.get('q', ''), 'can_generate': role_allows(request.user, 'reports', 'create'),
        'can_generate_headteacher': _can_generate_headteacher(request.user), 'comment_counts': comment_counts, 'accessible_classes': accessible_classes,
    })


@login_required
@require_POST
def trigger_report_card_batch(request):
    if not role_allows(request.user, 'reports', 'create'):
        messages.error(request, "You don't have permission to generate report cards.")
        return redirect('ai_engine:report_card_dashboard')
    school = _school(request)
    active_term = AcademicTerm.objects.filter(academic_year__school=school, academic_year__is_active=True, is_active=True).first()
    if not active_term:
        messages.error(request, 'No active academic term is configured.')
        return redirect('ai_engine:report_card_dashboard')
    batch = ReportCardBatchService.create_pending(school, active_term, request.user)
    try:
        run_report_card_batch_task.delay(str(batch.id))
        messages.info(request, 'End-of-term report card generation has started.')
    except Exception:
        ReportCardBatchService.run(batch)
        messages.info(request, 'Report cards were generated using the available local worker.')
    return redirect('ai_engine:report_card_dashboard')


@login_required
@require_POST
def trigger_report_comment_batch(request):
    if not role_allows(request.user, 'reports', 'create'):
        messages.error(request, "You don't have permission to generate report-card comments.")
        return redirect('ai_engine:report_card_dashboard')
    school = _school(request)
    active_term = AcademicTerm.objects.filter(academic_year__school=school, academic_year__is_active=True, is_active=True).first()
    if not active_term:
        messages.error(request, 'No active academic term is configured.')
        return redirect('ai_engine:report_card_dashboard')
    class_id = request.POST.get('school_class_id') or None
    if request.user.role == 'TEACHER':
        allowed = _teacher_scope_class_ids(request.user, school)
        if class_id and str(class_id) not in {str(x) for x in allowed}:
            messages.error(request, 'You can only generate comments for your assigned classes.')
            return redirect('ai_engine:report_card_dashboard')
        if not class_id and len(allowed) == 1:
            class_id = next(iter(allowed))
    generate_head = request.POST.get('generate_headteacher') == '1' and _can_generate_headteacher(request.user)
    generate_teacher = request.POST.get('generate_teacher', '1') == '1'
    if not generate_head and not generate_teacher:
        messages.error(request, 'Select at least one comment type.')
        return redirect('ai_engine:report_card_dashboard')
    batch = ReportCommentBatch.objects.create(
        school=school, academic_term=active_term, school_class_id=class_id, triggered_by=request.user,
        only_missing=request.POST.get('mode', 'missing') == 'missing',
        regenerate_ai=request.POST.get('mode') == 'regenerate',
        generate_teacher=generate_teacher, generate_headteacher=generate_head,
    )
    try:
        run_report_comment_batch_task.delay(str(batch.id))
        messages.info(request, 'AI report-card comments are being generated in the background. Manual comments will be preserved.')
    except Exception:
        ReportCommentService.run_batch(batch)
        messages.info(request, 'Report-card comments were generated using the available local worker.')
    return redirect('ai_engine:report_card_dashboard')


@login_required
def report_card_detail(request, report_card_id):
    if not _can_view(request.user):
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard')
    card = get_object_or_404(ReportCard.objects.select_related('student__user', 'student__school_class', 'student__grade_level', 'academic_term'), id=report_card_id, school=_school(request))
    # Keep report cards synchronized with authoritative TerminalResult records.
    # This fixes cards that were generated (or finalized) before Class /30 and
    # Exam /70 were entered — draft cards fully resync; finalized cards keep
    # their locked average/grade/position but have blank score cells repaired.
    card, computed = ReportCardEngine.refresh_report_card_snapshot(card, save=True)
    if request.user.role == 'TEACHER' and not _can_edit(request.user, card):
        messages.error(request, 'This student is outside your assigned class.')
        return redirect('ai_engine:report_card_dashboard')
    stats = [('Average', f'{card.overall_average:.1f}%' if card.overall_average is not None else '—'), ('Overall Grade', card.overall_grade or '—'), ('Class Position', f'{card.overall_position} / {card.class_size}' if card.overall_position else '—'), ('Attendance', f'{card.attendance_rate:.1f}%' if card.attendance_rate is not None else '—')]
    can_teacher_comment = _can_generate_teacher(request.user, card)
    can_headteacher_comment = _can_generate_headteacher(request.user) and not card.is_finalized
    return render(request, 'ai_engine/report_card_detail.html', {
        'report_card': card, 'subject_breakdown': computed.get('subject_breakdown', card.subject_breakdown or []), 'can_edit': _can_edit(request.user, card), 'can_teacher_comment': can_teacher_comment,
        'can_headteacher_comment': can_headteacher_comment, 'can_finalize': role_allows(request.user, 'reports', 'approve'), 'stats': stats,
    })


@login_required
@require_POST
def save_report_card_narrative(request, report_card_id):
    card = get_object_or_404(ReportCard, id=report_card_id, school=_school(request))
    if not _can_edit(request.user, card):
        messages.error(request, 'You do not have permission to edit this report card.')
        return redirect('ai_engine:report_card_detail', report_card_id=card.id)
    now = timezone.now()
    old_teacher = card.teacher_comment
    new_teacher = request.POST.get('teacher_comment', '').strip()
    card.teacher_comment = new_teacher
    card.teacher_comment_source = 'MANUAL' if new_teacher else 'BLANK'
    card.teacher_comment_edited_by = request.user if new_teacher != old_teacher else card.teacher_comment_edited_by
    card.teacher_comment_edited_at = now if new_teacher != old_teacher else card.teacher_comment_edited_at
    if request.user.role in ('SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD'):
        old_head = card.headteacher_comment
        new_head = request.POST.get('headteacher_comment', '').strip()
        card.headteacher_comment = new_head
        card.headteacher_comment_source = 'MANUAL' if new_head else 'BLANK'
        card.headteacher_comment_edited_by = request.user if new_head != old_head else card.headteacher_comment_edited_by
        card.headteacher_comment_edited_at = now if new_head != old_head else card.headteacher_comment_edited_at
        card.promotion_status = request.POST.get('promotion_status', '').strip()
        next_term = request.POST.get('next_term_date', '').strip()
        card.next_term_date = next_term or None
    card.conduct = request.POST.get('conduct', '').strip()
    narrative = request.POST.get('narrative', '').strip()
    if narrative: card.ai_narrative = narrative
    card.edited_by, card.edited_at = request.user, now
    card.save()
    messages.success(request, 'Report card details saved. Manual comments are protected from bulk AI regeneration.')
    return redirect('ai_engine:report_card_detail', report_card_id=card.id)


@login_required
@require_POST
def generate_report_card_comment(request, report_card_id, comment_type):
    card = get_object_or_404(ReportCard, id=report_card_id, school=_school(request))
    if card.is_finalized:
        messages.error(request, 'Finalized report cards are locked.')
        return redirect('ai_engine:report_card_detail', report_card_id=card.id)
    if comment_type == 'teacher' and not _can_generate_teacher(request.user, card):
        messages.error(request, 'You do not have permission to generate the teacher comment for this student.')
        return redirect('ai_engine:report_card_detail', report_card_id=card.id)
    if comment_type == 'headteacher' and not _can_generate_headteacher(request.user):
        messages.error(request, 'Only authorized academic administrators can generate the headteacher comment.')
        return redirect('ai_engine:report_card_detail', report_card_id=card.id)
    force = request.POST.get('force') == '1'
    try:
        ok, _ = ReportCommentService.generate_single(card, request.user, comment_type, force=force)
        if ok:
            messages.success(request, f'{comment_type.title()} comment generated successfully.')
        else:
            messages.info(request, 'The existing manual comment was preserved.')
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect('ai_engine:report_card_detail', report_card_id=card.id)


@login_required
@require_POST
def regenerate_report_card_narrative(request, report_card_id):
    card = get_object_or_404(ReportCard, id=report_card_id, school=_school(request))
    if not _can_edit(request.user, card):
        messages.error(request, 'You do not have permission to regenerate this report card.')
        return redirect('ai_engine:report_card_detail', report_card_id=card.id)
    ReportCardBatchService.regenerate_single(card)
    messages.success(request, 'Report card recalculated and AI narrative refreshed.')
    return redirect('ai_engine:report_card_detail', report_card_id=card.id)


@login_required
@require_POST
def finalize_report_card(request, report_card_id):
    if not role_allows(request.user, 'reports', 'approve'):
        messages.error(request, 'Only authorized academic administrators can finalize report cards.')
        return redirect('ai_engine:report_card_detail', report_card_id=report_card_id)
    card = get_object_or_404(ReportCard, id=report_card_id, school=_school(request))
    ReportCardBatchService.finalize(card, request.user)
    messages.success(request, 'Report card finalized and locked.')
    return redirect('ai_engine:report_card_detail', report_card_id=card.id)


@login_required
@require_POST
def unfinalize_report_card(request, report_card_id):
    if not role_allows(request.user, 'reports', 'approve'):
        messages.error(request, 'Only authorized administrators can unlock a report card.')
        return redirect('ai_engine:report_card_detail', report_card_id=report_card_id)
    card = get_object_or_404(ReportCard, id=report_card_id, school=_school(request))
    card.is_finalized, card.finalized_by, card.finalized_at = False, None, None
    card.save(update_fields=['is_finalized', 'finalized_by', 'finalized_at'])
    messages.success(request, 'Report card unlocked for editing.')
    return redirect('ai_engine:report_card_detail', report_card_id=card.id)