from core.pagination import paginate_queryset
# academics/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q

from school.models import AcademicTerm, AcademicYear
from .models import *
from .services import *
from .tasks import generate_timetable_task
from students.models import *

from .forms import TimeSlotForm
from .models import PromotionRule, PromotionBatch, StudentPromotion, SchoolClass
from academics.services.promotion_service import PromotionService


# ============================================================
# AI TIMETABLER LOGIC (Keep as is)
# ============================================================

@login_required
def timetable_workspace(request):
    school = request.user.school
    if not school:
        messages.error(request, "No school associated with your account.")
        return redirect('dashboard')

    active_term = AcademicTerm.objects.filter(
        academic_year__school=school, academic_year__is_active=True, is_active=True
    ).first()

    timetables = Timetable.objects.filter(school=school)
    if active_term:
        timetables = timetables.filter(academic_term=active_term)
    timetables = timetables.order_by('-generated_at')[:10]

    context = {
        'active_term': active_term,
        'timetables': timetables,
        'can_generate': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
    }
    return render(request, 'academics/timetable_workspace.html', context)


@login_required
@require_POST
def generate_timetable(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to generate a timetable.")
        return redirect('academics:timetable_workspace')

    school = request.user.school
    active_term = AcademicTerm.objects.filter(
        academic_year__school=school, academic_year__is_active=True, is_active=True
    ).first()

    if not active_term:
        messages.error(request, "No active academic term is configured. Set one up in School Settings first.")
        return redirect('academics:timetable_workspace')

    timetable = AITimetableService.create_pending(
        school=school, academic_term=active_term, generated_by=request.user
    )

    try:
        generate_timetable_task.delay(str(timetable.id))
        messages.info(request, "Timetable generation started. This page will update automatically.")
    except Exception:
        messages.warning(request, "Background worker unavailable - generating inline instead.")
        AITimetableService.run(timetable)

    return redirect('academics:timetable_detail', timetable_id=timetable.id)


@login_required
def timetable_detail(request, timetable_id):
    school = request.user.school
    timetable = get_object_or_404(Timetable, id=timetable_id, school=school)

    if timetable.status in ('PENDING', 'RUNNING'):
        context = {'timetable': timetable}
        return render(request, 'academics/timetable_generating.html', context)

    # FIXED: Count entries directly without triggering the tenant manager
    entries_count = TimetableEntry.objects.filter(timetable=timetable).count()

    # FIXED: Get entries without filtering by school (since TimetableEntry doesn't have school field)
    entries = TimetableEntry.objects.filter(
        timetable=timetable
    ).select_related(
        'school_class', 'subject', 'teacher__user', 'room', 'timeslot'
    )

    days = ['MON', 'TUE', 'WED', 'THU', 'FRI']
    timeslots = list(TimeSlot.objects.filter(school=school).order_by('period_index', 'day'))
    period_indexes = sorted(set(s.period_index for s in timeslots))
    classes = SchoolClass.objects.filter(school=school).order_by('name')
    selected_class_id = request.GET.get('class_id')

    # Get selected class name for display
    selected_class_display = None
    if selected_class_id:
        try:
            selected_class = SchoolClass.objects.get(id=selected_class_id, school=school)
            selected_class_display = selected_class.name
        except SchoolClass.DoesNotExist:
            pass

    slot_lookup = {}
    for entry in entries:
        if selected_class_id and str(entry.school_class_id) != selected_class_id:
            continue
        key = (entry.timeslot.period_index, entry.timeslot.day)
        slot_lookup[key] = entry

    rows = []
    for p in period_indexes:
        cells = [slot_lookup.get((p, d)) for d in days]
        rows.append({'period': p, 'cells': cells})

    context = {
        'timetable': timetable,
        'days': days,
        'rows': rows,
        'classes': classes,
        'selected_class_id': selected_class_id,
        'selected_class_display': selected_class_display,
        'entries_count': entries_count,
        'can_publish': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'],
    }
    return render(request, 'academics/timetable_detail.html', context)


@login_required
@require_POST
def publish_timetable(request, timetable_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to publish a timetable.")
        return redirect('academics:timetable_detail', timetable_id=timetable_id)

    school = request.user.school
    timetable = get_object_or_404(Timetable, id=timetable_id, school=school)
    if timetable.status != 'COMPLETE':
        messages.error(request, "Only a completed timetable can be published.")
        return redirect('academics:timetable_detail', timetable_id=timetable_id)

    AITimetableService.publish(timetable)
    messages.success(request, "Timetable published. It's now the active timetable for the term.")
    return redirect('academics:timetable_detail', timetable_id=timetable.id)


# academics/views.py - Fixed delete_timetable view

@login_required
def delete_timetable(request, timetable_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "You don't have permission to delete a timetable."}, status=403)

    school = request.user.school
    timetable = get_object_or_404(Timetable, id=timetable_id, school=school)

    if request.method == 'GET':
        # Count entries directly using the timetable filter
        entries_count = TimetableEntry.objects.filter(timetable=timetable).count()
        return render(request, 'academics/timetable_delete_modal.html', {
            'timetable': timetable,
            'entries_count': entries_count,
            'action_url': 'academics:delete_timetable'
        })

    if timetable.is_published:
        return JsonResponse({
            'success': False,
            'error': "This is the published, active timetable — publish a different one before deleting it.",
        })

    # TimetableEntry rows cascade-delete with the timetable (on_delete=CASCADE),
    # so nothing extra to clean up here.
    timetable.delete()
    return JsonResponse({
        'success': True,
        'message': "Timetable deleted.",
        'redirect_url': reverse('academics:timetable_workspace'),
    })


# ============================================================
# SUBJECT MANAGEMENT - FULL MODAL SUPPORT
# ============================================================

@login_required
def subject_list(request):
    school = request.user.school
    if not school: return redirect('dashboard')
    subjects = Subject.objects.filter(school=school).order_by('name')
    return render(request, 'academics/subject_list.html',
                  {'subjects': paginate_queryset(subjects, request), 'can_manage': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN']})


@login_required
def subject_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
    school = request.user.school
    if request.method == 'GET':
        return render(request, 'academics/subject_form_modal.html',
                      {'mode': 'create', 'action_url': 'academics:subject_create'})
    name = request.POST.get('name', '').strip()
    requires_lab = request.POST.get('requires_lab', False) == 'on'
    if not name:
        return JsonResponse({'success': False, 'error': "Subject name is required."})
    if Subject.objects.filter(school=school, name=name).exists():
        return JsonResponse({'success': False, 'error': f"A subject named '{name}' already exists."})
    Subject.objects.create(school=school, name=name, requires_lab=requires_lab)
    return JsonResponse({'success': True, 'message': f"Subject '{name}' created successfully."})


@login_required
def subject_edit(request, subject_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
    school = request.user.school
    subject = get_object_or_404(Subject, id=subject_id, school=school)
    if request.method == 'GET':
        return render(request, 'academics/subject_form_modal.html',
                      {'mode': 'edit', 'subject': subject, 'action_url': 'academics:subject_edit'})
    name = request.POST.get('name', '').strip()
    requires_lab = request.POST.get('requires_lab', False) == 'on'
    if not name:
        return JsonResponse({'success': False, 'error': "Subject name is required."})
    if Subject.objects.filter(school=school, name=name).exclude(id=subject.id).exists():
        return JsonResponse({'success': False, 'error': f"A subject named '{name}' already exists."})
    subject.name = name
    subject.requires_lab = requires_lab
    subject.save()
    return JsonResponse({'success': True, 'message': f"Subject '{name}' updated successfully."})


@login_required
def subject_delete(request, subject_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
    school = request.user.school
    subject = get_object_or_404(Subject, id=subject_id, school=school)
    if request.method == 'GET':
        return render(request, 'academics/subject_delete_modal.html',
                      {'subject': subject, 'action_url': 'academics:subject_delete'})
    subject.delete()
    return JsonResponse({'success': True, 'message': f"Subject '{subject.name}' deleted successfully."})


# ============================================================
# SCHOOL CLASS MANAGEMENT - FIXED WITH COMPLETE DUPLICATE CHECK
# ============================================================

@login_required
def school_class_list(request):
    school = request.user.school
    if not school: return redirect('dashboard:dashboard')
    classes = SchoolClass.objects.filter(school=school).select_related('grade_level').order_by('grade_level__order',
                                                                                               'name')
    return render(request, 'academics/class_list.html',
                  {'classes': paginate_queryset(classes, request), 'can_manage': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN']})


@login_required
def school_class_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    grade_levels = GradeLevel.objects.filter(school=school).order_by('order')

    if request.method == 'GET':
        return render(request, 'academics/class_form_modal.html', {
            'grade_levels': grade_levels,
            'mode': 'create',
            'action_url': 'academics:school_class_create'
        })

    # Handle POST request
    try:
        name = request.POST.get('name', '').strip()
        grade_level_id = request.POST.get('grade_level', '').strip()

        if not all([name, grade_level_id]):
            return JsonResponse({
                'success': False,
                'error': "Class name and Grade Level are required."
            }, status=400)

        grade_level = get_object_or_404(GradeLevel, id=grade_level_id, school=school)

        # Check if class exists with same name AND grade level.
        if SchoolClass.objects.filter(school=school, name__iexact=name, grade_level=grade_level).exists():
            return JsonResponse({
                'success': False,
                'error': f"A class named '{name}' already exists in {grade_level.name}. Each class name must be unique within a grade level."
            }, status=400)

        # Create the class
        SchoolClass.objects.create(school=school, name=name, grade_level=grade_level)

        return JsonResponse({
            'success': True,
            'message': f"Class '{name}' created successfully in {grade_level.name}."
        })

    except IntegrityError as e:
        return JsonResponse({
            'success': False,
            'error': (
                f"'{name}' couldn't be saved because of a database-level uniqueness "
                f"constraint that appears to ignore Grade Level. If you're trying to "
                f"reuse this class name in a different grade level, the SchoolClass "
                f"model's unique constraint likely needs to include grade_level "
                f"(this requires a models.py change + migration, not just a view fix)."
            )
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"An error occurred: {str(e)}"
        }, status=500)


@login_required
def school_class_edit(request, class_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    school_class = get_object_or_404(SchoolClass, id=class_id, school=school)
    grade_levels = GradeLevel.objects.filter(school=school).order_by('order')

    if request.method == 'GET':
        return render(request, 'academics/class_form_modal.html', {
            'mode': 'edit',
            'school_class': school_class,
            'grade_levels': grade_levels,
            'action_url': 'academics:school_class_edit'
        })

    # Handle POST request
    try:
        name = request.POST.get('name', '').strip()
        grade_level_id = request.POST.get('grade_level', '').strip()

        if not all([name, grade_level_id]):
            return JsonResponse({
                'success': False,
                'error': "Class name and Grade Level are required."
            }, status=400)

        grade_level = get_object_or_404(GradeLevel, id=grade_level_id, school=school)

        if SchoolClass.objects.filter(school=school, name__iexact=name, grade_level=grade_level).exclude(
                id=school_class.id).exists():
            return JsonResponse({
                'success': False,
                'error': f"A class named '{name}' already exists in {grade_level.name}. Each class name must be unique within a grade level."
            }, status=400)

        school_class.name = name
        school_class.grade_level = grade_level
        school_class.save()

        return JsonResponse({
            'success': True,
            'message': f"Class '{name}' updated successfully in {grade_level.name}."
        })

    except IntegrityError as e:
        return JsonResponse({
            'success': False,
            'error': (
                f"'{name}' couldn't be saved because of a database-level uniqueness "
                f"constraint that appears to ignore Grade Level. If you're trying to "
                f"reuse this class name in a different grade level, the SchoolClass "
                f"model's unique constraint likely needs to include grade_level "
                f"(this requires a models.py change + migration, not just a view fix)."
            )
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"An error occurred: {str(e)}"
        }, status=500)


@login_required
def school_class_delete(request, class_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    school_class = get_object_or_404(SchoolClass, id=class_id, school=school)

    if request.method == 'GET':
        return render(request, 'academics/class_delete_modal.html', {
            'school_class': school_class,
            'action_url': 'academics:school_class_delete'
        })

    # Handle POST request
    try:
        if school_class.timetable_entries.exists():
            return JsonResponse({
                'success': False,
                'error': f"Cannot delete '{school_class.name}' because it has timetable entries. Remove the timetable entries first."
            }, status=400)

        class_name = school_class.name
        school_class.delete()

        return JsonResponse({
            'success': True,
            'message': f"Class '{class_name}' deleted successfully."
        })

    except IntegrityError as e:
        return JsonResponse({
            'success': False,
            'error': f"Database error: {str(e)}"
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"An error occurred: {str(e)}"
        }, status=500)


# ============================================================
# ROOM MANAGEMENT
# ============================================================

@login_required
def room_list(request):
    school = request.user.school
    if not school: return redirect('dashboard:dashboard')
    rooms = Room.objects.filter(school=school).order_by('name')
    return render(request, 'academics/room_list.html',
                  {'rooms': paginate_queryset(rooms, request), 'can_manage': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN']})


@login_required
def room_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
    school = request.user.school
    if request.method == 'GET':
        return render(request, 'academics/room_form_modal.html',
                      {'mode': 'create', 'action_url': 'academics:room_create'})
    name = request.POST.get('name', '').strip()
    capacity = request.POST.get('capacity', 40)
    is_lab = request.POST.get('is_lab', False) == 'on'
    if not name:
        return JsonResponse({'success': False, 'error': "Room name is required."})
    if Room.objects.filter(school=school, name=name).exists():
        return JsonResponse({'success': False, 'error': f"A room named '{name}' already exists."})
    Room.objects.create(school=school, name=name, capacity=capacity, is_lab=is_lab)
    return JsonResponse({'success': True, 'message': f"Room '{name}' created successfully."})


@login_required
def room_edit(request, room_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
    school = request.user.school
    room = get_object_or_404(Room, id=room_id, school=school)
    if request.method == 'GET':
        return render(request, 'academics/room_form_modal.html',
                      {'mode': 'edit', 'room': room, 'action_url': 'academics:room_edit'})
    name = request.POST.get('name', '').strip()
    capacity = request.POST.get('capacity', 40)
    is_lab = request.POST.get('is_lab', False) == 'on'
    if not name:
        return JsonResponse({'success': False, 'error': "Room name is required."})
    if Room.objects.filter(school=school, name=name).exclude(id=room.id).exists():
        return JsonResponse({'success': False, 'error': f"A room named '{name}' already exists."})
    room.name = name
    room.capacity = capacity
    room.is_lab = is_lab
    room.save()
    return JsonResponse({'success': True, 'message': f"Room '{name}' updated successfully."})


@login_required
def room_delete(request, room_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)
    school = request.user.school
    room = get_object_or_404(Room, id=room_id, school=school)
    if request.method == 'GET':
        return render(request, 'academics/room_delete_modal.html',
                      {'room': room, 'action_url': 'academics:room_delete'})
    room.delete()
    return JsonResponse({'success': True, 'message': f"Room '{room.name}' deleted successfully."})


# ============================================================
# TIMESLOT MANAGEMENT - FULL MODAL SUPPORT
# ============================================================

@login_required
def timeslot_list(request):
    school = request.user.school
    if not school: return redirect('dashboard')
    timeslots = TimeSlot.objects.filter(school=school).order_by('day', 'period_index')
    return render(request, 'academics/timeslot_list.html',
                  {'timeslots': paginate_queryset(timeslots, request), 'can_manage': request.user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN']})


@login_required
@require_http_methods(["GET", "POST"])
def timeslot_create(request):
    """Create a new timeslot"""
    school = request.user.school

    if request.method == "POST":
        form = TimeSlotForm(request.POST)
        if form.is_valid():
            try:
                timeslot = form.save(commit=False)
                timeslot.school = school
                timeslot.save()

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'timeslot_id': str(timeslot.id),
                        'message': 'TimeSlot created successfully!'
                    })
                return redirect('academics:timeslot_list')
            except IntegrityError:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': 'A timeslot with this day and period already exists.'
                    }, status=400)
                form.add_error(None, 'A timeslot with this day and period already exists.')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': ' '.join([' '.join(errors) for errors in form.errors.values()])
                }, status=400)
    else:
        form = TimeSlotForm()

    return render(request, 'academics/timeslot_form_modal.html', {
        'mode': 'create',
        'action_url': 'academics:timeslot_create',
        'form': form,
        'timeslot': None
    })


@login_required
@require_http_methods(["GET", "POST"])
def timeslot_edit(request, timeslot_id):
    """Edit an existing timeslot"""
    school = request.user.school
    timeslot = get_object_or_404(TimeSlot, id=timeslot_id, school=school)

    if request.method == "POST":
        form = TimeSlotForm(request.POST, instance=timeslot)
        if form.is_valid():
            try:
                form.save()

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': 'TimeSlot updated successfully!'
                    })
                return redirect('academics:timeslot_list')
            except IntegrityError:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': 'A timeslot with this day and period already exists.'
                    }, status=400)
                form.add_error(None, 'A timeslot with this day and period already exists.')
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': ' '.join([' '.join(errors) for errors in form.errors.values()])
                }, status=400)
    else:
        form = TimeSlotForm(instance=timeslot)

    return render(request, 'academics/timeslot_form_modal.html', {
        'mode': 'edit',
        'action_url': 'academics:timeslot_edit',
        'form': form,
        'timeslot': timeslot
    })


@login_required
@require_http_methods(["GET", "POST"])
def timeslot_delete(request, timeslot_id):
    """Delete a timeslot"""
    school = request.user.school
    timeslot = get_object_or_404(TimeSlot, id=timeslot_id, school=school)

    if request.method == "POST":
        try:
            timeslot.delete()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'TimeSlot deleted successfully!'
                })
            return redirect('academics:timeslot_list')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': f'Error deleting timeslot: {str(e)}'
                }, status=500)
            return render(request, 'academics/timeslot_delete_modal.html', {
                'timeslot': timeslot,
                'error': f'Error deleting timeslot: {str(e)}'
            })

    return render(request, 'academics/timeslot_delete_modal.html', {
        'timeslot': timeslot,
        'action_url': 'academics:timeslot_delete'
    })


