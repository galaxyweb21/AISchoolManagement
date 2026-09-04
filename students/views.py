from core.pagination import paginate_queryset
# students/views.py
import secrets
import string
import json
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.db import transaction

from accounts.models import User
from .models import *
from .face_service import FaceRegistrationService
from attendance.models import Attendance
from assessments.models import Grade
from finance.models import Invoice
from academics.models import SchoolClass, TimetableEntry
from django.contrib.auth import get_user_model
from school.models import AcademicTerm

STAFF_ROLES = ['SUPER_ADMIN', 'SCHOOL_ADMIN', 'TEACHER', 'REGISTRAR', 'SECRETARY']
MANAGE_ROLES = ['SUPER_ADMIN', 'SCHOOL_ADMIN']
EDIT_ROLES = MANAGE_ROLES + ['REGISTRAR', 'SECRETARY']


def _teacher_classes(user, school):
    """
    Classes a TEACHER is authorized to see students for: their homeroom
    class(es), plus any class they're assigned to on a published
    timetable.
    """
    try:
        teacher = user.teacher_profile
    except Exception:
        return SchoolClass.objects.none()

    ids = list(
        teacher.homerooms.filter(school=school).values_list('id', flat=True)
    )

    timetable_ids = TimetableEntry.objects.filter(
        teacher=teacher,
        school_class__school=school,
        timetable__is_published=True,
    ).values_list('school_class_id', flat=True)
    ids.extend(list(timetable_ids))

    return SchoolClass.objects.filter(school=school, id__in=set(ids)).distinct()


def _generate_username(admission_number):
    base = admission_number.strip().lower().replace(' ', '')
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


def _generate_temp_password():
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(10))


# ============================================================
# STUDENT VIEWS
# ============================================================

@login_required
def student_list(request):
    if request.user.role not in STAFF_ROLES:
        messages.error(request, "You don't have permission to view students.")
        return redirect('dashboard:dashboard')
    school = request.user.school

    students = Student.objects.filter(school=school).select_related('user', 'parent', 'grade_level',
                                                                    'school_class').order_by('grade_level__order',
                                                                                             'user__last_name')

    if request.user.role == 'TEACHER':
        students = students.filter(school_class__in=_teacher_classes(request.user, school))

    query = request.GET.get('q', '').strip()
    if query:
        students = students.filter(user__first_name__icontains=query) | students.filter(
            user__last_name__icontains=query) | students.filter(admission_number__icontains=query)
    grade_filter = request.GET.get('grade', '').strip()
    if grade_filter:
        students = students.filter(grade_level_id=grade_filter)

    face_filter = request.GET.get('face', '').strip()
    if face_filter == 'registered':
        students = students.filter(face_registered=True)
    elif face_filter == 'unregistered':
        students = students.filter(face_registered=False)

    grade_levels = GradeLevel.objects.filter(school=school).order_by('order')

    if request.GET.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        students_data = []
        for student in students:
            students_data.append({
                'id': str(student.id),
                'name': student.user.get_full_name(),
                'admission_number': student.admission_number,
                'grade_level': student.grade_level.name if student.grade_level else None,
                'school_class': student.school_class.name if student.school_class else None,
                'face_registered': student.face_registered,
                'has_photo': bool(student.profile_photo),
                'photo_url': student.profile_photo.url if student.profile_photo else None,
            })

        return JsonResponse({
            'success': True,
            'students': students_data,
            'total': students.count(),
            'registered': students.filter(face_registered=True).count(),
            'unregistered': students.filter(face_registered=False).count(),
        })

    context = {
        'students': paginate_queryset(students, request),
        'query': query,
        'grade_filter': grade_filter,
        'face_filter': face_filter,
        'grade_levels': grade_levels,
        'can_manage': request.user.role in MANAGE_ROLES,
        'can_edit': request.user.role in EDIT_ROLES,
        'total_students': students.count(),
        'registered_faces': students.filter(face_registered=True).count(),
    }
    return render(request, 'students/student_list.html', context)


# students/views.py - Complete create_student view

