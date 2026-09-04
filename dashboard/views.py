# dashboard/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.db.models import Sum, Count, Q
from django.utils.timezone import localdate, timedelta
from decimal import Decimal

from students.models import Student
from finance.models import Invoice, InvoiceLineItem, Payment
from attendance.models import Attendance
from core.models import ActivityLog

from ai_engine.models import (
    GeneratedExam,
    StudentRiskAssessment,
)
from ai_engine.models import AIActivity
from ai_engine.services.recommendation_engine import RecommendationEngine

from accounts.models import User


# ============================================================
# ROLE-BASED DASHBOARD VIEW
# ============================================================

class RoleBasedDashboardView(LoginRequiredMixin, TemplateView):
    """
    Renders a unified dashboard route that tailors content
    and metrics according to the user's assigned role.
    """

    def get_template_names(self):
        user = self.request.user
        role_templates = {
            'SUPER_ADMIN': ['dashboard/index.html'],
            'SCHOOL_ADMIN': ['dashboard/index.html'],
            'BURSAR': ['dashboard/bursar_dashboard.html'],
            'REGISTRAR': ['dashboard/registrar_dashboard.html'],
            'HOD': ['dashboard/hod_dashboard.html'],
            'SECRETARY': ['dashboard/secretary_dashboard.html'],
            'TEACHER': ['dashboard/teacher_dashboard.html'],
            'PARENT': ['dashboard/parent_dashboard.html'],
            'STUDENT': ['dashboard/student_dashboard.html'],
        }
        return role_templates.get(user.role, ['dashboard/index.html'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        school = user.school

        context['user'] = user
        context['school'] = school
        context['user_role'] = user.role

        # Get role-specific context
        if user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'] and school:
            context.update(get_admin_dashboard_context(school))
        elif user.role == 'BURSAR' and school:
            context.update(get_bursar_dashboard_context(school))
        elif user.role == 'REGISTRAR' and school:
            context.update(get_registrar_dashboard_context(school))
        elif user.role == 'HOD' and school:
            context.update(get_hod_dashboard_context(user, school))
        elif user.role == 'SECRETARY' and school:
            context.update(get_secretary_dashboard_context(school))
        elif user.role == 'TEACHER':
            context.update(get_teacher_dashboard_context(user, school))
        elif user.role == 'PARENT':
            context.update(get_parent_dashboard_context(user, school))
        elif user.role == 'STUDENT':
            context.update(get_student_dashboard_context(user, school))

        return context


# ============================================================
# ADMIN DASHBOARD CONTEXT
# ============================================================

def get_admin_dashboard_context(school):
    """Get context data for admin dashboard."""
    today = localdate()

    # Recent Activities
    recent_activities = ActivityLog.objects.filter(school=school).order_by('-created_at')[:10]
    recent_ai_activity = AIActivity.objects.filter(school=school).select_related("created_by")[:10]

    # Students
    total_students = Student.objects.filter(school=school, is_active=True).count()

    # Finance KPIs
    total_billed = InvoiceLineItem.objects.filter(
        invoice__school=school
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_collected = Payment.objects.filter(
        invoice__school=school,
        status='CONFIRMED'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_receivables = total_billed - total_collected

    # Today's Attendance
    attendance = Attendance.objects.filter(school=school, date=today).aggregate(
        total=Count("id"),
        present=Count("id", filter=Q(status="PRESENT")),
    )

    total_marked = attendance["total"] or 0
    present = attendance["present"] or 0
    attendance_rate = round((present / total_marked) * 100, 1) if total_marked else 100

    # Attendance Trend (Last 5 Days)
    attendance_labels = []
    attendance_data = []
    for i in range(4, -1, -1):
        day = today - timedelta(days=i)
        attendance_labels.append(day.strftime('%a'))
        daily_att = Attendance.objects.filter(school=school, date=day).aggregate(
            total=Count("id"),
            present=Count("id", filter=Q(status="PRESENT")),
        )
        d_total = daily_att["total"] or 0
        d_present = daily_att["present"] or 0
        daily_rate = round((d_present / d_total) * 100, 1) if d_total > 0 else 0
        attendance_data.append(daily_rate)

    # Finance Chart Data
    chart_total_billed = InvoiceLineItem.objects.filter(
        invoice__school=school
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    chart_collected = Payment.objects.filter(
        invoice__school=school,
        status='CONFIRMED'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    chart_outstanding = chart_total_billed - chart_collected

    finance_chart_data = [
        float(chart_collected),
        float(chart_outstanding),
        float(chart_total_billed)
    ]

    # AI Metrics
    generated_exams = GeneratedExam.objects.filter(school=school).count()
    high_risk_students = StudentRiskAssessment.objects.filter(
        school=school,
        risk_band="HIGH"
    ).count()

    # AI Recommendations
    recommendations = RecommendationEngine.get_recommendations(school)

    return {
        "today": today,
        "total_students": total_students,
        "total_billed": total_billed,
        "total_collected": total_collected,
        "total_receivables": total_receivables,
        "attendance_rate": attendance_rate,
        "attendance_labels": attendance_labels,
        "attendance_data": attendance_data,
        "finance_chart_data": finance_chart_data,
        "generated_exams": generated_exams,
        "high_risk_students": high_risk_students,
        "recommendations": recommendations,
        "recent_ai_activity": recent_ai_activity,
        "recent_activities": recent_activities,
    }


# ============================================================
# TEACHER DASHBOARD CONTEXT
# ============================================================

def get_teacher_dashboard_context(user, school):
    """Get context data for teacher dashboard."""
    today = localdate()

    # Get teacher's classes
    try:
        teacher = user.teacher_profile
        from academics.models import TimetableEntry, SchoolClass
        homeroom_classes = teacher.homerooms.all()
        subject_classes = TimetableEntry.objects.filter(
            teacher=teacher,
            timetable__is_published=True
        ).values_list('school_class', flat=True).distinct()
        class_ids = list(homeroom_classes.values_list('id', flat=True)) + list(subject_classes)
        classes = SchoolClass.objects.filter(id__in=class_ids).distinct()
    except:
        classes = []

    # Get today's attendance for teacher's classes
    class_attendance = []
    total_students = 0
    total_present = 0
    total_marked = 0

    for cls in classes:
        students = Student.objects.filter(school=school, school_class=cls, is_active=True)
        student_count = students.count()
        attendance_today = Attendance.objects.filter(
            school=school,
            student__in=students,
            date=today
        )
        marked = attendance_today.count()
        present = attendance_today.filter(status='PRESENT').count()

        total_students += student_count
        total_marked += marked
        total_present += present

        class_attendance.append({
            'class': cls,
            'total_students': student_count,
            'marked': marked,
            'present': present,
            'rate': round((present / marked * 100), 1) if marked > 0 else 0
        })

    # Get recent student performance
    from assessments.models import Grade
    # FIXED: Use 'updated_at' instead of 'created_at'
    recent_grades = Grade.objects.filter(
        student__school=school,
        student__school_class__in=classes
    ).select_related('student__user', 'assessment').order_by('-updated_at')[:20]

    return {
        'today': today,
        'classes': classes,
        'class_attendance': class_attendance,
        'total_students': total_students,
        'total_present': total_present,
        'total_marked': total_marked,
        'attendance_rate': round((total_present / total_marked * 100), 1) if total_marked > 0 else 0,
        'recent_grades': recent_grades,
    }


# ============================================================
# PARENT DASHBOARD CONTEXT
# ============================================================

def get_parent_dashboard_context(user, school):
    """Get context data for parent dashboard."""
    # Get children of this parent
    children = Student.objects.filter(
        school=school,
        parent=user,
        is_active=True
    ).select_related('user', 'grade_level', 'school_class')

    child_data = []
    for child in children:
        # Get recent attendance (last 30 days)
        thirty_days_ago = localdate() - timedelta(days=30)
        attendance = Attendance.objects.filter(
            school=school,
            student=child,
            date__gte=thirty_days_ago
        )
        total = attendance.count()
        present = attendance.filter(status='PRESENT').count()

        # Get outstanding fees
        invoices = Invoice.objects.filter(school=school, student=child)
        total_billed = sum(inv.total_amount for inv in invoices) if invoices else Decimal('0.00')
        total_paid = sum(inv.amount_paid for inv in invoices) if invoices else Decimal('0.00')
        outstanding = total_billed - total_paid

        # Get recent grades
        from assessments.models import Grade
        # FIXED: Use 'updated_at' instead of 'created_at'
        recent_grades = Grade.objects.filter(
            student=child
        ).select_related('assessment').order_by('-updated_at')[:5]

        child_data.append({
            'student': child,
            'attendance_rate': round((present / total * 100), 1) if total > 0 else 0,
            'outstanding_fees': outstanding,
            'invoices': invoices[:5],
            'recent_grades': recent_grades,
        })

    return {
        'children': child_data,
        'total_children': len(child_data),
    }


# ============================================================
# BURSAR DASHBOARD CONTEXT
# ============================================================

def get_bursar_dashboard_context(school):
    """Get context data for bursar dashboard."""
    from finance.models import Invoice, InvoiceLineItem, Payment

    total_billed = InvoiceLineItem.objects.filter(
        invoice__school=school
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_collected = Payment.objects.filter(
        invoice__school=school,
        status='CONFIRMED'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_receivables = total_billed - total_collected

    recent_invoices = Invoice.objects.filter(school=school).order_by('-created_at')[:10]

    return {
        'total_billed': total_billed,
        'total_collected': total_collected,
        'total_receivables': total_receivables,
        'recent_invoices': recent_invoices,
    }


# ============================================================
# REGISTRAR DASHBOARD CONTEXT
# ============================================================

def get_registrar_dashboard_context(school):
    """Get context data for registrar dashboard."""
    from students.models import Student, GradeLevel

    total_students = Student.objects.filter(school=school).count()
    active_students = Student.objects.filter(school=school, is_active=True).count()
    grade_count = GradeLevel.objects.filter(school=school).count()
    recent_students = Student.objects.filter(school=school).order_by('-enrollment_date')[:10]

    return {
        'total_students': total_students,
        'active_students': active_students,
        'grade_count': grade_count,
        'recent_students': recent_students,
    }


# ============================================================
# HOD DASHBOARD CONTEXT
# ============================================================

def get_hod_dashboard_context(user, school):
    """Get context data for HOD dashboard."""
    from staff.models import Teacher
    from students.models import Student
    from ai_engine.models import GeneratedExam, StudentRiskAssessment

    # Get department from user's teacher profile
    try:
        teacher = user.teacher_profile
        department = teacher.department
        department_teachers = Teacher.objects.filter(school=school, department=department).count()
        department_students = 0
    except:
        department_teachers = 0
        department_students = 0

    generated_exams = GeneratedExam.objects.filter(school=school).count()
    high_risk_students = StudentRiskAssessment.objects.filter(
        school=school,
        risk_band="HIGH"
    ).count()
    recent_exams = GeneratedExam.objects.filter(school=school).order_by('-created_at')[:10]

    return {
        'department_teachers': department_teachers,
        'department_students': department_students,
        'generated_exams': generated_exams,
        'high_risk_students': high_risk_students,
        'recent_exams': recent_exams,
    }


# ============================================================
# SECRETARY DASHBOARD CONTEXT
# ============================================================

def get_secretary_dashboard_context(school):
    """Get context data for secretary dashboard."""
    from attendance.models import Attendance
    from finance.models import Invoice
    from library.models import Book
    from django.utils.timezone import localdate

    today = localdate()

    attendance = Attendance.objects.filter(school=school, date=today).aggregate(
        total=Count("id"),
        present=Count("id", filter=Q(status="PRESENT")),
    )
    total_marked = attendance["total"] or 0
    total_present = attendance["present"] or 0
    attendance_rate = round((total_present / total_marked) * 100, 1) if total_marked else 0

    outstanding_invoices = Invoice.objects.filter(school=school, status__in=['UNPAID', 'PARTIAL']).count()
    total_books = Book.objects.filter(school=school).count()

    recent_activities = ActivityLog.objects.filter(school=school).order_by('-created_at')[:10]

    return {
        'attendance_rate': attendance_rate,
        'total_present': total_present,
        'total_marked': total_marked,
        'outstanding_invoices': outstanding_invoices,
        'total_books': total_books,
        'recent_activities': recent_activities,
    }


# ============================================================
# STUDENT DASHBOARD CONTEXT
# ============================================================

def get_student_dashboard_context(user, school):
    """Get context data for student dashboard."""
    from assessments.models import Grade
    from academics.models import TimetableEntry

    try:
        student = Student.objects.select_related('grade_level', 'school_class').get(
            school=school, user=user
        )
    except Student.DoesNotExist:
        return {'student': None}

    # Attendance rate (last 30 days) -- same window as the parent dashboard
    thirty_days_ago = localdate() - timedelta(days=30)
    attendance_qs = Attendance.objects.filter(school=school, student=student, date__gte=thirty_days_ago)
    total_days = attendance_qs.count()
    present_days = attendance_qs.filter(status='PRESENT').count()
    attendance_rate = round((present_days / total_days * 100), 1) if total_days > 0 else 0

    # Outstanding fees
    invoices = Invoice.objects.filter(school=school, student=student)
    total_billed = sum(inv.total_amount for inv in invoices) if invoices else Decimal('0.00')
    total_paid = sum(inv.amount_paid for inv in invoices) if invoices else Decimal('0.00')
    outstanding = total_billed - total_paid

    # Recent grades
    recent_grades = Grade.objects.filter(
        student=student
    ).select_related('assessment').order_by('-updated_at')[:5]

    # This week's timetable, if the student's class has a published timetable
    todays_classes = []
    if student.school_class_id:
        todays_classes = list(
            TimetableEntry.objects.filter(
                school_class=student.school_class,
                timetable__is_published=True,
            ).select_related('subject', 'teacher', 'teacher__user', 'room', 'timeslot')
            .order_by('timeslot__day', 'timeslot__period_index')
        )

    return {
        'student': student,
        'attendance_rate': attendance_rate,
        'present_days': present_days,
        'total_days': total_days,
        'outstanding_fees': outstanding,
        'invoices': invoices[:5],
        'recent_grades': recent_grades,
        'todays_classes': todays_classes,
    }


# ============================================================
# LEGACY VIEWS (Keep for backward compatibility)
# ============================================================

@login_required
def admin_dashboard(request):
    """Legacy admin dashboard view."""
    if request.user.role == 'TEACHER':
        return redirect('dashboard:teacher_dashboard')
    elif request.user.role == 'PARENT':
        return redirect('dashboard:parent_dashboard')

    school = request.user.school
    context = get_admin_dashboard_context(school)
    context['user_role'] = request.user.role
    return render(request, 'dashboard/index.html', context)


@login_required
def teacher_dashboard(request):
    """Legacy teacher dashboard view."""
    school = request.user.school
    context = get_teacher_dashboard_context(request.user, school)
    return render(request, 'dashboard/teacher_dashboard.html', context)


@login_required
def parent_dashboard(request):
    """Legacy parent dashboard view."""
    school = request.user.school
    context = get_parent_dashboard_context(request.user, school)
    return render(request, 'dashboard/parent_dashboard.html', context)


# ============================================================
# EXPORT ALL FUNCTIONS
# ============================================================

__all__ = [
    'RoleBasedDashboardView',
    'get_admin_dashboard_context',
    'get_teacher_dashboard_context',
    'get_parent_dashboard_context',
    'get_bursar_dashboard_context',
    'get_registrar_dashboard_context',
    'get_hod_dashboard_context',
    'get_secretary_dashboard_context',
    'get_student_dashboard_context',
    'admin_dashboard',
    'teacher_dashboard',
    'parent_dashboard',
]