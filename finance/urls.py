# finance/urls.py
from django.urls import path
from . import views

from .views import (
    # Dashboard & Payments
    billing_dashboard,
    api_record_payment,

    # Fee Categories
    fee_category_list,
    fee_category_create,
    fee_category_edit,
    fee_category_delete,

    # Fee Structures
    fee_structure_list,
    fee_structure_create,
    fee_structure_edit,
    fee_structure_delete,
    fee_structure_detail,
    fee_schedule_view,
    fee_schedule_pdf,

    # Fee Preparation
    fee_preparation,
    api_prepare_class_fees,
    api_student_fee_detail,
    api_student_fee_approve,

    # Student Fees List
    student_fees_list_view,
    api_student_fee_bulk_approve,

    # Fee Waivers
    waiver_list,
    waiver_create,
    waiver_edit,
    waiver_delete,

    # Invoices
    invoice_list,
    invoice_detail,
    api_generate_invoices,

    # Fee Statements
    invoice_statement_view,
    invoice_statement_pdf,
    api_email_invoice_statement,
    api_bulk_invoice_statements_pdf,
    api_bulk_email_invoice_statements,

    # Student Financial Account
    student_financial_account,
    api_student_balance,

    # Payment Modal
    payment_modal,  # <-- ADD THIS

    # Payment Receipts
    payment_receipt_view,
    payment_receipt_pdf,
    api_resend_receipt,
    api_email_receipt,
)

app_name = 'finance'

urlpatterns = [
    # Dashboard
    path('billing/', billing_dashboard, name='billing_dashboard'),

    # Payments
    path('api/pay/', api_record_payment, name='api_record_payment'),

    # Payment Modal
    path('api/payment-modal/', payment_modal, name='payment_modal'),

    # Payment Receipts
    path('receipts/<uuid:payment_id>/', payment_receipt_view, name='payment_receipt'),
    path('receipts/<uuid:payment_id>/pdf/', payment_receipt_pdf, name='payment_receipt_pdf'),
    path('api/receipts/<uuid:payment_id>/resend/', api_resend_receipt, name='api_resend_receipt'),
    path('api/receipts/<uuid:payment_id>/email/', api_email_receipt, name='api_email_receipt'),

    # Fee Preparation
    path('fee-preparation/', fee_preparation, name='fee_preparation'),
    path('api/prepare-class-fees/', api_prepare_class_fees, name='api_prepare_class_fees'),
    path('api/student-fee/<uuid:student_fee_id>/', api_student_fee_detail, name='api_student_fee_detail'),
    path('api/student-fee/<uuid:student_fee_id>/approve/', api_student_fee_approve, name='api_student_fee_approve'),

    # Backfill ledger entries
    path('api/backfill-ledger/', views.api_backfill_ledger_entries, name='api_backfill_ledger'),

    # Student Fees List
    path('student-fees/', student_fees_list_view, name='student_fees_list'),
    path('api/student-fees/bulk-approve/', api_student_fee_bulk_approve, name='api_student_fee_bulk_approve'),

    # Fee Waivers
    path('waivers/', waiver_list, name='waiver_list'),
    path('waivers/create/', waiver_create, name='waiver_create'),
    path('waivers/<uuid:waiver_id>/edit/', waiver_edit, name='waiver_edit'),
    path('waivers/<uuid:waiver_id>/delete/', waiver_delete, name='waiver_delete'),

    # Invoices
    path('invoices/', invoice_list, name='invoice_list'),
    path('invoices/<uuid:invoice_id>/', invoice_detail, name='invoice_detail'),
    path('api/generate-invoices/', api_generate_invoices, name='api_generate_invoices'),

    # Fee Statements
    path('invoices/<uuid:invoice_id>/statement/', invoice_statement_view, name='invoice_statement'),
    path('invoices/<uuid:invoice_id>/statement/pdf/', invoice_statement_pdf, name='invoice_statement_pdf'),
    path('api/invoices/<uuid:invoice_id>/statement/email/', api_email_invoice_statement, name='api_email_invoice_statement'),
    path('api/invoices/statements/bulk-pdf/', api_bulk_invoice_statements_pdf, name='api_bulk_invoice_statements_pdf'),
    path('api/invoices/statements/bulk-email/', api_bulk_email_invoice_statements, name='api_bulk_email_invoice_statements'),

    # Fee Categories
    path('fee-categories/', fee_category_list, name='fee_category_list'),
    path('fee-categories/create/', fee_category_create, name='fee_category_create'),
    path('fee-categories/<uuid:category_id>/edit/', fee_category_edit, name='fee_category_edit'),
    path('fee-categories/<uuid:category_id>/delete/', fee_category_delete, name='fee_category_delete'),

    # Fee Structures
    path('fee-structures/', fee_structure_list, name='fee_structure_list'),
    path('fee-structures/create/', fee_structure_create, name='fee_structure_create'),
    path('fee-structures/<uuid:structure_id>/edit/', fee_structure_edit, name='fee_structure_edit'),
    path('fee-structures/<uuid:structure_id>/delete/', fee_structure_delete, name='fee_structure_delete'),
    path('fee-structures/<uuid:structure_id>/', fee_structure_detail, name='fee_structure_detail'),
    path('fee-structures/<uuid:structure_id>/schedule/', fee_schedule_view, name='fee_schedule'),
    path('fee-structures/<uuid:structure_id>/schedule/pdf/', fee_schedule_pdf, name='fee_schedule_pdf'),

    # Student Financial Account
    path('student/<uuid:student_id>/account/', student_financial_account, name='student_financial_account'),
    path('api/student/<uuid:student_id>/balance/', api_student_balance, name='api_student_balance'),

    # Fee Add-ons
    path('fee-addons/', views.fee_addon_list, name='fee_addon_list'),
    path('fee-addons/create/', views.fee_addon_create, name='fee_addon_create'),
    path('fee-addons/<uuid:addon_id>/edit/', views.fee_addon_edit, name='fee_addon_edit'),
    path('fee-addons/<uuid:addon_id>/delete/', views.fee_addon_delete, name='fee_addon_delete'),

    # Student Fee Adjustments
    path('student-fee/<uuid:student_fee_id>/adjustments/', views.student_fee_adjustments,
         name='student_fee_adjustments'),
    path('api/student-fee/<uuid:student_fee_id>/adjustment/create/', views.api_student_fee_adjustment_create,
         name='api_student_fee_adjustment_create'),
    path('api/student-fee-adjustment/<uuid:adjustment_id>/delete/', views.api_student_fee_adjustment_delete,
         name='api_student_fee_adjustment_delete'),

    path('api/fee-preview/', views.api_fee_preview, name='api_fee_preview'),

    path('api/rebuild-class-fees/', views.api_rebuild_class_fees, name='api_rebuild_class_fees'),

    path('api/rebuild-all-fees/', views.api_rebuild_all_fees, name='api_rebuild_all_fees'),

    path('class-addons/', views.class_addon_list, name='class_addon_list'),
    path('class-addons/create/', views.class_addon_create, name='class_addon_create'),
    # Editing/deleting is keyed by school class, not by a single add-on,
    # since one class can have several add-on items (each with its own
    # ClassAddOnStructure). See class_addon_edit/class_addon_delete.
    path('class-addons/class/<uuid:class_id>/edit/', views.class_addon_edit, name='class_addon_edit'),
    path('class-addons/class/<uuid:class_id>/delete/', views.class_addon_delete, name='class_addon_delete'),
]