@login_required
def create_student(request):
    if request.user.role not in EDIT_ROLES:
        messages.error(request, "You don't have permission to add a student.")
        return redirect('students:student_list')

    school = request.user.school
    existing_parents = User.objects.filter(school=school, role='PARENT').order_by('first_name', 'last_name')
    school_classes = SchoolClass.objects.filter(school=school).order_by('grade_level__order', 'name')

    # Get enrollment types
    from students.models import StudentEnrollmentType
    enrollment_types = StudentEnrollmentType.objects.filter(
        school=school,
        is_active=True
    ).order_by('order')

    # Get current active term for fee preparation
    from school.models import AcademicTerm
    current_term = AcademicTerm.objects.filter(
        academic_year__school=school,
        academic_year__is_active=True,
        is_active=True
    ).order_by('-start_date', '-id').first()

    if request.method != 'POST':
        return render(request, 'students/student_form.html', {
            'existing_parents': existing_parents,
            'school_classes': school_classes,
            'enrollment_types': enrollment_types,
            'current_term': current_term,
            'mode': 'create'
        })

    first_name = request.POST.get('first_name', '').strip()
    last_name = request.POST.get('last_name', '').strip()
    date_of_birth = request.POST.get('date_of_birth', '').strip()
    school_class_id = request.POST.get('school_class', '').strip()
    parent_id = request.POST.get('parent_id', '').strip()

    # Get enrollment type
    enrollment_type_id = request.POST.get('enrollment_type', '').strip()
    is_new_student = request.POST.get('is_new_student') == 'on'
    previous_school = request.POST.get('previous_school', '').strip()

    address = request.POST.get('address', '').strip()
    contact_phone = request.POST.get('contact_phone', '').strip()
    id_card_type = request.POST.get('id_card_type', '').strip()
    id_card_number = request.POST.get('id_card_number', '').strip()

    if not all([first_name, last_name, date_of_birth, school_class_id]):
        messages.error(request, "First name, last name, date of birth, and class are required.")
        return render(request, 'students/student_form.html', {
            'existing_parents': existing_parents,
            'school_classes': school_classes,
            'enrollment_types': enrollment_types,
            'current_term': current_term,
            'mode': 'create',
            'form_data': request.POST,
        })

    try:
        with transaction.atomic():
            # Generate admission number
            from students.models import Student
            admission_number = Student.generate_admission_number(school)

            # Generate username and password
            username = _generate_username(admission_number)
            student_temp_password = _generate_temp_password()

            # Create student user account
            student_user = User.objects.create_user(
                username=username,
                email='',
                password=student_temp_password,
                first_name=first_name,
                last_name=last_name,
                school=school,
                role='STUDENT',
                is_active=True,
            )

            # Handle parent
            parent = None
            if parent_id:
                parent = get_object_or_404(User, id=parent_id, school=school, role='PARENT')
            else:
                # Check if parent inline form is being used
                parent_first_name = request.POST.get('parent_first_name', '').strip()
                parent_last_name = request.POST.get('parent_last_name', '').strip()
                parent_email = request.POST.get('parent_email', '').strip()
                parent_phone = request.POST.get('parent_phone', '').strip()
                create_new_parent = request.POST.get('create_new_parent') == 'on'

                if create_new_parent and parent_first_name and parent_last_name and parent_email:
                    parent_username = _generate_username(parent_email)
                    parent_temp_password = _generate_temp_password()

                    parent = User.objects.create_user(
                        username=parent_username,
                        email=parent_email,
                        password=parent_temp_password,
                        first_name=parent_first_name,
                        last_name=parent_last_name,
                        school=school,
                        role='PARENT',
                        is_active=True,
                        phone_number=parent_phone,
                        default_password=parent_temp_password,
                    )

            # Get school class and grade level
            school_class = get_object_or_404(SchoolClass, id=school_class_id, school=school)
            grade_level = school_class.grade_level

            # Get enrollment type
            enrollment_type = None
            if enrollment_type_id:
                enrollment_type = get_object_or_404(
                    StudentEnrollmentType,
                    id=enrollment_type_id,
                    school=school
                )
            else:
                type_code = 'NEW' if is_new_student else 'RETURNING'
                enrollment_type = StudentEnrollmentType.objects.filter(
                    school=school,
                    code=type_code,
                    is_active=True
                ).first()

            # Determine if student is NEW - CRITICAL for add-ons
            is_new = False
            if enrollment_type and enrollment_type.code == 'NEW':
                is_new = True
            elif is_new_student:
                is_new = True

            # Create student
            student = Student.objects.create(
                school=school,
                user=student_user,
                parent=parent,
                admission_number=admission_number,
                date_of_birth=date_of_birth,
                grade_level=grade_level,
                school_class=school_class,
                address=address,
                contact_phone=contact_phone,
                id_card_type=id_card_type if id_card_type else None,
                id_card_number=id_card_number if id_card_number else None,
                default_password=student_temp_password,
                enrollment_type=enrollment_type,
                is_new_student=is_new,  # CRITICAL: This enables add-ons
                previous_school=previous_school if previous_school else None,
                enrollment_history=[],
            )

            # ============================================================
            # ENTERPRISE AUTOMATIC FEE + INVOICE LIFECYCLE
            # ============================================================
            # Keep the student-creation transaction intact, but delegate all
            # finance work to one idempotent service. The Student post-save
            # signal is a second safety net for students created elsewhere
            # (admin, imports, APIs, etc.).
            fee_prepared = False
            fee_error = None
            fee_preview = None
            invoice_created = False
            invoice = None

            if current_term:
                try:
                    from finance.services.auto_invoicing import ensure_student_term_invoice
                    from finance.models import StudentFee

                    invoice = ensure_student_term_invoice(
                        student,
                        created_by=request.user,
                        academic_term=current_term,
                    )

                    result = (
                        StudentFee.objects
                        .filter(
                            school=school,
                            student=student,
                            academic_term=current_term,
                        )
                        .prefetch_related('items__fee_category')
                        .first()
                    )

                    if result:
                        fee_prepared = result.status in ('PREPARED', 'APPROVED', 'INVOICED')
                        items_data = []
                        addon_count = 0
                        item_total = 0

                        for item in result.items.all():
                            amount = item.final_amount or 0
                            item_total += amount
                            items_data.append({
                                'description': item.description,
                                'amount': str(amount),
                                'category': item.fee_category.name,
                            })
                            if 'Add-on' in (item.description or '') or 'add-on' in (item.description or '').lower():
                                addon_count += 1

                        fee_preview = {
                            'total': str(item_total),
                            'base': str(result.base_amount or 0),
                            'discount': str(result.discount_amount or 0),
                            'arrears': str(result.arrears_amount or 0),
                            'status': result.status,
                            'items': items_data,
                            'addon_count': addon_count,
                        }

                    if invoice:
                        invoice_created = True
                        response_invoice_total = invoice.total_amount
                        if fee_preview is None:
                            fee_preview = {}
                        fee_preview['invoice_id'] = str(invoice.id)
                        fee_preview['invoice_number'] = invoice.invoice_number
                        fee_preview['invoice_total'] = str(response_invoice_total)

                except Exception as fee_error_exc:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.exception(
                        "Automatic finance processing failed while creating student %s",
                        student,
                    )
                    fee_error = str(fee_error_exc)

            # ============================================================
            # SUCCESS MESSAGE
            # ============================================================
            enrollment_label = enrollment_type.get_name_display() if enrollment_type else (
                'New' if is_new_student else 'Returning')
            success_msg = f"{first_name} {last_name} added as {enrollment_label} Student (Admission No. {admission_number})."

            if fee_prepared:
                if is_new and fee_preview and fee_preview.get('addon_count', 0) > 0:
                    addon_count = fee_preview.get('addon_count', 0)
                    success_msg += f" Fees have been auto-prepared with {addon_count} add-on(s)"
                else:
                    success_msg += " Fees have been auto-prepared"

                if invoice_created:
                    success_msg += " and invoiced"
                success_msg += " for the current term."
            elif fee_error:
                success_msg += f" Note: Could not auto-prepare fees: {fee_error}. Please prepare fees manually."

            messages.success(request, success_msg)

            # Prepare response data
            response_data = {
                'success': True,
                'student_id': str(student.id),
                'message': success_msg,
                'credentials': {
                    'username': username,
                    'password': student_temp_password,
                },
                'fee_prepared': fee_prepared,
                'fee_error': fee_error,
                'fee_preview': fee_preview,
                'invoice_created': invoice_created,
                'enrollment_type': enrollment_label,
                'is_new_student': is_new,
            }

            if invoice:
                response_data['invoice_id'] = str(invoice.id)
                response_data['invoice_number'] = invoice.invoice_number

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse(response_data)

            return redirect('students:student_detail', student_id=student.id)

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Student creation error: {e}")
        import traceback
        traceback.print_exc()

        messages.error(request, f"An error occurred during registration: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        return render(request, 'students/student_form.html', {
            'existing_parents': existing_parents,
            'school_classes': school_classes,
            'enrollment_types': enrollment_types,
            'current_term': current_term,
            'mode': 'create',
            'form_data': request.POST,
        })