# ============================================================
# STUDENT PROMOTION VIEWS - FIXED
# ============================================================

@login_required
def promotion_dashboard(request):
    """Dashboard for student promotions."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD']:
        messages.error(request, "You don't have permission to access promotions.")
        return redirect('dashboard')

    school = request.user.school

    # Get current academic year
    current_year = AcademicYear.objects.filter(school=school, is_active=True).first()

    # Get promotion statistics
    stats = PromotionService.get_promotion_statistics(school, current_year)

    # Get recent promotions - FIXED: filter through academic_year__school
    recent_promotions = StudentPromotion.objects.filter(
        promotion_batch__academic_year__school=school
    ).select_related('student__user', 'from_grade_level', 'to_grade_level', 'promotion_batch')[:20]

    # Get pending promotions - FIXED: filter through academic_year__school
    pending = StudentPromotion.objects.filter(
        promotion_batch__academic_year__school=school,
        status='PENDING'
    ).count()

    # Get promotion rules
    rules = PromotionRule.objects.filter(school=school, is_active=True)

    context = {
        'stats': stats,
        'recent_promotions': recent_promotions,
        'pending_count': pending,
        'rules': rules,
        'current_year': current_year,
        'active_tab': 'academics',
    }
    return render(request, 'academics/promotion/dashboard.html', context)


@login_required
def promotion_batch_list(request):
    """List all promotion batches."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD']:
        messages.error(request, "You don't have permission to view promotions.")
        return redirect('dashboard')

    school = request.user.school

    # FIXED: Filter through academic_year__school
    batches = PromotionBatch.objects.filter(
        academic_year__school=school
    ).order_by('-created_at')

    page_obj = paginate_queryset(batches, request)

    context = {
        'batches': page_obj,
        'active_tab': 'academics',
    }
    return render(request, 'academics/promotion/batch_list.html', context)


