from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from datetime import date
import re
import secrets
import string
from django.utils import timezone

from accounts.models import User
from academics.models import SchoolClass
from school.models import AcademicYear
from students.models import GradeLevel, Student, StudentEnrollmentType
from core.pagination import paginate_queryset
from .models import AdmissionApplication


ADMIN_ROLES = {'SUPER_ADMIN', 'SCHOOL_ADMIN', 'REGISTRAR'}


def admissions_enabled_for_school(school):
    return bool(school and school.admissions_mode != 'OFF')


def allowed_stages(school):
    if school.admissions_mode == 'ALL':
        return {'KG', 'PRIMARY', 'JHS', 'SHS', 'OTHER'}
    if school.admissions_mode == 'JHS_SHS':
        return {'JHS', 'SHS'}
    return set()


def ensure_admissions_access(request):
    if request.user.role not in ADMIN_ROLES:
        raise Http404
    school = request.user.school
    if not admissions_enabled_for_school(school):
        raise Http404
    return school


@login_required
def dashboard(request):
    school = ensure_admissions_access(request)
    applications = AdmissionApplication.objects.filter(school=school)

    counts = {
        status: applications.filter(status=status).count()
        for status, _ in AdmissionApplication.STATUS_CHOICES
    }

    # Keep the dashboard useful even when the school has only a few applications.
    recent_applications = (
        applications
        .select_related('grade_level', 'school_class', 'academic_year', 'created_by', 'reviewed_by', 'admitted_student', 'parent')
        .order_by('-created_at')[:8]
    )

    class_rows = list(
        applications
        .filter(school_class__isnull=False)
        .values('school_class__name', 'grade_level__name')
        .annotate(total=Count('id'))
        .order_by('-total', 'school_class__name')[:8]
    )

    # A compact pipeline for the visual dashboard.
    pipeline = OrderedDict([
        ('SUBMITTED', counts.get('SUBMITTED', 0)),
        ('REVIEW', counts.get('REVIEW', 0)),
        ('APPROVED', counts.get('APPROVED', 0)),
        ('ADMITTED', counts.get('ADMITTED', 0)),
        ('REJECTED', counts.get('REJECTED', 0)),
    ])

    return render(request, 'admissions/dashboard.html', {
        'counts': counts,
        'total': applications.count(),
        'recent_applications': recent_applications,
        'class_rows': class_rows,
        'pipeline': pipeline,
    })