@login_required
def edit_student(request, student_id):
    school = request.user.school
    if request.user.role not in EDIT_ROLES:
        messages.error(request, "You don't have permission to edit students.")
        return redirect('students:student_detail', student_id=student_id)

    student = get_object_or_404(Student.objects.select_related('user', 'grade_level', 'school_class'), id=student_id,
                                school=school)

    parents = User.objects.filter(school=school, role='PARENT').order_by('first_name', 'last_name')
    school_classes = SchoolClass.objects.filter(school=school).order_by('grade_level__order', 'name')
    enrollment_types = StudentEnrollmentType.objects.filter(
        school=school, is_active=True
    ).order_by('order', 'name')

    if request.method != 'POST':
        return render(request, 'students/student_form.html', {
            'existing_parents': parents,
            'school_classes': school_classes,
            'enrollment_types': enrollment_types,
            'mode': 'edit',
            'student': student,
        })

    # Student basic info
    student.user.first_name = request.POST.get('first_name', student.user.first_name).strip()
    student.user.last_name = request.POST.get('last_name', student.user.last_name).strip()
    student.user.email = request.POST.get('email', student.user.email).strip()
    student.user.save(update_fields=['first_name', 'last_name', 'email'])

    # Class
    school_class_id = request.POST.get('school_class', '').strip()
    if school_class_id:
        school_class = get_object_or_404(SchoolClass, id=school_class_id, school=school)
        student.school_class = school_class
        student.grade_level = school_class.grade_level
    else:
        student.school_class = None
        student.grade_level = None

    # Parent
    parent_id = request.POST.get('parent_id', '').strip()
    student.parent = get_object_or_404(User, id=parent_id, school=school, role='PARENT') if parent_id else None

    # Enrollment type: changing it updates the student's profile only. Existing
    # StudentFeeEnrollment records remain untouched so historical invoices stay correct.
    enrollment_type_id = request.POST.get('enrollment_type', '').strip()
    if enrollment_type_id:
        student.enrollment_type = get_object_or_404(
            StudentEnrollmentType, id=enrollment_type_id, school=school, is_active=True
        )
        student.is_new_student = student.enrollment_type.code == 'NEW'
    student.previous_school = request.POST.get('previous_school', '').strip() or None

    # Identification & Contact fields
    student.address = request.POST.get('address', '').strip()
    student.contact_phone = request.POST.get('contact_phone', '').strip()
    student.id_card_type = request.POST.get('id_card_type', '').strip()
    student.id_card_number = request.POST.get('id_card_number', '').strip()

    student.save(update_fields=[
        'grade_level', 'school_class', 'parent', 'enrollment_type',
        'is_new_student', 'previous_school',
        'address', 'contact_phone', 'id_card_type', 'id_card_number'
    ])

    messages.success(request, "Student details updated.")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Student updated successfully!'})

    return redirect('students:student_detail', student_id=student.id)