@login_required
def promotion_batch_create(request):
    """Create and process a new promotion batch."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        # Get available grade levels and terms
        grade_levels = GradeLevel.objects.filter(school=school).order_by('order')
        # FIXED: Filter terms through academic_year__school
        terms = AcademicTerm.objects.filter(
            academic_year__school=school,
            is_active=True
        ).select_related('academic_year')

        rules = PromotionRule.objects.filter(school=school, is_active=True)

        context = {
            'grade_levels': grade_levels,
            'terms': terms,
            'rules': rules,
            'mode': 'create',
            'action_url': 'academics:promotion_batch_create',
        }
        return render(request, 'academics/promotion/batch_form_modal.html', context)

    # POST - Process promotion batch
    from_grade_level_id = request.POST.get('from_grade_level')
    to_grade_level_id = request.POST.get('to_grade_level')
    academic_term_id = request.POST.get('academic_term')
    promotion_rule_id = request.POST.get('promotion_rule')
    batch_name = request.POST.get('name', '').strip()
    mode = request.POST.get('mode', 'AUTO')

    if not all([from_grade_level_id, to_grade_level_id, academic_term_id]):
        return JsonResponse({'success': False, 'error': "All required fields must be filled."})

    try:
        result = PromotionService.process_promotion_batch(
            school=school,
            from_grade_level_id=from_grade_level_id,
            to_grade_level_id=to_grade_level_id,
            academic_term_id=academic_term_id,
            promotion_rule_id=promotion_rule_id or None,
            batch_name=batch_name,
            processed_by=request.user,
            mode=mode
        )

        if result['success']:
            messages.success(
                request,
                f"Promotion batch processed: {result['stats']['promoted']} promoted, "
                f"{result['stats']['conditional']} conditional, "
                f"{result['stats']['repeated']} repeated."
            )
            return redirect('academics:promotion_batch_detail', batch_id=result['batch'].id)
        else:
            messages.error(request, f"Error processing promotion: {result['error']}")
            return redirect('academics:promotion_dashboard')

    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('academics:promotion_dashboard')


@login_required
def promotion_batch_detail(request, batch_id):
    """View details of a promotion batch."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'HOD']:
        messages.error(request, "You don't have permission to view promotions.")
        return redirect('dashboard')

    school = request.user.school

    # FIXED: Filter through academic_year__school
    batch = get_object_or_404(PromotionBatch, id=batch_id, academic_year__school=school)

    # Get promotions in this batch
    promotions = StudentPromotion.objects.filter(
        promotion_batch=batch
    ).select_related('student__user', 'from_grade_level', 'to_grade_level')

    # Apply filters
    status_filter = request.GET.get('status')
    if status_filter:
        promotions = promotions.filter(status=status_filter)

    page_obj = paginate_queryset(promotions, request)

    context = {
        'batch': batch,
        'promotions': page_obj,
        'selected_status': status_filter,
        'active_tab': 'academics',
    }
    return render(request, 'academics/promotion/batch_detail.html', context)


