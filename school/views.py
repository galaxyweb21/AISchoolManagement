# school/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from .models import School, AcademicYear, AcademicTerm


@login_required
def school_dashboard(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You do not have permission to view this page.")
        return redirect('dashboard:dashboard')

    school = request.user.school
    academic_years = AcademicYear.objects.filter(school=school).prefetch_related('terms').order_by('-start_date')
    return render(request, 'school/school_dashboard.html', {'school': school, 'academic_years': academic_years})


@login_required
def school_settings(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        messages.error(request, "You do not have permission to edit school settings.")
        return redirect('dashboard:dashboard')

    school = request.user.school

    if request.method == 'GET':
        return render(request, 'school/school_settings_modal.html', {
            'school': school,
            'mode': 'edit',
            'action_url': 'school:school_settings'
        })

    # POST - Update school via AJAX
    name = request.POST.get('name', '').strip()
    contact_email = request.POST.get('contact_email', '').strip()
    phone_number = request.POST.get('phone_number', '').strip()
    address = request.POST.get('address', '').strip()
    logo = request.FILES.get('logo')

    if not all([name, contact_email, phone_number, address]):
        return JsonResponse({'success': False, 'error': "All fields are required."})

    school.name = name
    school.contact_email = contact_email
    school.phone_number = phone_number
    school.address = address

    if logo:
        # Delete old logo if it exists
        if school.logo:
            school.logo.delete(save=False)
        school.logo = logo

    school.save()
    return JsonResponse({'success': True, 'message': "School settings updated successfully."})


# ============================================================
# ACADEMIC YEAR MODAL CRUD
# ============================================================

@login_required
def academic_year_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school

    if request.method == 'GET':
        return render(request, 'school/academic_year_form_modal.html', {
            'mode': 'create', 'action_url': 'school:academic_year_create'
        })

    name = request.POST.get('name', '').strip()
    start_date = request.POST.get('start_date', '').strip()
    end_date = request.POST.get('end_date', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not all([name, start_date, end_date]):
        return JsonResponse({'success': False, 'error': "Name, Start Date, and End Date are required."})

    if AcademicYear.objects.filter(school=school, name=name).exists():
        return JsonResponse({'success': False, 'error': f"A year named '{name}' already exists."})

    if is_active:
        AcademicYear.objects.filter(school=school).update(is_active=False)

    AcademicYear.objects.create(school=school, name=name, start_date=start_date, end_date=end_date, is_active=is_active)
    return JsonResponse({'success': True, 'message': f"Year '{name}' created successfully."})


@login_required
def academic_year_edit(request, year_id):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    academic_year = get_object_or_404(AcademicYear, id=year_id, school=school)

    if request.method == 'GET':
        return render(request, 'school/academic_year_form_modal.html', {
            'mode': 'edit',
            'academic_year': academic_year,
            'action_url': 'school:academic_year_edit'
        })

    name = request.POST.get('name', '').strip()
    start_date = request.POST.get('start_date', '').strip()
    end_date = request.POST.get('end_date', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not all([name, start_date, end_date]):
        return JsonResponse({'success': False, 'error': "Name, Start Date, and End Date are required."})

    if AcademicYear.objects.filter(school=school, name=name).exclude(id=academic_year.id).exists():
        return JsonResponse({'success': False, 'error': f"A year named '{name}' already exists."})

    if is_active:
        AcademicYear.objects.filter(school=school).exclude(id=academic_year.id).update(is_active=False)

    academic_year.name = name
    academic_year.start_date = start_date
    academic_year.end_date = end_date
    academic_year.is_active = is_active
    academic_year.save()

    return JsonResponse({'success': True, 'message': f"Year '{name}' updated successfully."})


@login_required
@require_POST
def academic_year_delete(request, year_id):
    school = request.user.school
    academic_year = get_object_or_404(AcademicYear, id=year_id, school=school)
    academic_year.delete()
    return JsonResponse({'success': True, 'message': f"Year deleted successfully."})


# ============================================================
# ACADEMIC TERM MODAL CRUD
# ============================================================

@login_required
def academic_term_create(request):
    if request.user.role not in ['SUPER_ADMIN', 'SCHOOL_ADMIN']:
        return JsonResponse({'success': False, 'error': "Permission denied."}, status=403)

    school = request.user.school
    academic_years = AcademicYear.objects.filter(school=school).order_by('-start_date')

    if request.method == 'GET':
        return render(request, 'school/academic_term_form_modal.html', {
            'mode': 'create',
            'academic_years': academic_years,
            'action_url': 'school:academic_term_create'
        })

    academic_year_id = request.POST.get('academic_year', '').strip()
    name = request.POST.get('name', '').strip()
    start_date = request.POST.get('start_date', '').strip()
    end_date = request.POST.get('end_date', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not all([academic_year_id, name, start_date, end_date]):
        return JsonResponse({'success': False, 'error': "All fields are required."})

    academic_year = get_object_or_404(AcademicYear, id=academic_year_id, school=school)

    if is_active:
        AcademicTerm.objects.filter(academic_year__school=school).update(is_active=False)

    AcademicTerm.objects.create(
        academic_year=academic_year, name=name, start_date=start_date, end_date=end_date, is_active=is_active
    )
    return JsonResponse({'success': True, 'message': f"Term '{name}' created successfully."})


@login_required
def academic_term_edit(request, term_id):
    school = request.user.school
    academic_term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)
    academic_years = AcademicYear.objects.filter(school=school).order_by('-start_date')

    if request.method == 'GET':
        return render(request, 'school/academic_term_form_modal.html', {
            'mode': 'edit',
            'academic_term': academic_term,
            'academic_years': academic_years,
            'action_url': 'school:academic_term_edit'
        })

    academic_year_id = request.POST.get('academic_year', '').strip()
    name = request.POST.get('name', '').strip()
    start_date = request.POST.get('start_date', '').strip()
    end_date = request.POST.get('end_date', '').strip()
    is_active = request.POST.get('is_active') == 'on'

    if not all([academic_year_id, name, start_date, end_date]):
        return JsonResponse({'success': False, 'error': "All fields are required."})

    academic_year = get_object_or_404(AcademicYear, id=academic_year_id, school=school)

    if is_active:
        AcademicTerm.objects.filter(academic_year__school=school).exclude(id=academic_term.id).update(is_active=False)

    academic_term.academic_year = academic_year
    academic_term.name = name
    academic_term.start_date = start_date
    academic_term.end_date = end_date
    academic_term.is_active = is_active
    academic_term.save()

    return JsonResponse({'success': True, 'message': f"Term '{name}' updated successfully."})


@login_required
@require_POST
def academic_term_delete(request, term_id):
    school = request.user.school
    academic_term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)
    academic_term.delete()
    return JsonResponse({'success': True, 'message': f"Term deleted successfully."})