@login_required
def student_detail(request, student_id):
    school = request.user.school
    if request.user.role not in STAFF_ROLES:
        messages.error(request, "You don't have permission to view this.")
        return redirect('dashboard:dashboard')
    student = get_object_or_404(Student.objects.select_related('user', 'parent', 'grade_level'), id=student_id,
                                school=school)

    if request.user.role == 'TEACHER':
        allowed_class_ids = set(_teacher_classes(request.user, school).values_list('id', flat=True))
        if student.school_class_id not in allowed_class_ids:
            messages.error(request, "You don't have permission to view this student.")
            return redirect('students:student_list')

    today = timezone.localdate()
    lookback_start = today - timezone.timedelta(days=30)
    attendance_qs = Attendance.objects.filter(student=student, date__gte=lookback_start, date__lte=today)
    total_days = attendance_qs.count()
    present_days = attendance_qs.filter(status__in=['PRESENT', 'LATE']).count()
    attendance_rate = round((present_days / total_days) * 100, 1) if total_days else None
    recent_grades = Grade.objects.filter(student=student).select_related('assessment').order_by(
        '-assessment__created_at')[:8]
    invoices = Invoice.objects.filter(student=student).exclude(status='PAID')
    outstanding = sum((inv.balance_due for inv in invoices), 0)
    latest_risk = None
    try:
        from ai_engine.models import StudentRiskAssessment
        latest_risk = StudentRiskAssessment.objects.filter(student=student).order_by('-run__computed_at').first()
    except Exception:
        pass
    context = {
        'student': student,
        'attendance_rate': attendance_rate,
        'present_days': present_days,
        'total_days': total_days,
        'recent_grades': recent_grades,
        'invoices': invoices,
        'outstanding': outstanding,
        'latest_risk': latest_risk,
        'can_manage': request.user.role in MANAGE_ROLES,
        'can_edit': request.user.role in EDIT_ROLES,
    }
    return render(request, 'students/student_detail.html', context)