@login_required
def promotion_apply(request, promotion_id):
    """Apply a promotion to a student."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    try:
        result = PromotionService.apply_promotion(promotion_id, request.user)

        if result['success']:
            messages.success(request, result['message'])
        else:
            messages.error(request, result['error'])

    except Exception as e:
        messages.error(request, f"Error: {str(e)}")

    # Redirect back to the referring page
    referer = request.META.get('HTTP_REFERER', 'academics:promotion_dashboard')
    return redirect(referer)


@login_required
def promotion_bulk_apply(request, batch_id):
    """Apply all eligible promotions in a batch."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to perform this action.")
        return redirect('academics:promotion_dashboard')

    school = request.user.school
    # FIXED: Filter through academic_year__school
    batch = get_object_or_404(PromotionBatch, id=batch_id, academic_year__school=school)

    if request.method == 'POST':
        try:
            # Get all promotions in batch that are eligible for application
            promotions = StudentPromotion.objects.filter(
                promotion_batch=batch,
                status__in=['PROMOTED', 'CONDITIONAL']
            )

            applied = 0
            for promotion in promotions:
                result = PromotionService.apply_promotion(promotion.id, request.user)
                if result['success']:
                    applied += 1

            if applied > 0:
                messages.success(request, f"Successfully applied {applied} promotions.")
            else:
                messages.warning(request, "No promotions were applied.")

        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

        return redirect('academics:promotion_batch_detail', batch_id=batch.id)

    # GET - Show confirmation page
    promotions = StudentPromotion.objects.filter(
        promotion_batch=batch,
        status__in=['PROMOTED', 'CONDITIONAL']
    ).select_related('student__user')

    context = {
        'batch': batch,
        'promotions': promotions,
        'action_url': 'academics:promotion_bulk_apply',
    }
    return render(request, 'academics/promotion/bulk_apply_modal.html', context)


