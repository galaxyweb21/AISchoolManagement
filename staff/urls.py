# staff/urls.py
from django.urls import path
from . import views

app_name = 'staff'

urlpatterns = [
    # ==========================================================
    # STAFF MANAGEMENT
    # ==========================================================
    path('', views.staff_list, name='staff_list'),
    path('create/', views.staff_create, name='staff_create'),
    path('<uuid:staff_id>/', views.staff_detail, name='staff_detail'),
    path('<uuid:staff_id>/edit/', views.staff_edit, name='staff_edit'),
    path('<uuid:staff_id>/delete/', views.staff_delete, name='staff_delete'),
    path('<uuid:staff_id>/toggle-active/', views.toggle_staff_active, name='toggle_staff_active'),

    # ==========================================================
    # DEPARTMENT MANAGEMENT
    # ==========================================================
    path('departments/', views.department_list, name='department_list'),
    path('departments/create/', views.department_create, name='department_create'),
    path('departments/<uuid:department_id>/edit/', views.department_edit, name='department_edit'),
    path('departments/<uuid:department_id>/delete/', views.department_delete, name='department_delete'),

    # ==========================================================
    # STAFF GRADES
    # ==========================================================
    path('grades/', views.staff_grade_list, name='staff_grade_list'),
    path('grades/create/', views.staff_grade_create, name='staff_grade_create'),
    path('grades/<uuid:grade_id>/edit/', views.staff_grade_edit, name='staff_grade_edit'),
    path('grades/<uuid:grade_id>/delete/', views.staff_grade_delete, name='staff_grade_delete'),

    # ==========================================================
    # TEACHER ASSIGNMENTS
    # ==========================================================
    path('assignments/', views.teacher_assignment_list, name='teacher_assignment_list'),
    path('assignments/class/<uuid:class_id>/', views.teacher_assignment_class_view,
         name='teacher_assignment_class_view'),
    path('assignments/class/<uuid:class_id>/assign-class-teacher/', views.class_teacher_assign,
         name='class_teacher_assign'),
    path('assignments/create/', views.teacher_assignment_create, name='teacher_assignment_create'),
    path('assignments/bulk-create/', views.teacher_assignment_bulk_create, name='teacher_assignment_bulk_create'),
    path('assignments/<uuid:assignment_id>/edit/', views.teacher_assignment_edit, name='teacher_assignment_edit'),
    path('assignments/<uuid:assignment_id>/delete/', views.teacher_assignment_delete, name='teacher_assignment_delete'),

    # ==========================================================
    # SALARY STRUCTURES
    # ==========================================================
    path("salary-structures/", views.salary_structure_list, name="salary_structure_list", ),
    path("salary-structures/create/", views.salary_structure_create, name="salary_structure_create", ),
    path("salary-structures/<int:structure_id>/edit/", views.salary_structure_edit, name="salary_structure_edit", ),
    path("salary-structures/<int:structure_id>/delete/", views.salary_structure_delete,
         name="salary_structure_delete", ),

    # ==========================================================
    # ALLOWANCES
    # ==========================================================

    # Allowance definitions
    path(
        'allowances/',
        views.allowance_list,
        name='allowance_list'
    ),

    path(
        'allowances/create/',
        views.allowance_create,
        name='allowance_create'
    ),

    path(
        'allowances/<uuid:allowance_id>/edit/',
        views.allowance_edit,
        name='allowance_edit'
    ),

    path(
        'allowances/<uuid:allowance_id>/delete/',
        views.allowance_delete,
        name='allowance_delete'
    ),

    # ==========================================================
    # STAFF ALLOWANCE ASSIGNMENTS
    # ==========================================================

    path(
        'staff-allowances/',
        views.staff_allowance_list,
        name='staff_allowance_list'
    ),

    path(
        'staff-allowances/create/',
        views.staff_allowance_create,
        name='staff_allowance_create'
    ),

    path(
        'staff-allowances/<uuid:staff_allowance_id>/edit/',
        views.staff_allowance_edit,
        name='staff_allowance_edit'
    ),

    path(
        'staff-allowances/<uuid:staff_allowance_id>/delete/',
        views.staff_allowance_delete,
        name='staff_allowance_delete'
    ),

    path(
        'staff-allowances/<uuid:staff_allowance_id>/toggle-active/',
        views.staff_allowance_toggle_active,
        name='staff_allowance_toggle_active'
    ),

    # Staff-specific allowance management
    path(
        '<uuid:staff_id>/allowances/',
        views.staff_allowance_staff_list,
        name='staff_allowance_staff_list'
    ),

    path(
        '<uuid:staff_id>/allowances/create/',
        views.staff_allowance_staff_create,
        name='staff_allowance_staff_create'
    ),


    # ==========================================================
    # DEDUCTIONS
    # ==========================================================
    path('deductions/', views.deduction_list, name='deduction_list'),
    path('deductions/create/', views.deduction_create, name='deduction_create'),
    path('deductions/<uuid:deduction_id>/edit/', views.deduction_edit, name='deduction_edit'),
    path('deductions/<uuid:deduction_id>/delete/', views.deduction_delete, name='deduction_delete'),

    # ==========================================================
    # PAYROLL
    # ==========================================================
    path('payroll/', views.payroll_dashboard, name='payroll_dashboard'),
    path('payroll/periods/', views.payroll_period_list, name='payroll_period_list'),
    path('payroll/periods/create/', views.payroll_period_create, name='payroll_period_create'),
    path('payroll/periods/<uuid:period_id>/', views.payroll_period_detail, name='payroll_period_detail'),
    path('payroll/periods/<uuid:period_id>/process/', views.process_payroll, name='process_payroll'),
    path('payroll/periods/<uuid:period_id>/approve/', views.approve_payroll, name='approve_payroll'),
    path('payroll/periods/<uuid:period_id>/close/', views.close_payroll, name='close_payroll'),

    # ==========================================================
    # PAYSLIPS
    # ==========================================================
    path('payslips/', views.payslip_list, name='payslip_list'),
    path('payslips/<uuid:payslip_id>/', views.payslip_detail, name='payslip_detail'),
    path('payslips/<uuid:payslip_id>/download/', views.download_payslip, name='download_payslip'),

    # ==========================================================
    # PAYSLIP GENERATION - NEW (FIXED)
    # ==========================================================
    path('payslips/<uuid:payslip_id>/generate/', views.generate_payslip, name='generate_payslip'),
    path('payroll/periods/<uuid:period_id>/generate-payslips/', views.generate_bulk_payslips,
         name='generate_bulk_payslips'),
    path('payroll/periods/<uuid:period_id>/print-payslips/', views.bulk_print_payslips, name='bulk_print_payslips'),

    # ==========================================================
    # PAYSLIP GENERATION - Alternative for when no payslip exists
    # ==========================================================
    path('payroll/run/<uuid:run_id>/generate-payslip/', views.generate_payslip_from_run, name='generate_payslip_from_run'),

    # ==========================================================
    # LEAVE MANAGEMENT - Enhanced
    # ==========================================================
    # Dashboard & Overview
    path('leaves/dashboard/', views.leave_dashboard, name='leave_dashboard'),
    path('leaves/', views.leave_list, name='leave_list'),
    path('leaves/balance/', views.leave_balance, name='leave_balance'),
    path('leaves/calendar/', views.leave_calendar, name='leave_calendar'),
    path('leaves/analytics/', views.leave_analytics, name='leave_analytics'),
    path('leaves/ledger/', views.leave_ledger, name='leave_ledger'),
    path('leaves/ledger/<uuid:staff_id>/', views.leave_ledger, name='leave_ledger_staff'),

    # Leave Requests
    path('leaves/create/', views.leave_request_create, name='leave_request_create'),
    path('leaves/<uuid:leave_id>/', views.leave_detail, name='leave_detail'),
    path('leaves/<uuid:leave_id>/edit/', views.leave_request_edit, name='leave_request_edit'),
    path('leaves/<uuid:leave_id>/approve/', views.leave_approve, name='leave_approve'),
    path('leaves/<uuid:leave_id>/reject/', views.leave_reject, name='leave_reject'),
    path('leaves/<uuid:leave_id>/cancel/', views.leave_cancel, name='leave_cancel'),

    # Leave Types (Admin only)
    path('leave-types/', views.leave_type_list, name='leave_type_list'),
    path('leave-types/create/', views.leave_type_create, name='leave_type_create'),
    path('leave-types/<uuid:leave_type_id>/edit/', views.leave_type_edit, name='leave_type_edit'),
    path('leave-types/<uuid:leave_type_id>/toggle-active/', views.leave_type_toggle_active,
         name='leave_type_toggle_active'),

    # Grade Leave Policies (Admin only)
    path('leave-types/grade-policies/', views.leave_type_grade_policies, name='leave_type_grade_policies'),
    path('leave-types/grade-policy/save/', views.leave_type_grade_policy_save, name='leave_type_grade_policy_save'),

    # ==========================================================
    # API ENDPOINTS
    # ==========================================================
    path('api/password-changed/', views.staff_mark_password_changed, name='staff_mark_password_changed'),
    path('api/staff-credentials/<uuid:staff_id>/', views.staff_get_credentials, name='staff_get_credentials'),
]