@login_required
@require_POST
def toggle_student_active(request, student_id):
    school = request.user.school
    if request.user.role not in MANAGE_ROLES:
        messages.error(request, "You don't have permission to do this.")
        return redirect('students:student_detail', student_id=student_id)
    student = get_object_or_404(Student, id=student_id, school=school)
    student.is_active = not student.is_active
    student.save(update_fields=['is_active'])
    messages.success(request, f"{student.user.get_full_name()} marked {'active' if student.is_active else 'inactive'}.")
    return redirect('students:student_detail', student_id=student.id)


# ============================================================
# FACE REGISTRATION VIEWS
# ============================================================

@login_required
@require_POST
def api_register_face(request, student_id):
    if request.user.role not in EDIT_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        school = request.user.school
        student = get_object_or_404(Student, id=student_id, school=school)

        data = json.loads(request.body)
        image_data = data.get('image')

        if not image_data:
            return JsonResponse({'success': False, 'error': 'No image provided.'}, status=400)

        success, message, encoding = FaceRegistrationService.register_student_face(
            student, image_data, request.user
        )

        return JsonResponse({
            'success': success,
            'message': message,
            'face_registered': success,
            'has_encoding': bool(encoding)
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def api_delete_face(request, student_id):
    if request.user.role not in EDIT_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        school = request.user.school
        student = get_object_or_404(Student, id=student_id, school=school)

        success, message = FaceRegistrationService.delete_student_face(student)

        return JsonResponse({
            'success': success,
            'message': message
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_face_preview(request, student_id):
    if request.user.role not in STAFF_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        school = request.user.school
        student = get_object_or_404(Student, id=student_id, school=school)

        if not student.profile_photo:
            return JsonResponse({'success': False, 'error': 'No face photo available.'}, status=404)

        return JsonResponse({
            'success': True,
            'image_url': student.profile_photo.url,
            'face_registered': student.face_registered,
            'registered_at': student.face_registered_at.isoformat() if student.face_registered_at else None
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_bulk_face_registration(request):
    if request.user.role not in EDIT_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    try:
        school = request.user.school
        data = json.loads(request.body)
        registrations = data.get('registrations', [])

        results = []
        success_count = 0
        failed_count = 0

        for reg in registrations:
            student_id = reg.get('student_id')
            image_data = reg.get('image')

            if not student_id or not image_data:
                results.append({
                    'student_id': student_id,
                    'success': False,
                    'message': 'Missing student ID or image'
                })
                failed_count += 1
                continue

            try:
                student = Student.objects.get(id=student_id, school=school)
                success, message, encoding = FaceRegistrationService.register_student_face(
                    student, image_data, request.user
                )

                results.append({
                    'student_id': student_id,
                    'student_name': str(student),
                    'success': success,
                    'message': message
                })

                if success:
                    success_count += 1
                else:
                    failed_count += 1

            except Student.DoesNotExist:
                results.append({
                    'student_id': student_id,
                    'success': False,
                    'message': 'Student not found'
                })
                failed_count += 1
            except Exception as e:
                results.append({
                    'student_id': student_id,
                    'success': False,
                    'message': str(e)
                })
                failed_count += 1

        return JsonResponse({
            'success': True,
            'total': len(registrations),
            'success_count': success_count,
            'failed_count': failed_count,
            'results': results
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def bulk_face_registration(request):
    if request.user.role not in EDIT_ROLES:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
        messages.error(request, "You don't have permission to manage face registrations.")
        return redirect('students:student_list')

    school = request.user.school
    unregistered_students = Student.objects.filter(
        school=school,
        is_active=True,
        face_registered=False
    ).select_related('user', 'grade_level', 'school_class').order_by('user__last_name')

    context = {
        'students': unregistered_students,
        'total_unregistered': unregistered_students.count(),
        'can_manage': request.user.role in MANAGE_ROLES,
        'can_edit': request.user.role in EDIT_ROLES,
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'students/bulk_face_registration_modal_content.html', context)

    return render(request, 'students/bulk_face_registration.html', context)


# ============================================================
# GRADE LEVEL VIEWS
# ============================================================

@login_required
def grade_level_list(request):
    if request.user.role not in MANAGE_ROLES:
        messages.error(request, "You don't have permission to manage grade levels.")
        return redirect('dashboard:dashboard')
    school = request.user.school
    grade_levels = GradeLevel.objects.filter(school=school).order_by('order')
    return render(request, 'students/grade_level_list.html', {'grade_levels': paginate_queryset(grade_levels, request)})


@login_required
def grade_level_create(request):
    if request.user.role not in MANAGE_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    school = request.user.school
    if request.method == 'GET':
        return render(request, 'students/grade_level_form_modal.html', {
            'mode': 'create',
            'action_url': 'students:grade_level_create'
        })
    name = request.POST.get('name', '').strip()
    order = request.POST.get('order', 0)
    if not name:
        return JsonResponse({'success': False, 'error': "Grade level name is required."})
    if GradeLevel.objects.filter(school=school, name=name).exists():
        return JsonResponse({'success': False, 'error': f"A grade level named '{name}' already exists."})
    GradeLevel.objects.create(school=school, name=name, order=order)
    return JsonResponse({'success': True, 'message': f"Grade level '{name}' created successfully."})


@login_required
def grade_level_edit(request, grade_level_id):
    if request.user.role not in MANAGE_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    school = request.user.school
    grade_level = get_object_or_404(GradeLevel, id=grade_level_id, school=school)
    if request.method == 'GET':
        return render(request, 'students/grade_level_form_modal.html', {
            'mode': 'edit',
            'grade_level': grade_level,
            'action_url': 'students:grade_level_edit'
        })
    name = request.POST.get('name', '').strip()
    order = request.POST.get('order', 0)
    if not name:
        return JsonResponse({'success': False, 'error': "Grade level name is required."})
    if GradeLevel.objects.filter(school=school, name=name).exclude(id=grade_level.id).exists():
        return JsonResponse({'success': False, 'error': f"A grade level named '{name}' already exists."})
    grade_level.name = name
    grade_level.order = order
    grade_level.save()
    return JsonResponse({'success': True, 'message': f"Grade level '{name}' updated successfully."})


@login_required
def grade_level_delete(request, grade_level_id):
    if request.user.role not in MANAGE_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)
    school = request.user.school
    grade_level = get_object_or_404(GradeLevel, id=grade_level_id, school=school)
    if request.method == 'GET':
        return render(request, 'students/grade_level_delete_modal.html', {
            'grade_level': grade_level,
            'action_url': 'students:grade_level_delete'
        })
    if grade_level.students.exists():
        return JsonResponse({
            'success': False,
            'error': f"Cannot delete '{grade_level.name}' because it has {grade_level.students.count()} students assigned to it."
        })
    grade_level.delete()
    return JsonResponse({'success': True, 'message': f"Grade level '{grade_level.name}' deleted successfully."})


# ============================================================
# STUDENT SELF-SERVICE VIEWS
# ============================================================

def _get_own_student_or_none(request):
    if not request.user.school:
        return None
    return Student.objects.select_related(
        'grade_level', 'school_class', 'user'
    ).filter(school=request.user.school, user=request.user).first()


@login_required
def my_grades(request):
    if request.user.role != 'STUDENT':
        messages.error(request, "This page is only available to students.")
        return redirect('dashboard:dashboard')

    student = _get_own_student_or_none(request)
    if not student:
        messages.error(request, "No student record is linked to your account.")
        return redirect('dashboard:dashboard')

    grades = Grade.objects.filter(student=student).select_related('assessment').order_by(
        'assessment__subject', '-updated_at'
    )

    context = {
        'student': student,
        'grades': paginate_queryset(grades, request),
    }
    return render(request, 'students/my_grades.html', context)


@login_required
def my_attendance(request):
    if request.user.role != 'STUDENT':
        messages.error(request, "This page is only available to students.")
        return redirect('dashboard:dashboard')

    student = _get_own_student_or_none(request)
    if not student:
        messages.error(request, "No student record is linked to your account.")
        return redirect('dashboard:dashboard')

    records = Attendance.objects.filter(student=student).order_by('-date')

    total = records.count()
    present = records.filter(status='PRESENT').count()
    attendance_rate = round((present / total * 100), 1) if total > 0 else 0

    page_obj = paginate_queryset(records, request)

    context = {
        'student': student,
        'records': page_obj,
        'total': total,
        'present': present,
        'attendance_rate': attendance_rate,
    }
    return render(request, 'students/my_attendance.html', context)


@login_required
def my_fees(request):
    if request.user.role != 'STUDENT':
        messages.error(request, "This page is only available to students.")
        return redirect('dashboard:dashboard')

    student = _get_own_student_or_none(request)
    if not student:
        messages.error(request, "No student record is linked to your account.")
        return redirect('dashboard:dashboard')

    invoices = Invoice.objects.filter(student=student).order_by('-created_at')
    total_billed = sum(inv.total_amount for inv in invoices) if invoices else Decimal('0.00')
    total_paid = sum(inv.amount_paid for inv in invoices) if invoices else Decimal('0.00')
    outstanding = total_billed - total_paid

    context = {
        'student': student,
        'invoices': paginate_queryset(invoices, request),
        'total_billed': total_billed,
        'total_paid': total_paid,
        'outstanding': outstanding,
    }
    return render(request, 'students/my_fees.html', context)


@login_required
def api_student_credentials(request, student_id):
    if request.user.role not in EDIT_ROLES:
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        school = request.user.school
        student = get_object_or_404(Student, id=student_id, school=school)

        student_password = None
        if hasattr(student, 'default_password') and student.default_password:
            student_password = student.default_password
        elif hasattr(student.user, 'default_password') and student.user.default_password:
            student_password = student.user.default_password
        else:
            student_password = "**********"

        parent_data = None
        if student.parent:
            parent_password = None
            if hasattr(student.parent, 'default_password') and student.parent.default_password:
                parent_password = student.parent.default_password
            else:
                parent_password = "**********"

            parent_data = {
                'id': str(student.parent.id),
                'full_name': student.parent.get_full_name() or student.parent.username,
                'username': student.parent.username,
                'password': parent_password,
                'email': student.parent.email or 'Not provided',
                'phone_number': student.parent.phone_number or 'Not provided',
            }

        return JsonResponse({
            'success': True,
            'student': {
                'id': str(student.id),
                'full_name': student.user.get_full_name() or student.user.username,
                'username': student.user.username,
                'password': student_password,
                'email': student.user.email or 'Not provided',
                'admission_number': student.admission_number,
            },
            'parent': parent_data,
        })

    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student not found.'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================
# PARENT / GUARDIAN API
# ============================================================

User = get_user_model()


def _parent_to_dict(parent):
    return {
        "id": str(parent.id),
        "first_name": parent.first_name or "",
        "last_name": parent.last_name or "",
        "full_name": parent.get_full_name().strip() or parent.username,
        "username": parent.username or "",
        "email": parent.email or "",
        "phone_number": getattr(parent, "phone_number", "") or "",
    }


@login_required
@require_GET
def api_get_parent(request, parent_id):
    try:
        parent = get_object_or_404(User, id=parent_id)

        school = getattr(request.user, 'school', None)
        if school is None:
            return JsonResponse({
                'success': False,
                'error': 'Your account is not linked to a school.'
            }, status=403)

        parent_student = Student.objects.filter(
            parent=parent,
            school=school
        ).first()

        if not parent_student:
            return JsonResponse({
                'success': False,
                'error': 'Parent not found for this school.'
            }, status=404)

        return JsonResponse({
            'success': True,
            'parent': {
                'id': str(parent.id),
                'first_name': parent.first_name or '',
                'last_name': parent.last_name or '',
                'email': parent.email or '',
                'phone_number': getattr(parent, 'phone_number', '') or '',
                'username': parent.username or '',
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)



@login_required
@require_POST
def api_edit_parent(request, parent_id):
    """
    Update parent/guardian account information.
    Accepts normal Django form POST data OR JSON.
    NOTE: Email is now handled by the separate api_edit_parent_email endpoint.
    """
    try:
        school = getattr(request.user, 'school', None)
        if school is None:
            return JsonResponse({
                'success': False,
                'error': 'Your account is not linked to a school.'
            }, status=403)

        parent = get_object_or_404(User, id=parent_id)

        # Verify the parent belongs to this school
        parent_student = Student.objects.filter(
            parent=parent,
            school=school
        ).first()

        if not parent_student:
            return JsonResponse({
                'success': False,
                'error': 'Parent account not found for this school.'
            }, status=404)

        # Check if request is JSON or form data
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body)
            first_name = data.get('first_name', '').strip()
            last_name = data.get('last_name', '').strip()
            phone_number = data.get('phone_number', '').strip()
            new_password = data.get('new_password', '').strip()
            # email is optional now - use existing if not provided
            email = data.get('email', parent.email).strip() if data.get('email') else parent.email
        else:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            phone_number = request.POST.get('phone_number', '').strip()
            new_password = request.POST.get('new_password', '').strip()
            # email is optional now - use existing if not provided
            email = request.POST.get('email', '').strip() or parent.email

        # Validate required fields (email is now optional)
        if not first_name:
            return JsonResponse({
                'success': False,
                'error': 'First name is required.'
            }, status=400)

        if not last_name:
            return JsonResponse({
                'success': False,
                'error': 'Last name is required.'
            }, status=400)

        # ============================================================
        # EMAIL UNIQUENESS CHECK - Only if email has changed
        # ============================================================
        if email and email != parent.email:
            # Check if ANY OTHER user has this email (case-insensitive)
            # Exclude the current parent from the check
            email_exists = User.objects.filter(
                email__iexact=email
            ).exclude(
                pk=parent.pk
            ).exists()

            if email_exists:
                return JsonResponse({
                    'success': False,
                    'error': 'This email address is already being used by another account.'
                }, status=400)

        # ============================================================
        # UPDATE PARENT
        # ============================================================
        with transaction.atomic():
            parent.first_name = first_name
            parent.last_name = last_name

            # Only update email if provided and different
            if email and email != parent.email:
                parent.email = email

            if hasattr(parent, 'phone_number'):
                parent.phone_number = phone_number

            if new_password:
                if len(new_password) < 6:
                    return JsonResponse({
                        'success': False,
                        'error': 'New password must contain at least 6 characters.'
                    }, status=400)
                parent.set_password(new_password)

            parent.save()

        return JsonResponse({
            'success': True,
            'message': 'Parent/Guardian details updated successfully.',
            'parent': {
                'id': str(parent.id),
                'first_name': parent.first_name or '',
                'last_name': parent.last_name or '',
                'email': parent.email or '',
                'phone_number': getattr(parent, 'phone_number', '') or '',
                'username': parent.username or '',
                'full_name': parent.get_full_name(),
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data.'
        }, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'Unable to update parent: {str(e)}'
        }, status=500)


# students/views.py - Fixed api_edit_parent_email view

@login_required
@require_POST
def api_edit_parent_email(request, parent_id):
    """
    Update only the parent/guardian email address.
    This also updates the student's email to match the parent's email
    to maintain consistency and avoid duplicate email conflicts.
    """
    try:
        school = getattr(request.user, 'school', None)
        if school is None:
            return JsonResponse({
                'success': False,
                'error': 'Your account is not linked to a school.'
            }, status=403)

        parent = get_object_or_404(User, id=parent_id)

        # Verify the parent belongs to this school
        parent_student = Student.objects.filter(
            parent=parent,
            school=school
        ).first()

        if not parent_student:
            return JsonResponse({
                'success': False,
                'error': 'Parent account not found for this school.'
            }, status=404)

        # Get email from request
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body)
            email = data.get('email', '').strip()
        else:
            email = request.POST.get('email', '').strip()

        # Validate email
        if not email:
            return JsonResponse({
                'success': False,
                'error': 'Email address is required.'
            }, status=400)

        # Validate email format
        import re
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            return JsonResponse({
                'success': False,
                'error': 'Please enter a valid email address.'
            }, status=400)

        # ============================================================
        # Email uniqueness check - allow same email for same parent
        # ============================================================
        # Check if ANY OTHER user has this email (case-insensitive)
        # Exclude the current parent from the check
        email_exists = User.objects.filter(
            email__iexact=email
        ).exclude(
            pk=parent.pk
        ).exists()

        if email_exists:
            return JsonResponse({
                'success': False,
                'error': 'This email address is already being used by another account.'
            }, status=400)

        # ============================================================
        # UPDATE EMAIL - Update both parent AND student
        # ============================================================
        with transaction.atomic():
            # Update parent email
            parent.email = email
            parent.save(update_fields=['email'])

            # ============================================================
            # FIXED: Update ALL students linked to this parent
            # ============================================================
            # Find all students in this school that have this parent
            students = Student.objects.filter(
                parent=parent,
                school=school
            ).select_related('user')

            for student in students:
                # Update the student's user email to match the parent's email
                student.user.email = email
                student.user.save(update_fields=['email'])

        return JsonResponse({
            'success': True,
            'message': 'Parent email and student email(s) updated successfully.',
            'parent': {
                'id': str(parent.id),
                'email': parent.email,
                'full_name': parent.get_full_name(),
            },
            'students_updated': students.count(),
            'student_names': [s.user.get_full_name() for s in students],
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data.'
        }, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': f'Unable to update parent email: {str(e)}'
        }, status=500)