@login_required
def promotion_rule_list(request):
    """List all promotion rules."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You don't have permission to view promotion rules.")
        return redirect('dashboard')

    school = request.user.school

    rules = PromotionRule.objects.filter(school=school).order_by('from_grade_level__order')

    context = {
        'rules': paginate_queryset(rules, request),
        'active_tab': 'academics',
    }
    return render(request, 'academics/promotion/rule_list.html', context)


@login_required
def promotion_rule_create(request):
    """Create a new promotion rule."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        grade_levels = GradeLevel.objects.filter(school=school).order_by('order')
        return render(request, 'academics/promotion/rule_form_modal.html', {
            'grade_levels': grade_levels,
            'mode': 'create',
            'action_url': 'academics:promotion_rule_create'
        })

    # POST - Create rule
    from_grade_id = request.POST.get('from_grade_level')
    to_grade_id = request.POST.get('to_grade_level')
    promotion_mode = request.POST.get('promotion_mode', 'AUTO')
    min_pass = request.POST.get('minimum_passing_grade', 50)
    min_subjects = request.POST.get('minimum_subjects_to_pass', 0)
    min_average = request.POST.get('minimum_overall_average', 50)
    min_attendance = request.POST.get('minimum_attendance_percentage', 75)
    allow_conditional = request.POST.get('allow_conditional_promotion') == 'on'
    max_conditional = request.POST.get('max_conditional_subjects', 2)
    eval_term = request.POST.get('evaluation_term_sequence', 3)

    if not all([from_grade_id, to_grade_id]):
        return JsonResponse({'success': False, 'error': "From and To grade levels are required."})

    try:
        rule = PromotionRule.objects.create(
            school=school,
            from_grade_level_id=from_grade_id,
            to_grade_level_id=to_grade_id,
            promotion_mode=promotion_mode,
            minimum_passing_grade=min_pass,
            minimum_subjects_to_pass=min_subjects,
            minimum_overall_average=min_average,
            minimum_attendance_percentage=min_attendance,
            allow_conditional_promotion=allow_conditional,
            max_conditional_subjects=max_conditional,
            evaluation_term_sequence=eval_term,
        )
        return JsonResponse({
            'success': True,
            'message': f"Promotion rule created for {rule.from_grade_level.name} → {rule.to_grade_level.name}"
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def promotion_rule_edit(request, rule_id):
    """Edit an existing promotion rule."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    rule = get_object_or_404(PromotionRule, id=rule_id, school=school)

    if request.method == 'GET':
        grade_levels = GradeLevel.objects.filter(school=school).order_by('order')
        return render(request, 'academics/promotion/rule_form_modal.html', {
            'rule': rule,
            'grade_levels': grade_levels,
            'mode': 'edit',
            'action_url': 'academics:promotion_rule_edit'
        })

    # POST - Update rule
    promotion_mode = request.POST.get('promotion_mode', 'AUTO')
    min_pass = request.POST.get('minimum_passing_grade', 50)
    min_subjects = request.POST.get('minimum_subjects_to_pass', 0)
    min_average = request.POST.get('minimum_overall_average', 50)
    min_attendance = request.POST.get('minimum_attendance_percentage', 75)
    allow_conditional = request.POST.get('allow_conditional_promotion') == 'on'
    max_conditional = request.POST.get('max_conditional_subjects', 2)
    eval_term = request.POST.get('evaluation_term_sequence', 3)
    is_active = request.POST.get('is_active') == 'on'

    try:
        rule.promotion_mode = promotion_mode
        rule.minimum_passing_grade = min_pass
        rule.minimum_subjects_to_pass = min_subjects
        rule.minimum_overall_average = min_average
        rule.minimum_attendance_percentage = min_attendance
        rule.allow_conditional_promotion = allow_conditional
        rule.max_conditional_subjects = max_conditional
        rule.evaluation_term_sequence = eval_term
        rule.is_active = is_active
        rule.save()

        return JsonResponse({
            'success': True,
            'message': f"Promotion rule updated for {rule.from_grade_level.name} → {rule.to_grade_level.name}"
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def promotion_rule_delete(request, rule_id):
    """Delete a promotion rule."""
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    rule = get_object_or_404(PromotionRule, id=rule_id, school=school)

    try:
        rule.delete()
        return JsonResponse({'success': True, 'message': "Promotion rule deleted successfully."})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