@login_required
def application_list(request):
    school = ensure_admissions_access(request)
    qs = (
        AdmissionApplication.objects
        .filter(school=school)
        .select_related('grade_level', 'academic_year', 'school_class')
    )

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip().upper()

    if q:
        qs = qs.filter(
            Q(application_number__icontains=q)
            | Q(first_name__icontains=q)
            | Q(middle_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(parent_name__icontains=q)
            | Q(parent_phone__icontains=q)
            | Q(parent_email__icontains=q)
        )

    if status in dict(AdmissionApplication.STATUS_CHOICES):
        qs = qs.filter(status=status)

    total_matching = qs.count()
    status_counts = {
        value: AdmissionApplication.objects.filter(school=school, status=value).count()
        for value, _ in AdmissionApplication.STATUS_CHOICES
    }
    page_obj = paginate_queryset(qs, request)

    return render(request, 'admissions/application_list.html', {
        'applications': page_obj,
        'page_obj': page_obj,
        'query': q,
        'status': status,
        'status_choices': AdmissionApplication.STATUS_CHOICES,
        'total_matching': total_matching,
        'status_counts': status_counts,
    })


@login_required
def application_create(request):
    school = ensure_admissions_access(request)
    years = AcademicYear.objects.filter(school=school).order_by('-start_date')
    grades = GradeLevel.objects.filter(
        school=school,
        stage__in=allowed_stages(school),
    ).order_by('order', 'name')
    classes = SchoolClass.objects.filter(
        school=school,
        is_active=True,
        grade_level__stage__in=allowed_stages(school),
    ).select_related('grade_level').order_by('grade_level__order', 'name')
    parents = User.objects.filter(school=school, role='PARENT', is_active=True).order_by('first_name', 'last_name')

    errors = []
    form_data = request.POST if request.method == 'POST' else {}

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        middle_name = request.POST.get('middle_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        dob_raw = request.POST.get('date_of_birth', '').strip()
        gender = request.POST.get('gender', '').strip().upper()
        applicant_phone = request.POST.get('applicant_phone', '').strip()
        applicant_email = request.POST.get('applicant_email', '').strip()
        applicant_address = request.POST.get('applicant_address', '').strip()
        previous_school = request.POST.get('previous_school', '').strip()
        academic_year_id = request.POST.get('academic_year', '').strip()
        grade_id = request.POST.get('grade_level', '').strip()
        class_id = request.POST.get('school_class', '').strip()
        parent_id = request.POST.get('parent_id', '').strip()
        parent_first_name = request.POST.get('parent_first_name', '').strip()
        parent_last_name = request.POST.get('parent_last_name', '').strip()
        parent_name = ''
        parent_relationship = request.POST.get('parent_relationship', '').strip()
        parent_phone = request.POST.get('parent_phone', '').strip()
        parent_email = request.POST.get('parent_email', '').strip()
        parent_address = request.POST.get('parent_address', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not first_name:
            errors.append('Applicant first name is required.')
        if not last_name:
            errors.append('Applicant last name is required.')
        if not dob_raw:
            errors.append('Applicant date of birth is required.')
        else:
            try:
                dob = date.fromisoformat(dob_raw)
                if dob >= date.today():
                    errors.append('Date of birth must be in the past.')
            except ValueError:
                errors.append('Enter a valid date of birth.')
                dob = None

        if gender not in {'MALE', 'FEMALE', 'OTHER'}:
            errors.append('Select the applicant gender.')
        if not academic_year_id:
            errors.append('Academic year is required.')
        if not grade_id:
            errors.append('Applying grade is required.')
        if not parent_id and not parent_first_name:
            errors.append('Parent / guardian first name is required.')
        if not parent_id and not parent_last_name:
            errors.append('Parent / guardian last name is required.')
        if not parent_phone and not parent_id:
            errors.append('Parent / guardian phone is required.')
        if parent_email:
            try:
                validate_email(parent_email)
            except ValidationError:
                errors.append('Enter a valid parent / guardian email address.')
        if applicant_email:
            try:
                validate_email(applicant_email)
            except ValidationError:
                errors.append('Enter a valid applicant email address.')

        academic_year = AcademicYear.objects.filter(id=academic_year_id, school=school).first() if academic_year_id else None
        grade = GradeLevel.objects.filter(id=grade_id, school=school).first() if grade_id else None
        school_class = None
        if class_id and grade:
            school_class = SchoolClass.objects.filter(
                id=class_id, school=school, grade_level=grade, is_active=True
            ).first()
            if not school_class:
                errors.append('The selected class is not valid for the selected grade.')

        if academic_year_id and not academic_year:
            errors.append('Select a valid academic year for this school.')
        if grade_id and not grade:
            errors.append('Select a valid applying grade for this school.')
        if grade and grade.stage not in allowed_stages(school):
            errors.append('Admissions is not enabled for the selected school level.')

        parent = None
        if parent_id:
            parent = User.objects.filter(id=parent_id, school=school, role='PARENT', is_active=True).first()
            if not parent:
                errors.append('The selected parent / guardian account is not valid.')
            else:
                parent_name = f'{parent.first_name} {parent.last_name}'.strip() or parent.get_full_name()
                parent_phone = parent.phone_number or parent_phone
                parent_email = parent.email or parent_email

        # Avoid accidental duplicate applications for the same applicant in the same academic year.
        if not errors and academic_year and dob:
            duplicate_qs = AdmissionApplication.objects.filter(
                school=school,
                academic_year=academic_year,
                first_name__iexact=first_name,
                last_name__iexact=last_name,
                date_of_birth=dob,
            ).exclude(status='REJECTED')
            if duplicate_qs.exists():
                existing = duplicate_qs.order_by('-created_at').first()
                errors.append(
                    f'This applicant already has an active application ({existing.application_number}). '
                    'Review that application instead of creating a duplicate.'
                )

        if not errors:
            if parent:
                parent_name = f'{parent.first_name} {parent.last_name}'.strip() or parent.get_full_name()
            else:
                parent_name = ' '.join(p for p in [parent_first_name, parent_last_name] if p).strip()
            if not parent_name:
                errors.append('Enter the parent / guardian first and last name.')
            else:
                application = AdmissionApplication.objects.create(
                    school=school,
                    academic_year=academic_year,
                    first_name=first_name,
                    middle_name=middle_name,
                    last_name=last_name,
                    date_of_birth=dob,
                    gender=gender,
                    applicant_phone=applicant_phone,
                    applicant_email=applicant_email,
                    applicant_address=applicant_address,
                    grade_level=grade,
                    school_class=school_class,
                    parent=parent,
                    parent_name=parent_name,
                    parent_relationship=parent_relationship,
                    parent_phone=parent_phone,
                    parent_email=parent_email,
                    parent_address=parent_address,
                    previous_school=previous_school,
                    notes=notes,
                    created_by=request.user,
                    status='SUBMITTED',
                )
                messages.success(request, f'Application {application.application_number} submitted successfully.')
                return redirect('admissions:application_detail', application_id=application.id)

    return render(request, 'admissions/application_form.html', {
        'academic_years': years,
        'grade_levels': grades,
        'school_classes': classes,
        'parents': parents,
        'admissions_mode': school.admissions_mode,
        'errors': errors,
        'form_data': form_data,
    })


@login_required
def application_detail(request, application_id):
    school = ensure_admissions_access(request)
    application = get_object_or_404(
        AdmissionApplication.objects.select_related('grade_level', 'school_class', 'academic_year', 'created_by', 'reviewed_by', 'admitted_student', 'parent'),
        id=application_id,
        school=school,
    )
    return render(request, 'admissions/application_detail.html', {'application': application})


@login_required
def application_status(request, application_id, action):
    school = ensure_admissions_access(request)
    if request.method != 'POST':
        return redirect('admissions:application_detail', application_id=application_id)
    application = get_object_or_404(AdmissionApplication, id=application_id, school=school)
    if action == 'review' and application.status == 'SUBMITTED':
        application.status = 'REVIEW'
    elif action == 'approve' and application.status in {'SUBMITTED', 'REVIEW'}:
        application.status = 'APPROVED'
        application.reviewed_at = timezone.now()
        application.reviewed_by = request.user
    elif action == 'reject' and application.status in {'SUBMITTED', 'REVIEW'}:
        application.status = 'REJECTED'
        application.rejection_reason = request.POST.get('rejection_reason', '').strip()
        application.reviewed_at = timezone.now()
        application.reviewed_by = request.user
    else:
        messages.warning(request, 'That application status cannot be changed from its current state.')
        return redirect('admissions:application_detail', application_id=application.id)
    application.save()
    messages.success(request, f'Application {application.application_number} updated.')
    return redirect('admissions:application_detail', application_id=application.id)


@login_required
@transaction.atomic
def admit_application(request, application_id):
    school = ensure_admissions_access(request)
    if request.method != 'POST':
        return redirect('admissions:application_detail', application_id=application_id)
    application = get_object_or_404(
        AdmissionApplication.objects.select_for_update(), id=application_id, school=school
    )
    if not application.can_admit:
        messages.error(request, 'Only approved applications that have not already been admitted can be admitted.')
        return redirect('admissions:application_detail', application_id=application.id)

    # Reuse a selected parent account, otherwise create a parent account from the
    # approved application. This keeps the application as the source of truth.
    parent = application.parent
    parent_temp_password = None
    if not parent and application.parent_email:
        parent = User.objects.filter(
            school=school, role='PARENT', email__iexact=application.parent_email
        ).first()
    if not parent:
        parent_first, _, parent_last = application.parent_name.partition(' ')
        base = re.sub(r'[^a-z0-9]+', '.', application.parent_email.split('@')[0].lower()) if application.parent_email else ''
        if not base:
            base = re.sub(r'[^a-z0-9]+', '.', application.parent_name.lower()).strip('.') or 'parent'
        username = base
        suffix = 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f'{base}{suffix}'
        alphabet = string.ascii_letters + string.digits
        parent_temp_password = 'EduAI@' + ''.join(secrets.choice(alphabet) for _ in range(8))
        parent = User.objects.create_user(
            username=username,
            password=parent_temp_password,
            first_name=parent_first,
            last_name=parent_last or parent_first,
            email=application.parent_email or '',
            role='PARENT',
            school=school,
            phone_number=application.parent_phone,
            default_password=parent_temp_password,
            is_active=True,
        )

    username_base = f"{application.first_name}.{application.last_name}".lower().replace(' ', '')
    username = username_base or f"student{str(application.id)[:8]}"
    counter = 1
    candidate = username
    while User.objects.filter(username=candidate).exists():
        counter += 1
        candidate = f"{username}{counter}"
    temp_password = f"EduAI@{timezone.localdate().year}{str(application.id)[:4]}"
    user = User.objects.create_user(
        username=candidate,
        password=temp_password,
        first_name=application.first_name,
        last_name=application.last_name,
        email=application.applicant_email or '',
        role='STUDENT',
        school=school,
        phone_number=application.applicant_phone or None,
    )
    user.gender = application.gender or None
    user.save(update_fields=['gender', 'email', 'phone_number'])

    enrollment_type = StudentEnrollmentType.objects.filter(
        school=school, code='NEW', is_active=True
    ).first()
    student = Student.objects.create(
        school=school,
        user=user,
        parent=parent,
        date_of_birth=application.date_of_birth,
        grade_level=application.grade_level,
        school_class=application.school_class,
        enrollment_type=enrollment_type,
        is_new_student=True,
        previous_school=application.previous_school or None,
        contact_phone=application.applicant_phone or application.parent_phone,
        address=application.applicant_address or application.parent_address,
        default_password=temp_password,
    )
    application.parent = parent
    application.status = 'ADMITTED'
    application.admitted_at = timezone.now()
    application.admitted_student = student
    application.save(update_fields=['parent', 'status', 'admitted_at', 'admitted_student', 'updated_at'])

    message = f'{application.applicant_name} has been admitted as {student.admission_number}. Temporary username: {username}.'
    if parent_temp_password:
        message += f' Parent account created; temporary password: {parent_temp_password}.'
    messages.success(request, message)
    return redirect('students:student_detail', student_id=student.id)

