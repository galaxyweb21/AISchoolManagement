from core.pagination import paginate_queryset
# finance/views.py
import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum, Count

from django.db import models
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone

from students.models import Student, GradeLevel  # <-- ADD GradeLevel here
from academics.models import SchoolClass
from school.models import AcademicTerm

from .models import (
    FeeCategory,
    FeeStructure,
    FeeStructureItem,
    FeeWaiver,
    Invoice,
    InvoiceLineItem,
    Payment,
    StudentFinancialLedger,
    StudentFee,
    StudentFeeItem,
    FeeAddOnStructure,
    FeeAddOnItem,
    StudentFeeAdjustment,
    ClassAddOnStructure,   # <-- ADD THIS
    ClassAddOnItem,        # <-- ADD THIS
    EnrollmentFeePackage,  # <-- ADD THIS
    StudentFeeEnrollment,  # <-- ADD THIS
)

from .services.ledger import (
    create_invoice_ledger_entries,
    create_payment_ledger_entry,
    get_student_previous_balance,
    create_arrears_entry,
    get_student_balance,
)

from .services.fee_preparation import (
    prepare_class_fees,
    prepare_student_fee,
    FeePreparationError,
    get_applicable_class_addons,
)

from ai_engine.services.events import AIEvents
from .services.fee_preparation import create_student_fee_ledger_entry
from .services.auto_invoicing import ensure_student_term_invoice

# ============================================================================
# CONSTANTS
# ============================================================================

ZERO = Decimal("0.00")
MANAGER_ROLES = [
    'SUPER_ADMIN',
    'SCHOOL_ADMIN',
    'BURSAR',
]

# ============================================================================
# HELPERS
# ============================================================================

def user_can_manage_finance(user):
    """Centralized finance permission check."""
    return getattr(user, 'role', None) in MANAGER_ROLES


def decimal_from_value(value, default=Decimal('0.00')):
    """Safely convert a value to Decimal."""
    if value in (None, ''):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def json_error(message, status=400):
    """Standard JSON error response."""
    return JsonResponse(
        {'success': False, 'error': message},
        status=status,
    )


def permission_denied_response(request, redirect_name):
    """Return JSON for AJAX requests or redirect for normal requests."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return json_error('Permission denied.', status=403)
    messages.error(request, 'Permission denied.')
    return redirect(redirect_name)



# ============================================================================
# BILLING DASHBOARD - FIXED
# ============================================================================

# finance/views.py - Replace billing_dashboard with this fixed version

@login_required
def billing_dashboard(request):
    """Main finance/billing dashboard."""
    school = request.user.school

    # Get all invoices for the school
    invoices = (
        Invoice.objects
        .filter(school=school)
        .select_related('student', 'student__user', 'academic_term')
        .prefetch_related('line_items', 'payments')
        .order_by('-due_date', '-created_at')
    )

    # ==========================================================
    # FIXED: Calculate totals directly from Invoice model
    # ==========================================================

    # Total Billed = sum of total_amount from all invoices
    total_billed = Decimal('0.00')
    for invoice in invoices:
        total_billed += invoice.total_amount

    # Total Collected = sum of amount_paid from all invoices
    total_collected = Decimal('0.00')
    for invoice in invoices:
        total_collected += invoice.amount_paid

    total_receivables = total_billed - total_collected

    # ==========================================================
    # FIXED: Status breakdown
    # ==========================================================

    # Get invoices by status
    unpaid_invoices = Invoice.objects.filter(school=school, status='UNPAID')
    partial_invoices = Invoice.objects.filter(school=school, status='PARTIAL')
    paid_invoices = Invoice.objects.filter(school=school, status='PAID')

    # Calculate totals for each status
    unpaid_total = Decimal('0.00')
    partial_total = Decimal('0.00')
    paid_total = Decimal('0.00')

    for invoice in unpaid_invoices:
        unpaid_total += invoice.total_amount

    for invoice in partial_invoices:
        partial_total += invoice.total_amount

    for invoice in paid_invoices:
        paid_total += invoice.total_amount

    invoice_counts = {
        'unpaid': unpaid_invoices.count(),
        'partial': partial_invoices.count(),
        'paid': paid_invoices.count(),
        'total': invoices.count(),
    }

    # Calculate collection rate
    if total_billed > 0:
        collection_rate = (total_collected / total_billed) * 100
    else:
        collection_rate = 0

    context = {
        'invoices': invoices,
        'total_billed': total_billed,
        'total_collected': total_collected,
        'total_receivables': total_receivables,
        'unpaid_total': unpaid_total,
        'partial_total': partial_total,
        'paid_total': paid_total,
        'invoice_counts': invoice_counts,
        'collection_rate': collection_rate,
        'can_manage': user_can_manage_finance(request.user),
    }

    return render(request, 'finance/billing_dashboard.html', context)


# ============================================================================
# PAYMENT RECORDING
# ============================================================================

# finance/views.py - Complete rewrite of api_record_payment

# finance/views.py - Complete rewrite of api_record_payment

@login_required
@require_POST
def api_record_payment(request):
    """Record a payment against one or more invoices."""
    if not user_can_manage_finance(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    try:
        data = json.loads(request.body or '{}')
        invoice_ids = data.get('invoice_ids', [])

        # Handle single invoice_id for backward compatibility
        if not invoice_ids and data.get('invoice_id'):
            invoice_ids = [data.get('invoice_id')]

        payment_amount = decimal_from_value(data.get('amount'))
        method = data.get('method', 'CASH')
        reference_number = data.get('reference_number', '').strip()
        notes = data.get('notes', '').strip()

        if not invoice_ids:
            return JsonResponse({'success': False, 'error': 'At least one invoice is required.'}, status=400)

        if payment_amount <= Decimal('0.00'):
            return JsonResponse({'success': False, 'error': 'Payment amount must be greater than zero.'}, status=400)

        if method not in dict(Payment.METHOD_CHOICES):
            return JsonResponse({'success': False, 'error': 'Invalid payment method.'}, status=400)

        school = request.user.school
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Processing payment: amount={payment_amount}, method={method}, invoices={invoice_ids}")

        with transaction.atomic():
            # Get all invoices
            invoices = Invoice.objects.filter(
                id__in=invoice_ids,
                school=school
            ).exclude(status='VOID').select_for_update()

            if not invoices.exists():
                return JsonResponse({'success': False, 'error': 'No valid invoices found.'}, status=404)

            # Calculate total outstanding
            total_outstanding = Decimal('0.00')
            invoice_balances = {}

            for invoice in invoices:
                # Calculate balance directly from line items and payments
                total_amount = invoice.line_items.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                amount_paid = invoice.payments.filter(status='CONFIRMED').aggregate(total=Sum('amount'))[
                                  'total'] or Decimal('0.00')
                balance = total_amount - amount_paid
                invoice_balances[invoice.id] = {
                    'total': total_amount,
                    'paid': amount_paid,
                    'balance': balance
                }
                if balance > 0:
                    total_outstanding += balance

            logger.info(f"Total outstanding: {total_outstanding}")

            if total_outstanding <= Decimal('0.00'):
                return JsonResponse({'success': False, 'error': 'All selected invoices are already paid.'}, status=400)

            if payment_amount > total_outstanding:
                return JsonResponse({
                    'success': False,
                    'error': f'Payment amount (GH¢ {payment_amount:.2f}) exceeds total outstanding (GH¢ {total_outstanding:.2f})'
                }, status=400)

            # Distribute payment across invoices (oldest first)
            remaining = payment_amount
            payments = []
            total_paid = Decimal('0.00')
            updated_invoices = []

            # Sort invoices by due date (oldest first)
            sorted_invoices = invoices.order_by('due_date', 'created_at')

            for invoice in sorted_invoices:
                if remaining <= Decimal('0.00'):
                    break

                balance = invoice_balances[invoice.id]['balance']
                if balance <= Decimal('0.00'):
                    continue

                # Amount to allocate to this invoice
                allocated = min(remaining, balance)

                # Create payment
                payment = Payment.objects.create(
                    invoice=invoice,
                    amount=allocated,
                    method=method,
                    reference_number=reference_number or '',
                    recorded_by=request.user,
                    status='CONFIRMED',
                    notes=notes or '',
                )

                payments.append(payment)
                total_paid += allocated
                remaining -= allocated

                # Update invoice balance and status
                new_total = invoice_balances[invoice.id]['total']
                new_paid = invoice_balances[invoice.id]['paid'] + allocated
                new_balance = new_total - new_paid

                # Update status based on new balance
                if new_balance <= Decimal('0.00'):
                    invoice.status = 'PAID'
                elif new_paid > Decimal('0.00'):
                    invoice.status = 'PARTIAL'
                else:
                    invoice.status = 'UNPAID'
                invoice.save(update_fields=['status'])

                updated_invoices.append({
                    'id': str(invoice.id),
                    'number': invoice.invoice_number,
                    'new_status': invoice.status,
                    'new_paid': new_paid,
                    'new_balance': new_balance
                })

                # Create ledger entry
                try:
                    from .services.ledger import create_payment_ledger_entry
                    create_payment_ledger_entry(payment, created_by=request.user)
                except Exception as ledger_error:
                    logger.error(f"Error creating ledger entry for payment {payment.id}: {ledger_error}")

                logger.info(
                    f"Payment allocated to invoice {invoice.invoice_number}: {allocated}, new status: {invoice.status}")

            # If there's remaining amount, log it
            if remaining > Decimal('0.00'):
                logger.info(f"Remaining amount {remaining} after payment distribution")

        # Email the PDF receipt + text a confirmation to the parent for each
        # payment just created. Fired on a background thread (see
        # send_receipt_notifications_async) so a slow/misconfigured email or
        # SMS provider never delays this response -- and wrapped here too so
        # a failure to even queue it can't affect a payment that has already
        # been saved and deducted from the balance.
        try:
            from .services.receipts import send_receipt_notifications_async
            for p in payments:
                send_receipt_notifications_async(p)
        except Exception as exc:
            logger.error(f"Could not queue receipt notifications: {exc}")

        # Prepare response.
        # NOTE: don't call invoices.first() here — `invoices` has
        # select_for_update() applied, and by this point we're outside the
        # `with transaction.atomic():` block above. Evaluating a
        # select_for_update() queryset outside a transaction raises
        # TransactionManagementError, which was crashing every payment
        # with a 500 *after* it had already been saved and deducted from
        # the balance. Use the per-invoice data already collected inside
        # the transaction instead.
        first_updated = updated_invoices[0] if updated_invoices else None
        response_data = {
            'success': True,
            'message': f'Payment of GH¢ {total_paid:.2f} recorded successfully across {len(payments)} invoice(s).',
            'payment_id': str(payments[0].id) if payments else None,
            'receipt_number': payments[0].receipt_number if payments else None,
            'total_paid': str(total_paid),
            'invoices_affected': len(payments),
            'remaining_balance': str(total_outstanding - total_paid),
            'updated_invoices': updated_invoices,
        }

        if payments:
            response_data['receipt_url'] = reverse('finance:payment_receipt', args=[payments[0].id])
            response_data['receipt_pdf_url'] = reverse('finance:payment_receipt_pdf', args=[payments[0].id])

        if first_updated:
            response_data['new_status'] = first_updated['new_status']
            response_data['new_amount_paid'] = str(first_updated['new_paid'])
            response_data['new_balance'] = str(first_updated['new_balance'])

        logger.info(f"Payment successful: {response_data}")
        return JsonResponse(response_data)

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON request.'}, status=400)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Payment error: {exc}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


# ============================================================================
# PAYMENT RECEIPTS
# ============================================================================

@login_required
def payment_receipt_view(request, payment_id):
    """Printable/viewable HTML payment receipt, with Print / Download PDF / Resend actions."""
    school = request.user.school
    payment = get_object_or_404(
        Payment.objects.select_related(
            'invoice', 'invoice__student__user', 'invoice__student__school_class',
            'invoice__school', 'invoice__academic_term', 'recorded_by',
        ),
        id=payment_id,
        invoice__school=school,
    )

    from .services.receipts import build_receipt_context
    context = build_receipt_context(payment)
    context['is_pdf'] = False
    context['can_manage'] = user_can_manage_finance(request.user)

    return render(request, 'finance/receipt.html', context)


@login_required
def payment_receipt_pdf(request, payment_id):
    """Download (or view inline with ?inline=1) the payment receipt as a PDF."""
    school = request.user.school
    payment = get_object_or_404(
        Payment.objects.select_related('invoice', 'invoice__student__user', 'invoice__school'),
        id=payment_id,
        invoice__school=school,
    )

    from .services.receipts import generate_receipt_pdf
    pdf_bytes = generate_receipt_pdf(payment)
    if not pdf_bytes:
        return HttpResponse(
            'Could not generate the receipt PDF right now. Please try again, or contact support.',
            status=500,
        )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="Receipt-{payment.receipt_number}.pdf"'
    return response


@login_required
@require_POST
def api_resend_receipt(request, payment_id):
    """Re-send the receipt (email with PDF attached + SMS) to the parent on demand."""
    if not user_can_manage_finance(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    school = request.user.school
    payment = get_object_or_404(
        Payment.objects.select_related('invoice', 'invoice__student__user', 'invoice__school'),
        id=payment_id,
        invoice__school=school,
    )

    from .services.receipts import send_receipt_notifications
    result = send_receipt_notifications(payment)

    if not result['email_sent'] and not result['sms_sent']:
        return JsonResponse({
            'success': False,
            'error': result.get('reason') or "Could not send the receipt via email or SMS.",
        }, status=400)

    parts = []
    if result['email_sent']:
        parts.append('email')
    if result['sms_sent']:
        parts.append('SMS')

    return JsonResponse({
        'success': True,
        'email_sent': result['email_sent'],
        'sms_sent': result['sms_sent'],
        'message': f"Receipt sent via {' & '.join(parts)}.",
    })


@login_required
@require_POST
def api_email_receipt(request, payment_id):
    """Re-send just the receipt email (PDF attached) to the parent on demand -- no SMS."""
    if not user_can_manage_finance(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    school = request.user.school
    payment = get_object_or_404(
        Payment.objects.select_related('invoice', 'invoice__student__user', 'invoice__school'),
        id=payment_id,
        invoice__school=school,
    )

    from .services.receipts import send_receipt_notifications
    result = send_receipt_notifications(payment, send_email=True, send_sms=False)

    if not result['email_sent']:
        return JsonResponse({
            'success': False,
            'error': result.get('reason') or "Could not send the receipt via email.",
        }, status=400)

    return JsonResponse({
        'success': True,
        'email_sent': True,
        'message': "Receipt emailed to parent.",
    })


# ============================================================================
# FEE CATEGORY MANAGEMENT
# ============================================================================

@login_required
def fee_category_list(request):
    """List all fee categories belonging to the current school."""
    school = request.user.school
    categories = (
        FeeCategory.objects
            .filter(school=school)
            .order_by('category_type', 'name')
    )

    return render(request, 'finance/fee_category_list.html', {
        'categories': paginate_queryset(categories, request),
        'can_manage': user_can_manage_finance(request.user),
    })


@login_required
@require_http_methods(["GET", "POST"])
def fee_category_create(request):
    """Create a fee category."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:fee_category_list')

    school = request.user.school

    if request.method == 'GET':
        return render(request, 'finance/fee_category_form_modal.html', {
            'mode': 'create',
            'category': None,
            'action_url': 'finance:fee_category_create',
            'type_choices': FeeCategory.TYPE_CHOICES,
        })

    try:
        name = request.POST.get('name', '').strip()
        category_type = request.POST.get('category_type', 'OTHER')
        is_recurring = request.POST.get('is_recurring') == 'on'
        is_optional = request.POST.get('is_optional') == 'on'
        description = request.POST.get('description', '').strip()

        if not name:
            return json_error('Category name is required.')

        if category_type not in dict(FeeCategory.TYPE_CHOICES):
            return json_error('Invalid fee category type.')

        if FeeCategory.objects.filter(school=school, name__iexact=name).exists():
            return json_error(f"A fee category named '{name}' already exists.")

        FeeCategory.objects.create(
            school=school,
            name=name,
            category_type=category_type,
            is_recurring=is_recurring,
            is_optional=is_optional,
            description=description,
        )

        return JsonResponse({
            'success': True,
            'message': f"Category '{name}' created successfully.",
        })

    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def fee_category_edit(request, category_id):
    """Edit a fee category."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:fee_category_list')

    school = request.user.school
    category = get_object_or_404(FeeCategory, id=category_id, school=school)

    if request.method == 'GET':
        return render(request, 'finance/fee_category_form_modal.html', {
            'mode': 'edit',
            'category': category,
            'action_url': 'finance:fee_category_edit',
            'type_choices': FeeCategory.TYPE_CHOICES,
        })

    try:
        name = request.POST.get('name', '').strip()
        category_type = request.POST.get('category_type', 'OTHER')
        is_recurring = request.POST.get('is_recurring') == 'on'
        is_optional = request.POST.get('is_optional') == 'on'
        description = request.POST.get('description', '').strip()

        if not name:
            return json_error('Category name is required.')

        if category_type not in dict(FeeCategory.TYPE_CHOICES):
            return json_error('Invalid fee category type.')

        if FeeCategory.objects.filter(school=school, name__iexact=name).exclude(id=category.id).exists():
            return json_error(f"A fee category named '{name}' already exists.")

        category.name = name
        category.category_type = category_type
        category.is_recurring = is_recurring
        category.is_optional = is_optional
        category.description = description
        category.save()

        return JsonResponse({
            'success': True,
            'message': f"Category '{name}' updated successfully.",
        })

    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def fee_category_delete(request, category_id):
    """Delete a fee category."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:fee_category_list')

    school = request.user.school
    category = get_object_or_404(FeeCategory, id=category_id, school=school)

    if request.method == 'GET':
        return render(request, 'finance/fee_category_delete_modal.html', {
            'category': category,
            'action_url': 'finance:fee_category_delete',
        })

    try:
        category_name = category.name
        category.delete()
        return JsonResponse({
            'success': True,
            'message': f"Category '{category_name}' deleted successfully.",
        })

    except IntegrityError:
        return json_error(
            'Cannot delete this category because it is associated with existing fee structures or invoices.'
        )
    except Exception as exc:
        return json_error(str(exc), status=500)


# ============================================================================
# FEE STRUCTURE MANAGEMENT
# ============================================================================

@login_required
def fee_structure_list(request):
    """List fee structures for the current school."""
    school = request.user.school

    structures = (
        FeeStructure.objects
            .filter(school=school)
            .select_related('academic_term', 'school_class', 'school_class__grade_level')
            .prefetch_related('items__fee_category')
            .order_by('-academic_term__start_date', 'school_class__grade_level__order', 'school_class__name')
    )

    return render(request, 'finance/fee_structure_list.html', {
        'structures': paginate_queryset(structures, request),
        'can_manage': user_can_manage_finance(request.user),
    })


@login_required
@require_http_methods(["GET", "POST"])
def fee_structure_create(request):
    """Create a fee structure for a school class and term."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:fee_structure_list')

    school = request.user.school

    if request.method == 'GET':
        school_classes = SchoolClass.objects.filter(school=school).select_related('grade_level').order_by(
            'grade_level__order', 'name')
        terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')
        fee_categories = FeeCategory.objects.filter(school=school, is_active=True).order_by('name')

        return render(request, 'finance/fee_structure_form_modal.html', {
            'mode': 'create',
            'structure': None,
            'school_classes': school_classes,
            'terms': terms,
            'fee_categories': fee_categories,
            'existing_items': [],
            'action_url': 'finance:fee_structure_create',
        })

    try:
        term_id = request.POST.get('academic_term')
        school_class_id = request.POST.get('school_class')
        category_ids = request.POST.getlist('categories')
        amounts = request.POST.getlist('amounts')

        if not term_id or not school_class_id:
            return json_error('Academic Term and School Class are required.')

        term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)
        school_class = get_object_or_404(SchoolClass, id=school_class_id, school=school)

        valid_items = []
        seen_categories = set()

        for category_id, amount_value in zip(category_ids, amounts):
            if not category_id:
                continue

            amount = decimal_from_value(amount_value)
            if amount <= Decimal('0.00'):
                return json_error('All fee amounts must be greater than zero.')

            category = get_object_or_404(FeeCategory, id=category_id, school=school, is_active=True)

            if str(category.id) in seen_categories:
                return json_error(f"Fee category '{category.name}' has been added more than once.")

            seen_categories.add(str(category.id))
            valid_items.append((category, amount))

        if not valid_items:
            return json_error('Please add at least one fee category with an amount.')

        if FeeStructure.objects.filter(academic_term=term, school_class=school_class).exists():
            return json_error(f"A fee structure for {school_class.name} in {term.name} already exists.")

        with transaction.atomic():
            structure = FeeStructure.objects.create(
                school=school,
                academic_term=term,
                school_class=school_class,
                is_published=False,
            )

            for category, amount in valid_items:
                FeeStructureItem.objects.create(
                    fee_structure=structure,
                    fee_category=category,
                    amount=amount,
                )

        return JsonResponse({
            'success': True,
            'message': f"Fee Structure for {school_class.name} created successfully with {len(valid_items)} item(s).",
            'structure_id': str(structure.id),
        })

    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def fee_structure_edit(request, structure_id):
    """Edit an unpublished fee structure."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:fee_structure_list')

    school = request.user.school
    structure = get_object_or_404(FeeStructure, id=structure_id, school=school)

    if structure.is_published:
        return json_error('Cannot edit a published fee structure. Published structures are locked.')

    if request.method == 'GET':
        school_classes = SchoolClass.objects.filter(school=school).select_related('grade_level').order_by(
            'grade_level__order', 'name')
        terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')
        fee_categories = FeeCategory.objects.filter(school=school, is_active=True).order_by('name')
        existing_items = structure.items.select_related('fee_category').all()

        return render(request, 'finance/fee_structure_form_modal.html', {
            'mode': 'edit',
            'structure': structure,
            'school_classes': school_classes,
            'terms': terms,
            'fee_categories': fee_categories,
            'existing_items': existing_items,
            'action_url': 'finance:fee_structure_edit',
        })

    try:
        term_id = request.POST.get('academic_term')
        school_class_id = request.POST.get('school_class')
        category_ids = request.POST.getlist('categories')
        amounts = request.POST.getlist('amounts')

        if not term_id or not school_class_id:
            return json_error('Academic Term and School Class are required.')

        term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)
        school_class = get_object_or_404(SchoolClass, id=school_class_id, school=school)

        valid_items = []
        seen_categories = set()

        for category_id, amount_value in zip(category_ids, amounts):
            if not category_id:
                continue

            amount = decimal_from_value(amount_value)
            if amount <= Decimal('0.00'):
                return json_error('All fee amounts must be greater than zero.')

            category = get_object_or_404(FeeCategory, id=category_id, school=school, is_active=True)

            if str(category.id) in seen_categories:
                return json_error(f"Fee category '{category.name}' has been added more than once.")

            seen_categories.add(str(category.id))
            valid_items.append((category, amount))

        if not valid_items:
            return json_error('Please add at least one fee category with an amount.')

        if FeeStructure.objects.filter(academic_term=term, school_class=school_class).exclude(id=structure.id).exists():
            return json_error(f"A fee structure for {school_class.name} in {term.name} already exists.")

        with transaction.atomic():
            structure.academic_term = term
            structure.school_class = school_class
            structure.save(update_fields=['academic_term', 'school_class'])

            structure.items.all().delete()

            for category, amount in valid_items:
                FeeStructureItem.objects.create(
                    fee_structure=structure,
                    fee_category=category,
                    amount=amount,
                )

        return JsonResponse({
            'success': True,
            'message': f"Fee Structure updated successfully with {len(valid_items)} item(s).",
        })

    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def fee_structure_delete(request, structure_id):
    """Delete an unpublished fee structure."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:fee_structure_list')

    school = request.user.school
    structure = get_object_or_404(FeeStructure, id=structure_id, school=school)

    if structure.is_published:
        return json_error('Cannot delete a published fee structure.')

    if request.method == 'GET':
        return render(request, 'finance/fee_structure_delete_modal.html', {
            'structure': structure,
            'action_url': 'finance:fee_structure_delete',
        })

    try:
        structure_name = f"{structure.school_class.name} - {structure.academic_term.name}"
        structure.delete()
        return JsonResponse({
            'success': True,
            'message': f"Fee Structure for '{structure_name}' deleted successfully.",
        })

    except IntegrityError:
        return json_error('Cannot delete this structure because it is already linked to generated invoices.')
    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
def fee_structure_detail(request, structure_id):
    """View a single fee structure."""
    school = request.user.school
    structure = get_object_or_404(
        FeeStructure.objects.select_related('academic_term', 'school_class', 'school_class__grade_level')
            .prefetch_related('items__fee_category'),
        id=structure_id,
        school=school
    )

    return render(request, 'finance/fee_structure_detail.html', {
        'structure': structure,
        'can_manage': user_can_manage_finance(request.user),
    })


@login_required
def fee_schedule_view(request, structure_id):
    """
    Printable/viewable HTML fee schedule for a class/term -- itemized base
    fees + add-ons, with NO student attached, for parents making enquiries
    about a class before enrolling.
    """
    school = request.user.school
    structure = get_object_or_404(
        FeeStructure.objects.select_related('school_class__grade_level', 'academic_term__academic_year'),
        id=structure_id,
        school=school,
    )

    from .services.fee_preparation import get_class_fee_schedule
    context = get_class_fee_schedule(school, structure.school_class, structure.academic_term)
    context['is_pdf'] = False
    context['structure_id'] = structure.id

    return render(request, 'finance/fee_schedule.html', context)


@login_required
def fee_schedule_pdf(request, structure_id):
    """Download the generic class/term fee schedule (no student name) as a PDF."""
    school = request.user.school
    structure = get_object_or_404(
        FeeStructure.objects.select_related('school_class__grade_level', 'academic_term__academic_year'),
        id=structure_id,
        school=school,
    )

    from .services.fee_preparation import generate_fee_schedule_pdf
    pdf_bytes = generate_fee_schedule_pdf(school, structure.school_class, structure.academic_term, structure_id=structure.id)
    if not pdf_bytes:
        return HttpResponse(
            'Could not generate the fee schedule PDF right now. Please try again, or contact support.',
            status=500,
        )

    filename = f"Fee-Schedule-{structure.school_class.name}-{structure.academic_term.name}.pdf".replace(' ', '-')
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    return response


# ============================================================================
# FEE WAIVER MANAGEMENT
# ============================================================================

@login_required
def waiver_list(request):
    """List all fee waivers."""
    school = request.user.school
    waivers = (
        FeeWaiver.objects
            .filter(school=school)
            .select_related('student', 'student__user', 'fee_category', 'academic_term')
            .order_by('-created_at')
    )

    return render(request, 'finance/waiver_list.html', {
        'waivers': paginate_queryset(waivers, request),
        'can_manage': user_can_manage_finance(request.user),
    })


@login_required
@require_http_methods(["GET", "POST"])
def waiver_create(request):
    """Create a new fee waiver."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:waiver_list')

    school = request.user.school

    if request.method == 'GET':
        students = Student.objects.filter(school=school, is_active=True).select_related('user').order_by(
            'user__last_name')
        fee_categories = FeeCategory.objects.filter(school=school, is_active=True).order_by('name')
        terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')

        return render(request, 'finance/waiver_form_modal.html', {
            'mode': 'create',
            'waiver': None,
            'students': students,
            'fee_categories': fee_categories,
            'terms': terms,
            'action_url': 'finance:waiver_create',
        })

    try:
        student_id = request.POST.get('student')
        reason = request.POST.get('reason', '').strip()
        waiver_type = request.POST.get('waiver_type', 'PERCENTAGE')
        value = decimal_from_value(request.POST.get('value'))
        fee_category_id = request.POST.get('fee_category')
        academic_term_id = request.POST.get('academic_term')
        is_active = request.POST.get('is_active') == 'on'

        if not student_id or not reason:
            return json_error('Student and Reason are required.')

        if value <= Decimal('0.00'):
            return json_error('Value must be greater than zero.')

        student = get_object_or_404(Student, id=student_id, school=school)

        fee_category = None
        if fee_category_id:
            fee_category = get_object_or_404(FeeCategory, id=fee_category_id, school=school)

        academic_term = None
        if academic_term_id:
            academic_term = get_object_or_404(AcademicTerm, id=academic_term_id, academic_year__school=school)

        waiver = FeeWaiver.objects.create(
            school=school,
            student=student,
            reason=reason,
            waiver_type=waiver_type,
            value=value,
            fee_category=fee_category,
            academic_term=academic_term,
            is_active=is_active,
            approved_by=request.user,
        )

        return JsonResponse({
            'success': True,
            'message': f'Waiver for {student} created successfully.',
            'waiver_id': str(waiver.id),
        })

    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def waiver_edit(request, waiver_id):
    """Edit a fee waiver."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:waiver_list')

    school = request.user.school
    waiver = get_object_or_404(FeeWaiver, id=waiver_id, school=school)

    if request.method == 'GET':
        students = Student.objects.filter(school=school, is_active=True).select_related('user').order_by(
            'user__last_name')
        fee_categories = FeeCategory.objects.filter(school=school, is_active=True).order_by('name')
        terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')

        return render(request, 'finance/waiver_form_modal.html', {
            'mode': 'edit',
            'waiver': waiver,
            'students': students,
            'fee_categories': fee_categories,
            'terms': terms,
            'action_url': 'finance:waiver_edit',
        })

    try:
        student_id = request.POST.get('student')
        reason = request.POST.get('reason', '').strip()
        waiver_type = request.POST.get('waiver_type', 'PERCENTAGE')
        value = decimal_from_value(request.POST.get('value'))
        fee_category_id = request.POST.get('fee_category')
        academic_term_id = request.POST.get('academic_term')
        is_active = request.POST.get('is_active') == 'on'

        if not student_id or not reason:
            return json_error('Student and Reason are required.')

        if value <= Decimal('0.00'):
            return json_error('Value must be greater than zero.')

        student = get_object_or_404(Student, id=student_id, school=school)

        fee_category = None
        if fee_category_id:
            fee_category = get_object_or_404(FeeCategory, id=fee_category_id, school=school)

        academic_term = None
        if academic_term_id:
            academic_term = get_object_or_404(AcademicTerm, id=academic_term_id, academic_year__school=school)

        waiver.student = student
        waiver.reason = reason
        waiver.waiver_type = waiver_type
        waiver.value = value
        waiver.fee_category = fee_category
        waiver.academic_term = academic_term
        waiver.is_active = is_active
        waiver.approved_by = request.user
        waiver.save()

        return JsonResponse({
            'success': True,
            'message': f'Waiver for {student} updated successfully.',
        })

    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
@require_http_methods(["GET", "POST"])
def waiver_delete(request, waiver_id):
    """Delete a fee waiver."""
    if not user_can_manage_finance(request.user):
        return permission_denied_response(request, 'finance:waiver_list')

    school = request.user.school
    waiver = get_object_or_404(FeeWaiver, id=waiver_id, school=school)

    if request.method == 'GET':
        return render(request, 'finance/waiver_delete_modal.html', {
            'waiver': waiver,
            'action_url': 'finance:waiver_delete',
        })

    try:
        waiver.delete()
        return JsonResponse({
            'success': True,
            'message': 'Waiver deleted successfully.',
        })
    except Exception as exc:
        return json_error(str(exc), status=500)


# ============================================================================
# FEE PREPARATION VIEWS
# ============================================================================

@login_required
def fee_preparation(request):
    """Fee preparation dashboard for a specific term."""
    school = request.user.school

    # Get active term
    active_term = AcademicTerm.objects.filter(
        academic_year__school=school,
        academic_year__is_active=True,
        is_active=True
    ).first()

    # Get all terms
    terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')

    # Get all school classes
    school_classes = SchoolClass.objects.filter(school=school).select_related('grade_level').order_by(
        'grade_level__order', 'name')

    # Get fee structures for the active term
    fee_structures = {}
    if active_term:
        fee_structures = {
            fs.school_class_id: fs
            for fs in FeeStructure.objects.filter(
                school=school,
                academic_term=active_term
            ).select_related('school_class', 'academic_term')
        }

    # Get student fee preparation status for each class
    class_status = []
    for cls in school_classes:
        student_fees = StudentFee.objects.filter(
            school=school,
            academic_term=active_term,
            student__school_class=cls
        ) if active_term else StudentFee.objects.none()

        status_counts = {
            'total': student_fees.count(),
            'draft': student_fees.filter(status='DRAFT').count(),
            'prepared': student_fees.filter(status='PREPARED').count(),
            'approved': student_fees.filter(status='APPROVED').count(),
            'invoiced': student_fees.filter(status='INVOICED').count(),
            'cancelled': student_fees.filter(status='CANCELLED').count(),
        }

        class_status.append({
            'class': cls,
            'has_fee_structure': cls.id in fee_structures,
            'fee_structure': fee_structures.get(cls.id),
            'status_counts': status_counts,
            'students': Student.objects.filter(school=school, school_class=cls).count(),
        })

    # Get recent student fees
    student_fees = StudentFee.objects.filter(
        school=school
    ).select_related(
        'student', 'student__user', 'academic_term', 'student__school_class'
    ).order_by('-updated_at')[:50]

    context = {
        'active_term': active_term,
        'terms': terms,
        'class_status': class_status,
        'student_fees': student_fees,
        'can_manage': user_can_manage_finance(request.user),
    }

    return render(request, 'finance/fee_preparation.html', context)


@login_required
@require_POST
def api_prepare_class_fees(request):
    """Prepare fees for all students in a class."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    try:
        data = json.loads(request.body or '{}')
        class_id = data.get('class_id')
        term_id = data.get('term_id')
        force_rebuild = data.get('force_rebuild', False)

        if not class_id or not term_id:
            return json_error('Class ID and Term ID are required.')

        school = request.user.school
        school_class = get_object_or_404(SchoolClass, id=class_id, school=school)
        academic_term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)

        # Check if fee structure exists
        fee_structure = FeeStructure.objects.filter(
            school=school,
            academic_term=academic_term,
            school_class=school_class
        ).first()

        if not fee_structure:
            return json_error(
                f'No fee structure exists for {school_class.name} in {academic_term.name}. '
                f'Please create a fee structure first.'
            )

        # Prepare fees for all students in the class
        result = prepare_class_fees(
            school=school,
            school_class=school_class,
            academic_term=academic_term,
            prepared_by=request.user,
            force_rebuild=force_rebuild,
        )

        return JsonResponse({
            'success': True,
            'message': f'Prepared fees for {result["prepared_count"]} student(s).',
            'prepared': result['prepared_count'],
            'total': result['total_students'],
            'errors': result['errors'],
        })

    except json.JSONDecodeError:
        return json_error('Invalid JSON request.')
    except Exception as exc:
        return json_error(str(exc), status=500)


# finance/views.py - Add these new views

# finance/views.py - Add these new views after the existing ones

# ============================================================================
# FEE ADD-ON VIEWS
# ============================================================================

# finance/views.py - Update fee_addon_list view

@login_required
def fee_addon_list(request):
    """Unified fee add-on page grouped exactly by school class."""
    if not user_can_manage_finance(request.user):
        messages.error(request, "You don't have permission to manage fee add-ons.")
        return redirect('finance:billing_dashboard')

    school = request.user.school

    school_classes = list(
        SchoolClass.objects.filter(school=school)
        .select_related('grade_level')
        .order_by('grade_level__order', 'name')
    )

    class_items = (
        ClassAddOnItem.objects.filter(
            school=school,
            addon_structure__school=school,
        )
        .select_related(
            'addon_structure',
            'addon_structure__fee_category',
            'grade_level',
            'school_class',
        )
        .order_by('school_class__grade_level__order', 'school_class__name', 'addon_structure__name')
    )

    items_by_class = {str(cls.id): [] for cls in school_classes}
    unassigned_items = []

    for item in class_items:
        if item.school_class_id:
            bucket = items_by_class.get(str(item.school_class_id))
            if bucket is not None:
                bucket.append(item)
            else:
                unassigned_items.append(item)
        elif item.grade_level_id:
            matched = False
            for cls in school_classes:
                if cls.grade_level_id == item.grade_level_id:
                    items_by_class[str(cls.id)].append(item)
                    matched = True
            if not matched:
                unassigned_items.append(item)
        else:
            for cls in school_classes:
                items_by_class[str(cls.id)].append(item)

    class_columns = []
    for cls in school_classes:
        items = items_by_class[str(cls.id)]
        total = sum(item.amount for item in items)  # Calculate total
        class_columns.append({
            'school_class': cls,
            'items': items,
            'total': total,  # Add total to context
        })

    if unassigned_items:
        total = sum(item.amount for item in unassigned_items)
        class_columns.append({
            'school_class': None,
            'items': unassigned_items,
            'total': total,
        })

    legacy_addons = (
        FeeAddOnStructure.objects.filter(school=school)
        .select_related('academic_term')
        .prefetch_related('items__fee_category')
        .order_by('-created_at')
    )

    return render(request, 'finance/fee_addon_list.html', {
        'class_columns': class_columns,
        'legacy_addons': paginate_queryset(legacy_addons, request),
        'class_addon_count': ClassAddOnStructure.objects.filter(school=school).count(),
        'can_manage': True,
        'active_tab': 'finance',
    })


# finance/views.py - Updated fee_addon_create with better error handling

@login_required
@require_http_methods(["GET", "POST"])
def fee_addon_create(request):
    """Create a new fee add-on structure."""
    if not user_can_manage_finance(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Permission denied.', 403)
        messages.error(request, "Permission denied.")
        return redirect('finance:fee_addon_list')

    school = request.user.school

    if request.method == 'GET':
        terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')
        fee_categories = FeeCategory.objects.filter(school=school, is_active=True).order_by('name')

        return render(request, 'finance/fee_addon_form_modal.html', {
            'mode': 'create',
            'terms': terms,
            'fee_categories': fee_categories,
            'action_url': 'finance:fee_addon_create',
        })

    # POST
    try:
        import logging
        logger = logging.getLogger(__name__)

        name = request.POST.get('name', '').strip()
        term_id = request.POST.get('academic_term', '').strip()
        apply_to_new_students_only = request.POST.get('apply_to_new_students_only') == 'on'
        is_active = request.POST.get('is_active') == 'on'

        category_ids = request.POST.getlist('categories')
        amounts = request.POST.getlist('amounts')
        descriptions = request.POST.getlist('descriptions')

        logger.info(
            f"Fee Add-on Create - Name: {name}, Term: {term_id}, Categories: {category_ids}, Amounts: {amounts}")

        # Validation
        if not name:
            error_msg = 'Add-on name is required.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(request, error_msg)
            return redirect('finance:fee_addon_list')

        if not term_id:
            error_msg = 'Academic Term is required.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(request, error_msg)
            return redirect('finance:fee_addon_list')

        term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)

        # Check if any valid items exist
        has_valid_item = False
        for idx, cat_id in enumerate(category_ids):
            if cat_id and idx < len(amounts):
                amount = decimal_from_value(amounts[idx])
                if amount > ZERO:
                    has_valid_item = True
                    break

        if not has_valid_item:
            error_msg = 'Please add at least one valid fee item with an amount greater than zero.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg}, status=400)
            messages.error(request, error_msg)
            return redirect('finance:fee_addon_list')

        with transaction.atomic():
            # Create the add-on
            addon = FeeAddOnStructure.objects.create(
                school=school,
                name=name,
                academic_term=term,
                apply_to_new_students_only=apply_to_new_students_only,
                is_active=is_active,
            )

            logger.info(f"Fee Add-on created with ID: {addon.id}")

            # Create items
            item_count = 0
            for idx, cat_id in enumerate(category_ids):
                if not cat_id:
                    continue
                if idx >= len(amounts):
                    continue

                amount = decimal_from_value(amounts[idx])
                if amount <= ZERO:
                    continue

                category = get_object_or_404(FeeCategory, id=cat_id, school=school)
                desc = descriptions[idx] if idx < len(descriptions) else ''

                FeeAddOnItem.objects.create(
                    addon_structure=addon,
                    fee_category=category,
                    amount=amount,
                    description=desc,
                )
                item_count += 1

            logger.info(f"Created {item_count} items for add-on {addon.id}")

        success_msg = f'Fee add-on "{name}" created successfully with {item_count} item(s).'

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': success_msg,
                'addon_id': str(addon.id),
            })

        messages.success(request, success_msg)
        return redirect('finance:fee_addon_list')

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"Error creating fee add-on: {str(e)}"
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': error_msg}, status=500)
        messages.error(request, error_msg)
        return redirect('finance:fee_addon_list')


@login_required
@require_http_methods(["GET", "POST"])
def fee_addon_edit(request, addon_id):
    """Edit an existing fee add-on structure."""
    if not user_can_manage_finance(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Permission denied.', 403)
        messages.error(request, "Permission denied.")
        return redirect('finance:fee_addon_list')

    school = request.user.school
    addon = get_object_or_404(FeeAddOnStructure, id=addon_id, school=school)

    if request.method == 'GET':
        terms = AcademicTerm.objects.filter(academic_year__school=school).select_related('academic_year').order_by('-start_date')
        fee_categories = FeeCategory.objects.filter(school=school, is_active=True).order_by('name')
        existing_items = addon.items.select_related('fee_category').all()

        return render(request, 'finance/fee_addon_form_modal.html', {
            'mode': 'edit',
            'addon': addon,
            'terms': terms,
            'fee_categories': fee_categories,
            'existing_items': existing_items,
            'action_url': 'finance:fee_addon_edit',
        })

    # POST
    name = request.POST.get('name', '').strip()
    term_id = request.POST.get('academic_term', '').strip()
    apply_to_new_students_only = request.POST.get('apply_to_new_students_only') == 'on'
    is_active = request.POST.get('is_active') == 'on'

    category_ids = request.POST.getlist('categories')
    amounts = request.POST.getlist('amounts')
    descriptions = request.POST.getlist('descriptions')

    # Validation
    if not name:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Add-on name is required.')
        messages.error(request, "Add-on name is required.")
        return redirect('finance:fee_addon_list')

    if not term_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Academic Term is required.')
        messages.error(request, "Academic Term is required.")
        return redirect('finance:fee_addon_list')

    try:
        term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)

        with transaction.atomic():
            addon.name = name
            addon.academic_term = term
            addon.apply_to_new_students_only = apply_to_new_students_only
            addon.is_active = is_active
            addon.save()

            # Delete existing items
            addon.items.all().delete()

            for idx, cat_id in enumerate(category_ids):
                if not cat_id:
                    continue
                if idx >= len(amounts):
                    continue

                amount = decimal_from_value(amounts[idx])
                if amount <= ZERO:
                    continue

                category = get_object_or_404(FeeCategory, id=cat_id, school=school)
                desc = descriptions[idx] if idx < len(descriptions) else ''

                FeeAddOnItem.objects.create(
                    addon_structure=addon,
                    fee_category=category,
                    amount=amount,
                    description=desc,
                )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'Fee add-on "{name}" updated successfully.',
            })

        messages.success(request, f'Fee add-on "{name}" updated successfully.')
        return redirect('finance:fee_addon_list')

    except Exception as e:
        import traceback
        traceback.print_exc()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error(f"Error updating fee add-on: {str(e)}")
        messages.error(request, f"Error updating fee add-on: {str(e)}")
        return redirect('finance:fee_addon_list')


@login_required
@require_POST
def fee_addon_delete(request, addon_id):
    """Delete a fee add-on structure."""
    if not user_can_manage_finance(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Permission denied.', 403)
        messages.error(request, "Permission denied.")
        return redirect('finance:fee_addon_list')

    school = request.user.school
    addon = get_object_or_404(FeeAddOnStructure, id=addon_id, school=school)

    try:
        addon_name = addon.name
        addon.delete()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': f'Fee add-on "{addon_name}" deleted successfully.',
                'id': str(addon_id),
            })

        messages.success(request, f'Fee add-on "{addon_name}" deleted successfully.')
        return redirect('finance:fee_addon_list')

    except Exception as e:
        import traceback
        traceback.print_exc()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error(f"Error deleting fee add-on: {str(e)}")
        messages.error(request, f"Error deleting fee add-on: {str(e)}")
        return redirect('finance:fee_addon_list')


# ============================================================================
# STUDENT FEE ADJUSTMENT VIEWS
# ============================================================================

@login_required
def student_fee_adjustments(request, student_fee_id):
    """Manage adjustments for a student fee."""
    if not user_can_manage_finance(request.user):
        messages.error(request, "You don't have permission to manage fee adjustments.")
        return redirect('finance:student_fees_list')

    school = request.user.school
    student_fee = get_object_or_404(
        StudentFee.objects.select_related('student', 'student__user', 'academic_term'),
        id=student_fee_id,
        school=school
    )

    adjustments = StudentFeeAdjustment.objects.filter(
        student_fee=student_fee
    ).select_related('fee_category', 'created_by').order_by('-created_at')

    fee_categories = FeeCategory.objects.filter(school=school, is_active=True).order_by('name')

    context = {
        'student_fee': student_fee,
        'adjustments': paginate_queryset(adjustments, request),
        'fee_categories': fee_categories,
        'can_manage': user_can_manage_finance(request.user),
        'adjustment_types': StudentFeeAdjustment.ADJUSTMENT_TYPE_CHOICES,
    }

    return render(request, 'finance/student_fee_adjustments.html', context)


@login_required
@require_POST
def api_student_fee_adjustment_create(request, student_fee_id):
    """Create a new adjustment for a student fee."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    school = request.user.school
    student_fee = get_object_or_404(
        StudentFee.objects.select_related('student'),
        id=student_fee_id,
        school=school
    )

    if student_fee.status in ['INVOICED', 'CANCELLED']:
        return json_error(f'Cannot adjust a fee that is {student_fee.get_status_display().lower()}.')

    try:
        data = json.loads(request.body or '{}')
        fee_category_id = data.get('fee_category_id')
        adjustment_type = data.get('adjustment_type')
        amount = decimal_from_value(data.get('amount'))
        description = data.get('description', '').strip()

        if not fee_category_id or not adjustment_type or amount <= 0:
            return json_error('Fee category, adjustment type, and amount are required.')

        fee_category = get_object_or_404(FeeCategory, id=fee_category_id, school=school)

        with transaction.atomic():
            adjustment = StudentFeeAdjustment.objects.create(
                school=school,
                student_fee=student_fee,
                fee_category=fee_category,
                adjustment_type=adjustment_type,
                amount=amount,
                description=description,
                created_by=request.user,
                is_active=True,
            )

            # Rebuild the fee to include the adjustment
            from .services.fee_preparation import prepare_student_fee
            prepare_student_fee(
                student=student_fee.student,
                academic_term=student_fee.academic_term,
                prepared_by=request.user,
                force_rebuild=True,
            )

        return JsonResponse({
            'success': True,
            'message': f'Adjustment "{description}" added successfully.',
            'adjustment_id': str(adjustment.id),
        })

    except json.JSONDecodeError:
        return json_error('Invalid JSON data.')
    except Exception as e:
        import traceback
        traceback.print_exc()
        return json_error(str(e))


@login_required
@require_POST
def api_student_fee_adjustment_delete(request, adjustment_id):
    """Delete a student fee adjustment."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    school = request.user.school
    adjustment = get_object_or_404(
        StudentFeeAdjustment.objects.select_related('student_fee', 'student_fee__student'),
        id=adjustment_id,
        school=school
    )

    student_fee = adjustment.student_fee

    if student_fee.status in ['INVOICED', 'CANCELLED']:
        return json_error(f'Cannot delete adjustment from a fee that is {student_fee.get_status_display().lower()}.')

    try:
        with transaction.atomic():
            adjustment.delete()

            # Rebuild the fee
            from .services.fee_preparation import prepare_student_fee
            prepare_student_fee(
                student=student_fee.student,
                academic_term=student_fee.academic_term,
                prepared_by=request.user,
                force_rebuild=True,
            )

        return JsonResponse({
            'success': True,
            'message': 'Adjustment deleted successfully.',
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return json_error(str(e))

@login_required
def api_student_fee_detail(request, student_fee_id):
    """Return complete student-fee detail with server-authoritative totals.

    The browser must never guess which lines are add-ons or calculate the
    invoice total from StudentFee.final_amount because StudentFee.final_amount
    represents the prepared base fee and class add-ons are stored as separate
    StudentFeeItem rows.
    """
    school = request.user.school
    student_fee = get_object_or_404(
        StudentFee.objects.select_related(
            'student',
            'student__user',
            'student__school_class',
            'academic_term',
            'fee_structure',
        ),
        id=student_fee_id,
        school=school,
    )

    enrollment = (
        StudentFeeEnrollment.objects
        .filter(
            student=student_fee.student,
            academic_term=student_fee.academic_term,
        )
        .select_related('enrollment_type')
        .first()
    )

    # The term enrollment is the source of truth. Do not use the student's
    # global is_new_student profile flag for term-specific billing.
    is_new_student = bool(
        enrollment
        and enrollment.enrollment_type
        and enrollment.enrollment_type.code == 'NEW'
    )

    # Build exact server-side descriptions for class add-ons. This is safer
    # than guessing from fee-category names such as "Admission" or "Uniform".
    addon_descriptions = set()
    if is_new_student:
        for addon in get_applicable_class_addons(
            student_fee.student,
            student_fee.academic_term,
        ):
            if addon.get('apply_to_new_students_only'):
                description = str(addon.get('description') or '').strip()
                if description:
                    addon_descriptions.add(description.casefold())

    items = []
    base_total = Decimal('0.00')
    addon_total = Decimal('0.00')

    for item in student_fee.items.select_related('fee_category').all():
        description = (item.description or '').strip()
        is_new_student_addon = bool(
            is_new_student
            and description.casefold() in addon_descriptions
        )

        final_amount = item.final_amount or Decimal('0.00')
        if is_new_student_addon:
            addon_total += final_amount
        else:
            base_total += final_amount

        items.append({
            'id': str(item.id),
            'category': item.fee_category.name,
            'description': item.description,
            'standard_amount': str(item.standard_amount or Decimal('0.00')),
            'discount_amount': str(item.discount_amount or Decimal('0.00')),
            'adjustment_amount': str(item.adjustment_amount or Decimal('0.00')),
            'final_amount': str(final_amount),
            'is_optional': item.is_optional,
            'is_waived': item.is_waived,
            'is_new_student_addon': is_new_student_addon,
        })

    # These are the authoritative totals shown by the Fee Items Detail modal.
    # They are calculated from the actual StudentFeeItem rows, so the displayed
    # total always equals Base + New Student Add-ons.
    items_total = base_total + addon_total

    return JsonResponse({
        'success': True,
        'id': str(student_fee.id),
        'student_id': str(student_fee.student.id),
        'student_name': student_fee.student.user.get_full_name(),
        'term': student_fee.academic_term.name,
        'status': student_fee.status,
        'is_new_student': is_new_student,
        # Legacy fields retained for compatibility with any existing code.
        'base_amount': str(student_fee.base_amount or Decimal('0.00')),
        'discount_amount': str(student_fee.discount_amount or Decimal('0.00')),
        'adjustment_amount': str(student_fee.adjustment_amount or Decimal('0.00')),
        'arrears_amount': str(student_fee.arrears_amount or Decimal('0.00')),
        'final_amount': str(items_total),
        # New authoritative breakdown fields.
        'base_items_total': str(base_total),
        'addon_total': str(addon_total),
        'items_total': str(items_total),
        'items': items,
        'notes': student_fee.notes,
    })


@login_required
@require_POST
def api_student_fee_approve(request, student_fee_id):
    """Approve a student fee preparation."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    school = request.user.school
    student_fee = get_object_or_404(
        StudentFee.objects.select_related('student', 'academic_term'),
        id=student_fee_id,
        school=school
    )

    if student_fee.status == 'INVOICED':
        return json_error('This student fee has already been invoiced.')

    if student_fee.status == 'CANCELLED':
        return json_error('This student fee has been cancelled.')

    if student_fee.final_amount <= Decimal('0.00'):
        return json_error('Cannot approve a fee with zero amount.')

    with transaction.atomic():
        student_fee.status = 'APPROVED'
        student_fee.approved_by = request.user
        student_fee.save(update_fields=['status', 'approved_by', 'updated_at'])

        # Create ledger entry for the approved fee
        from .services.fee_preparation import create_student_fee_ledger_entry
        create_student_fee_ledger_entry(student_fee, created_by=request.user)

    return JsonResponse({
        'success': True,
        'message': f'Student fee for {student_fee.student.user.get_full_name()} has been approved.',
        'status': student_fee.status,
    })


@login_required
@require_POST
def api_student_fee_bulk_approve(request):
    """Bulk approve multiple student fees."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    try:
        data = json.loads(request.body or '{}')
        fee_ids = data.get('fee_ids', [])

        if not fee_ids:
            return json_error('No student fees selected for approval.')

        school = request.user.school
        approved_count = 0
        errors = []

        for fee_id in fee_ids:
            try:
                student_fee = get_object_or_404(
                    StudentFee.objects.select_related('student', 'academic_term'),
                    id=fee_id,
                    school=school
                )

                if student_fee.status == 'INVOICED':
                    errors.append(f"{student_fee.student.user.get_full_name()}: Already invoiced")
                    continue

                if student_fee.status == 'CANCELLED':
                    errors.append(f"{student_fee.student.user.get_full_name()}: Cancelled")
                    continue

                if student_fee.final_amount <= Decimal('0.00'):
                    errors.append(f"{student_fee.student.user.get_full_name()}: Zero amount")
                    continue

                student_fee.status = 'APPROVED'
                student_fee.approved_by = request.user
                student_fee.save(update_fields=['status', 'approved_by', 'updated_at'])
                approved_count += 1

            except Exception as e:
                errors.append(f"Error processing fee {fee_id}: {str(e)}")

        return JsonResponse({
            'success': True,
            'message': f'Successfully approved {approved_count} student fee(s).',
            'approved': approved_count,
            'errors': errors if errors else None,
        })

    except json.JSONDecodeError:
        return json_error('Invalid JSON request.')
    except Exception as exc:
        return json_error(str(exc), status=500)


@login_required
def api_backfill_ledger_entries(request):
    """Admin view to backfill missing ledger entries for approved fees."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    school = request.user.school

    from .services.fee_preparation import create_ledger_entries_for_approved_fees

    created_count = create_ledger_entries_for_approved_fees(school)

    return JsonResponse({
        'success': True,
        'message': f'Created {created_count} missing ledger entries.',
        'created': created_count,
    })


# ============================================================================
# INVOICE MANAGEMENT
# ============================================================================

@login_required
def invoice_list(request):
    """List invoices and provide terms/classes for invoice generation."""
    school = request.user.school

    invoices = (
        Invoice.objects
            .filter(school=school)
            .select_related('student', 'student__user', 'academic_term')
            .prefetch_related('line_items', 'payments')
            .order_by('-created_at')
    )

    terms = (
        AcademicTerm.objects
            .filter(academic_year__school=school)
            .select_related('academic_year')
            .order_by('-start_date')
    )

    school_classes = (
        SchoolClass.objects
            .filter(school=school)
            .select_related('grade_level')
            .order_by('grade_level__order', 'name')
    )

    return render(request, 'finance/invoice_list.html', {
        'invoices': paginate_queryset(invoices, request),
        'terms': terms,
        'school_classes': school_classes,
        'can_manage': user_can_manage_finance(request.user),
    })


@login_required
def invoice_detail(request, invoice_id):
    """View a single invoice."""
    school = request.user.school
    invoice = get_object_or_404(
        Invoice.objects.select_related('student', 'student__user', 'academic_term')
            .prefetch_related('line_items__fee_category', 'payments'),
        id=invoice_id,
        school=school
    )

    # FIXED: Calculate totals using InvoiceLineItem and Payment
    total_amount = InvoiceLineItem.objects.filter(
        invoice=invoice
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    amount_paid = Payment.objects.filter(
        invoice=invoice,
        status='CONFIRMED'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    balance_due = total_amount - amount_paid

    return render(request, 'finance/invoice_detail.html', {
        'invoice': invoice,
        'total_amount': total_amount,
        'amount_paid': amount_paid,
        'balance_due': balance_due,
        'can_manage': user_can_manage_finance(request.user),
    })


# ============================================================================
# FEE STATEMENTS (full itemized invoice -- base fees + add-ons, for parents)
# ============================================================================

@login_required
def invoice_statement_view(request, invoice_id):
    """Printable/viewable HTML fee statement for one invoice, with Print / Download PDF / Email actions."""
    school = request.user.school
    invoice = get_object_or_404(
        Invoice.objects.select_related('student__user', 'student__school_class', 'school', 'academic_term')
            .prefetch_related('line_items__fee_category', 'payments'),
        id=invoice_id,
        school=school,
    )

    from .services.statements import build_invoice_statement_context
    context = build_invoice_statement_context(invoice)
    context['is_pdf'] = False
    context['can_manage'] = user_can_manage_finance(request.user)

    return render(request, 'finance/invoice_statement.html', context)


@login_required
def invoice_statement_pdf(request, invoice_id):
    """Download (or view inline with ?inline=1) the invoice fee statement as a PDF."""
    school = request.user.school
    invoice = get_object_or_404(
        Invoice.objects.select_related('student__user', 'school'),
        id=invoice_id,
        school=school,
    )

    from .services.statements import generate_invoice_statement_pdf
    pdf_bytes = generate_invoice_statement_pdf(invoice)
    if not pdf_bytes:
        return HttpResponse(
            'Could not generate the fee statement PDF right now. Please try again, or contact support.',
            status=500,
        )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="Fee-Statement-{invoice.invoice_number}.pdf"'
    return response


@login_required
@require_POST
def api_email_invoice_statement(request, invoice_id):
    """Email the full itemized fee statement (PDF attached) to the parent on demand."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    school = request.user.school
    invoice = get_object_or_404(
        Invoice.objects.select_related('student__user', 'school', 'academic_term'),
        id=invoice_id,
        school=school,
    )

    from .services.statements import send_invoice_statement_email
    result = send_invoice_statement_email(invoice)

    if not result['email_sent']:
        return json_error(result.get('reason') or 'Could not send the fee statement via email.')

    return JsonResponse({
        'success': True,
        'email_sent': True,
        'message': 'Fee statement emailed to parent.',
    })


def _invoices_for_bulk_statements(request, data):
    """Shared filter logic for the bulk statement PDF/email endpoints."""
    school = request.user.school
    term_id = data.get('term_id')
    school_class_ids = data.get('school_class_ids') or []

    invoices = (
        Invoice.objects
        .filter(school=school, status__in=['UNPAID', 'PARTIAL', 'PAID'])
        .select_related('student__user', 'student__school_class', 'school', 'academic_term')
        .prefetch_related('line_items__fee_category', 'payments')
    )
    if term_id:
        invoices = invoices.filter(academic_term_id=term_id)
    if school_class_ids:
        invoices = invoices.filter(student__school_class_id__in=school_class_ids)

    return invoices.order_by('student__school_class__name', 'student__user__last_name')


@login_required
@require_POST
def api_bulk_invoice_statements_pdf(request):
    """
    Generate fee statements for every invoice matching the given term/class
    filters and return them as a single downloadable zip of PDFs.
    """
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return json_error('Invalid request.')

    invoices = list(_invoices_for_bulk_statements(request, data))
    if not invoices:
        return json_error('No invoices match the selected term/class.')

    from .services.statements import generate_bulk_statements_zip
    zip_bytes, summary = generate_bulk_statements_zip(invoices)

    if summary['succeeded'] == 0:
        return json_error('Could not generate any fee statement PDFs. Please try again, or contact support.')

    response = HttpResponse(zip_bytes, content_type='application/zip')
    filename = f"Fee-Statements-{timezone.localdate().isoformat()}.zip"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    if summary['failed']:
        response['X-Statement-Failures'] = ', '.join(summary['failed'])
    return response


@login_required
@require_POST
def api_bulk_email_invoice_statements(request):
    """
    Email the fee statement for every invoice matching the given term/class
    filters to its student's parent. Best-effort per invoice -- returns a
    summary of how many sent successfully.
    """
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return json_error('Invalid request.')

    invoices = list(_invoices_for_bulk_statements(request, data))
    if not invoices:
        return json_error('No invoices match the selected term/class.')

    from .services.statements import send_bulk_invoice_statements
    summary = send_bulk_invoice_statements(invoices)

    return JsonResponse({
        'success': True,
        'total': summary['total'],
        'sent': summary['sent'],
        'failed': summary['failed'],
        'results': summary['results'],
    })


@login_required
@require_POST
def api_generate_invoices(request):
    """Generate/repair term invoices through the centralized finance lifecycle."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    try:
        data = json.loads(request.body or '{}')
        term_id = data.get('term_id')
        school_class_ids = data.get('school_class_ids') or []
        due_date = data.get('due_date')

        if not term_id:
            return json_error('Academic term is required.')
        if not school_class_ids:
            return json_error('At least one school class is required.')
        if not due_date:
            return json_error('Invoice due date is required.')

        school = request.user.school
        term = get_object_or_404(
            AcademicTerm,
            id=term_id,
            academic_year__school=school,
        )
        school_classes = SchoolClass.objects.filter(
            id__in=school_class_ids,
            school=school,
        )
        if not school_classes.exists():
            return json_error('No valid school classes selected.')

        generated_count = 0
        existing_count = 0
        skipped_count = 0
        errors = []

        # Process students rather than pre-existing StudentFee rows. This is
        # important: the enterprise workflow can now repair a student that was
        # created after the bulk invoice run and has no StudentFee yet.
        students = (
            Student.objects
            .filter(
                school=school,
                school_class__in=school_classes,
                is_active=True,
            )
            .select_related('school_class', 'user')
            .distinct()
        )

        for student in students:
            try:
                before = Invoice.objects.filter(
                    school=school,
                    student=student,
                    academic_term=term,
                ).exists()

                invoice = ensure_student_term_invoice(
                    student,
                    created_by=request.user,
                    academic_term=term,
                    due_date=due_date,
                )

                if invoice:
                    if before:
                        existing_count += 1
                    else:
                        generated_count += 1
                else:
                    skipped_count += 1

            except Exception as exc:
                errors.append(f'{student}: {exc}')
                logger = __import__('logging').getLogger(__name__)
                logger.exception(
                    'Term invoice generation failed for student %s.',
                    student,
                )

        message_parts = []
        if generated_count:
            message_parts.append(f'✅ {generated_count} invoice(s) generated.')
        if existing_count:
            message_parts.append(f'ℹ️ {existing_count} invoice(s) already existed.')
        if skipped_count:
            message_parts.append(f'⚠️ {skipped_count} student(s) were not eligible for invoicing.')
        if errors:
            message_parts.append(f'❌ {len(errors)} student(s) failed.')

        if not message_parts:
            message_parts.append('No students were found for the selected classes.')

        return JsonResponse({
            'success': True,
            'message': ' '.join(message_parts),
            'generated': generated_count,
            'existing': existing_count,
            'skipped': skipped_count,
            'errors': errors[:20],
        })

    except json.JSONDecodeError:
        return json_error('Invalid JSON request.')
    except Exception as exc:
        return json_error(str(exc), status=500)


# ============================================================================
# STUDENT FINANCIAL ACCOUNT
# ============================================================================

# finance/views.py - Fixed student_financial_account view

@login_required
def student_financial_account(request, student_id):
    """Complete financial account for one student with base fee and add-on breakdown for new students."""
    school = request.user.school

    student = get_object_or_404(
        Student.objects.select_related('user', 'school_class', 'school_class__grade_level'),
        id=student_id,
        school=school,
    )

    # IMPORTANT: Create ledger entries for any approved fees that don't have them
    from .services.fee_preparation import create_ledger_entries_for_approved_fees
    create_ledger_entries_for_approved_fees(school, student=student)

    # Get ledger entries with proper ordering
    ledger_entries = list(
        StudentFinancialLedger.objects
            .filter(school=school, student=student)
            .select_related('academic_term', 'invoice', 'payment', 'created_by')
            .order_by('-transaction_date', '-created_at')  # Most recent first
    )

    # Calculate totals from ledger
    total_debits = StudentFinancialLedger.objects.filter(
        school=school,
        student=student,
        side='DEBIT'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    total_credits = StudentFinancialLedger.objects.filter(
        school=school,
        student=student,
        side='CREDIT'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Current balance
    balance = total_debits - total_credits

    # Determine balance status
    if balance > Decimal('0.00'):
        balance_status = 'OUTSTANDING'
    elif balance < Decimal('0.00'):
        balance_status = 'CREDIT'
    else:
        balance_status = 'SETTLED'

    # Get current term
    from .services.auto_invoicing import get_current_term
    current_term = get_current_term(school)

    # Calculate current term balance
    current_term_balance = Decimal('0.00')
    if current_term:
        current_term_balance = StudentFinancialLedger.objects.filter(
            school=school,
            student=student,
            academic_term=current_term
        ).aggregate(
            debits=Sum('amount', filter=models.Q(side='DEBIT')),
            credits=Sum('amount', filter=models.Q(side='CREDIT'))
        )
        current_term_balance = (current_term_balance['debits'] or Decimal('0.00')) - (
                    current_term_balance['credits'] or Decimal('0.00'))

    # Get invoice counts
    invoice_count = Invoice.objects.filter(school=school, student=student).count()
    unpaid_invoices = Invoice.objects.filter(school=school, student=student, status='UNPAID').count()
    paid_invoices = Invoice.objects.filter(school=school, student=student, status='PAID').count()

    # ============================================================
    # CURRENT-TERM FEE BREAKDOWN
    # ============================================================
    # The term enrollment record is the source of truth. A student's
    # global is_new_student flag is deliberately NOT used here.
    from .services.fee_preparation import get_applicable_class_addons

    enrollment = None
    if current_term:
        enrollment = (
            StudentFeeEnrollment.objects
            .filter(student=student, academic_term=current_term)
            .select_related('enrollment_type')
            .first()
        )

    is_new_student = bool(
        enrollment
        and enrollment.enrollment_type
        and enrollment.enrollment_type.code == 'NEW'
    )

    student_fee = None
    if current_term:
        student_fee = (
            StudentFee.objects
            .filter(
                school=school,
                student=student,
                academic_term=current_term,
            )
            .select_related('fee_structure', 'fee_structure__school_class')
            .prefetch_related('items__fee_category')
            .first()
        )

    base_fee_amount = Decimal('0.00')
    addon_amount = Decimal('0.00')
    total_fee_amount = Decimal('0.00')
    addon_items = []

    if student_fee:
        base_fee_amount = student_fee.base_amount or Decimal('0.00')

        # Only NEW enrollment records can receive add-ons flagged
        # apply_to_new_students_only=True.
        if is_new_student:
            applicable = get_applicable_class_addons(student, current_term)
            allowed_names = {
                str(addon.get('addon_name', '')).strip()
                for addon in applicable
                if addon.get('apply_to_new_students_only')
            }

            class_name = student.school_class.name if student.school_class else ''
            suffix = f" - {class_name}" if class_name else ''

            for item in student_fee.items.all():
                description = (item.description or '').strip()
                is_new_addon = False

                if suffix and description.endswith(suffix):
                    addon_name = description[:-len(suffix)].strip()
                    is_new_addon = addon_name in allowed_names

                if is_new_addon:
                    amount = item.final_amount or Decimal('0.00')
                    addon_amount += amount
                    addon_items.append({
                        'description': description,
                        'amount': amount,
                        'category': item.fee_category.name,
                    })

        total_fee_amount = base_fee_amount + addon_amount

    context = {
        'student': student,
        'ledger_entries': ledger_entries,
        'total_debits': total_debits,
        'total_credits': total_credits,
        'balance': balance,
        'balance_status': balance_status,
        'current_term': current_term,
        'current_term_balance': current_term_balance,
        'invoice_count': invoice_count,
        'unpaid_invoices': unpaid_invoices,
        'paid_invoices': paid_invoices,
        'can_manage': user_can_manage_finance(request.user),
        # New context variables for fee breakdown
        'is_new_student': is_new_student,
        'base_fee_amount': base_fee_amount,
        'addon_amount': addon_amount,
        'total_fee_amount': total_fee_amount,
        'addon_items': addon_items,
    }

    return render(request, 'finance/student_financial_account.html', context)


# ============================================================================
# API: STUDENT BALANCE
# ============================================================================

@login_required
def api_student_balance(request, student_id):
    """Lightweight API for retrieving a student's financial balance."""
    school = request.user.school
    student = get_object_or_404(Student, id=student_id, school=school)

    balance = get_student_balance(student=student)

    if balance > Decimal('0.00'):
        status = 'OUTSTANDING'
    elif balance < Decimal('0.00'):
        status = 'CREDIT'
    else:
        status = 'SETTLED'

    return JsonResponse({
        'success': True,
        'student_id': str(student.id),
        'balance': str(balance),
        'status': status,
        'is_outstanding': balance > Decimal('0.00'),
        'has_credit': balance < Decimal('0.00'),
        'is_settled': balance == Decimal('0.00'),
    })


# ============================================================================
# PREPARED STUDENT FEES LIST VIEW
# ============================================================================

@login_required
def student_fees_list_view(request):
    """View all prepared student fees with new-student add-on totals."""

    school = request.user.school
    if not school:
        messages.error(request, "No school associated with your account.")
        return redirect('dashboard')

    student_fees = (
        StudentFee.objects
        .filter(school=school)
        .select_related(
            'student',
            'student__user',
            'academic_term',
            'student__school_class',
        )
        .prefetch_related('items__fee_category')
        .order_by('-created_at')
    )

    # Optional status filtering
    status_filter = request.GET.get('status')
    if status_filter:
        student_fees = student_fees.filter(status=status_filter)

    # Search filtering
    search_query = request.GET.get('search', '').strip()
    if search_query:
        student_fees = student_fees.filter(
            Q(student__user__first_name__icontains=search_query) |
            Q(student__user__last_name__icontains=search_query) |
            Q(student__admission_number__icontains=search_query)
        )

    # Status counts
    total_count = student_fees.count()
    draft_count = student_fees.filter(status='DRAFT').count()
    prepared_count = student_fees.filter(status='PREPARED').count()
    approved_count = student_fees.filter(status='APPROVED').count()
    invoiced_count = student_fees.filter(status='INVOICED').count()
    cancelled_count = student_fees.filter(status='CANCELLED').count()

    # Base amount is stored on StudentFee. The display final amount for this
    # page is intentionally:
    #
    #     Base Amount + New Student Add-ons
    #
    # This keeps returning students at base amount only and ensures new
    # students show both the class base fee and the applicable new-student
    # add-ons.
    total_base = (
        student_fees.aggregate(total=Sum('base_amount'))['total']
        or Decimal('0.00')
    )

    # Pagination
    page_obj = paginate_queryset(student_fees, request)
    paginator = page_obj.paginator

    page_fees = list(page_obj.object_list)

    # ------------------------------------------------------------------
    # Identify which students are NEW for the relevant academic term.
    # ------------------------------------------------------------------
    enrollment_map = {}

    if page_fees:
        student_ids = {fee.student_id for fee in page_fees}
        term_ids = {fee.academic_term_id for fee in page_fees}

        enrollments = (
            StudentFeeEnrollment.objects
            .filter(
                school=school,
                student_id__in=student_ids,
                academic_term_id__in=term_ids,
            )
            .select_related('enrollment_type')
        )

        enrollment_map = {
            (enrollment.student_id, enrollment.academic_term_id): enrollment
            for enrollment in enrollments
        }

    # ------------------------------------------------------------------
    # Get ONLY class add-ons that are configured for new students.
    #
    # StudentFeeItem does not currently contain a direct addon_structure FK,
    # so prepared add-on lines are identified using the same description
    # format used by fee_preparation.py:
    #
    #     "{addon.name} - {school_class.name}"
    # ------------------------------------------------------------------
    new_student_addon_names = set(
        ClassAddOnStructure.objects.filter(
            school=school,
            is_active=True,
            apply_to_new_students_only=True,
        ).values_list('name', flat=True)
    )

    total_addons = Decimal('0.00')
    display_total_final = Decimal('0.00')

    for fee in page_fees:
        enrollment = enrollment_map.get(
            (fee.student_id, fee.academic_term_id)
        )

        enrollment_is_new = bool(
            enrollment
            and getattr(enrollment.enrollment_type, 'code', None) == 'NEW'
        )

        # IMPORTANT: eligibility is determined ONLY by the enrollment record
        # for this student and this academic term. Do NOT fall back to the
        # student's global is_new_student flag, because that flag can remain
        # True and would incorrectly charge add-ons to returning/existing
        # students.
        is_new_student = enrollment_is_new

        fee.is_new_student_for_fee = is_new_student
        fee.new_student_addon_total = Decimal('0.00')

        # Only NEW students are allowed to contribute to the Add-ons column.
        if is_new_student and fee.student.school_class_id:
            class_suffix = f" - {fee.student.school_class.name}"

            for item in fee.items.all():
                description = (item.description or '').strip()

                if not description.endswith(class_suffix):
                    continue

                addon_name = description[:-len(class_suffix)].strip()

                if addon_name in new_student_addon_names:
                    fee.new_student_addon_total += (
                        item.final_amount or Decimal('0.00')
                    )

        # Final display amount required by this page:
        # Base Amount + applicable New Student Add-ons.
        fee.display_final_amount = (
            (fee.base_amount or Decimal('0.00'))
            + fee.new_student_addon_total
        )

        total_addons += fee.new_student_addon_total
        display_total_final += fee.display_final_amount

    context = {
        'student_fees': page_obj,
        'selected_status': status_filter or '',
        'search': search_query,
        'total_count': total_count,
        'draft_count': draft_count,
        'prepared_count': prepared_count,
        'approved_count': approved_count,
        'invoiced_count': invoiced_count,
        'cancelled_count': cancelled_count,
        'total_base': total_base,
        'total_addons': total_addons,
        'total_final': display_total_final,
        'can_manage': user_can_manage_finance(request.user),
        'active_tab': 'finance',
    }

    return render(request, 'finance/student_fees_list.html', context)


# ============================================================================
# FEE PREVIEW API
# ============================================================================

# finance/views.py - Update api_fee_preview

@login_required
def api_fee_preview(request):
    """
    Preview fees for a student based on enrollment type and class.
    Used during student registration.
    """
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', 403)

    school = request.user.school
    enrollment_type_id = request.GET.get('enrollment_type')
    class_id = request.GET.get('class_id')

    if not enrollment_type_id or not class_id:
        return json_error('Enrollment type and class are required.')

    try:
        from students.models import StudentEnrollmentType
        from academics.models import SchoolClass
        from finance.models import (
            EnrollmentFeePackage, FeeStructure, FeeAddOnStructure,
            ClassAddOnStructure, ClassAddOnItem
        )

        enrollment_type = get_object_or_404(
            StudentEnrollmentType,
            id=enrollment_type_id,
            school=school
        )
        school_class = get_object_or_404(
            SchoolClass,
            id=class_id,
            school=school
        )

        # Get current active term
        from school.models import AcademicTerm
        current_term = AcademicTerm.objects.filter(
            academic_year__school=school,
            academic_year__is_active=True,
            is_active=True
        ).first()

        if not current_term:
            return json_error('No active term found.')

        # Get term number
        from finance.services.fee_preparation import get_term_number
        term_number = get_term_number(current_term)

        # Get the fee structure
        package = EnrollmentFeePackage.objects.filter(
            school=school,
            enrollment_type=enrollment_type,
            academic_term=current_term,
            is_active=True
        ).order_by('-is_default', '-created_at').first()

        if package and package.fee_structure:
            fee_structure = package.fee_structure
        else:
            fee_structure = FeeStructure.objects.filter(
                school=school,
                academic_term=current_term,
                school_class=school_class
            ).first()

        if not fee_structure:
            return json_error('No fee structure found for this class and term.')

        # Build preview items
        items = []
        total = 0

        # Add main fee structure items
        for item in fee_structure.items.all():
            amount = float(item.amount)
            items.append({
                'description': f"{item.fee_category.name} - {current_term.name}",
                'amount': amount,
                'category': item.fee_category.name,
                'type': 'Base Fee'
            })
            total += amount

        # ============================================================
        # CLASS-BASED ADD-ONS
        # ============================================================
        class_addons = ClassAddOnStructure.objects.filter(
            school=school,
            is_active=True,
        ).prefetch_related('items')

        for addon in class_addons:
            # Check term applicability
            if addon.term_type == 'FIRST' and term_number != 1:
                continue
            elif addon.term_type == 'SECOND' and term_number != 2:
                continue
            elif addon.term_type == 'THIRD' and term_number != 3:
                continue
            elif addon.term_type == 'CUSTOM' and term_number not in {
                int(value) for value in (addon.custom_terms or []) if str(value).isdigit()
            }:
                continue

            # Check new student restriction
            if addon.apply_to_new_students_only and enrollment_type.code != 'NEW':
                continue

            # Find the add-on item for this class
            addon_item = addon.items.filter(
                school_class=school_class,
                is_active=True
            ).first()

            if not addon_item:
                addon_item = addon.items.filter(
                    grade_level=school_class.grade_level,
                    school_class__isnull=True,
                    is_active=True
                ).first()

            if not addon_item:
                addon_item = addon.items.filter(
                    grade_level__isnull=True,
                    school_class__isnull=True,
                    is_active=True
                ).first()

            if addon_item:
                amount = float(addon_item.get_amount_for_term(term_number))
                items.append({
                    'description': f"{addon.name} - {school_class.name}",
                    'amount': amount,
                    'category': addon.fee_category.name,
                    'type': 'Class Add-on',
                    'is_required': addon.is_required,
                })
                total += amount

        # ============================================================
        # LEGACY ADD-ONS (for backward compatibility)
        # ============================================================
        legacy_addons = FeeAddOnStructure.objects.filter(
            school=school,
            academic_term=current_term,
            is_active=True,
        ).prefetch_related('items__fee_category')

        for addon in legacy_addons:
            should_apply = True
            if addon.apply_to_new_students_only and enrollment_type.code != 'NEW':
                should_apply = False

            if should_apply:
                for item in addon.items.all():
                    # Check if this add-on already exists from class addons
                    already_exists = any(
                        i['description'] == f"{item.fee_category.name} (Add-on - {addon.name})"
                        for i in items
                    )
                    if not already_exists:
                        amount = float(item.amount)
                        items.append({
                            'description': f"{item.fee_category.name} (Add-on)",
                            'amount': amount,
                            'category': item.fee_category.name,
                            'type': 'Legacy Add-on',
                            'is_required': False,
                        })
                        total += amount

        # Calculate discount if applicable
        discount_amount = 0
        if package and package.discount_percentage > 0:
            discount_amount = (total * package.discount_percentage) / 100
            total = total - discount_amount

        return JsonResponse({
            'success': True,
            'total': round(total, 2),
            'discount': round(discount_amount, 2),
            'items': items,
            'enrollment_type': enrollment_type.get_name_display(),
            'enrollment_type_code': enrollment_type.code,
            'term': current_term.name,
            'term_number': term_number,
            'package_name': package.name if package else 'Standard Fee Structure',
            'has_package': package is not None,
            'class_name': school_class.name,
            'grade_name': school_class.grade_level.name,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return json_error(str(e))


# finance/views.py - Add these new views

# ============================================================================
# CLASS-BASED ADD-ON VIEWS
# ============================================================================

@login_required
def class_addon_list(request):
    """Backward-compatible alias for the unified fee add-on list."""
    return fee_addon_list(request)



def _class_addon_context(school, mode, school_class=None):
    """
    Context for the class-based add-on form.

    Unlike the old implementation, editing is keyed by *school class*, not by
    a single ClassAddOnStructure — a class can have several add-on items and
    each one has its own ClassAddOnStructure (its own name/category/
    description). All of a class's items are loaded here so every item's own
    fields are preserved when the form is edited.
    """
    school_classes = (
        SchoolClass.objects.filter(school=school)
            .select_related('grade_level')
            .order_by('grade_level__order', 'name')
    )

    existing_items = []
    selected_school_class = None
    representative_structure = None  # used only to pre-fill shared billing settings

    if school_class:
        existing_items = list(
            ClassAddOnItem.objects.filter(
                addon_structure__school=school,
                school_class=school_class,
            )
            .select_related('school_class', 'grade_level', 'addon_structure')
            .order_by('addon_structure__name')
        )
        selected_school_class = school_class.id
        if existing_items:
            representative_structure = existing_items[0].addon_structure
        else:
            # No items yet for this class — give the template a safe,
            # unsaved default so `addon.term_type` etc. don't hit None.
            representative_structure = ClassAddOnStructure(
                term_type='ALL',
                custom_terms=[],
                apply_to_new_students_only=False,
                is_required=False,
                is_optional=False,
                is_active=True,
            )

    return {
        'mode': mode,
        'addon': representative_structure,
        'class_id': school_class.id if school_class else None,
        'existing_items': existing_items,
        'selected_school_class': selected_school_class,
        'fee_categories': FeeCategory.objects.filter(
            school=school, is_active=True
        ).order_by('name'),
        'school_classes': school_classes,
        'action_url': (
            'finance:class_addon_create'
            if mode == 'create'
            else 'finance:class_addon_edit'
        ),
    }


def _parse_class_addon_rows(request, school):
    """
    Parse multiple add-on items submitted for one school class.

    Each row carries its OWN name, fee category, amount and description —
    these are per-item fields and must never be collapsed down to a single
    row's values. ``item_id`` (blank for new rows) is used by the edit view
    to know which existing ClassAddOnItem a row corresponds to.
    """
    school_class_id = request.POST.get('school_class', '').strip()
    if not school_class_id:
        raise ValueError('Please select a school class.')

    school_class = get_object_or_404(
        SchoolClass.objects.select_related('grade_level'),
        id=school_class_id,
        school=school,
    )

    names = request.POST.getlist('item_names')
    category_ids = request.POST.getlist('item_categories')
    amounts = request.POST.getlist('item_amounts')
    descriptions = request.POST.getlist('item_descriptions')
    item_ids = request.POST.getlist('item_ids')

    rows = []
    max_len = max(len(names), len(category_ids), len(amounts))

    for index in range(max_len):
        name = names[index].strip() if index < len(names) else ''
        category_id = category_ids[index].strip() if index < len(category_ids) else ''
        raw_amount = amounts[index].strip() if index < len(amounts) else ''
        description = descriptions[index].strip() if index < len(descriptions) else ''
        item_id = item_ids[index].strip() if index < len(item_ids) else ''

        # Ignore fully empty rows (e.g. a blank row left over in the UI)
        if not name and not category_id and not raw_amount:
            continue

        if not name or not category_id or not raw_amount:
            raise ValueError('Each add-on item must have a name, fee category and amount.')

        amount = decimal_from_value(raw_amount)
        if amount <= ZERO:
            raise ValueError('Each add-on amount must be greater than zero.')

        category = get_object_or_404(
            FeeCategory,
            id=category_id,
            school=school,
            is_active=True,
        )

        # Reject duplicate items *within this submission* (same name, same
        # category) so a copy/paste mistake doesn't silently create two
        # identical add-ons in one save.
        for existing_row in rows:
            if (existing_row['name'].lower() == name.lower()
                    and existing_row['fee_category'].id == category.id):
                raise ValueError(f'"{name}" was added more than once in this form.')

        rows.append({
            'name': name,
            'fee_category': category,
            'amount': amount,
            'description': description,
            'item_id': item_id,
        })

    if not rows:
        raise ValueError('Add at least one add-on item.')

    return school_class, rows


def _get_or_create_addon_structure(school, name, fee_category, description, common_data):
    """
    Find an existing ClassAddOnStructure for this school by name
    (case-insensitive, since ClassAddOnStructure.name is unique per school),
    or create a new one. The structure's category/description/billing
    settings are kept in sync with what was just submitted.
    """
    structure = ClassAddOnStructure.objects.filter(
        school=school, name__iexact=name
    ).first()

    if structure:
        structure.name = name
        structure.fee_category = fee_category
        structure.description = description
        for field, value in common_data.items():
            setattr(structure, field, value)
        structure.save()
    else:
        structure = ClassAddOnStructure.objects.create(
            school=school,
            name=name,
            fee_category=fee_category,
            description=description,
            **common_data,
        )

    return structure


def _class_addon_common_data(request):
    """Extract common add-on structure data from request."""
    term_type = request.POST.get('term_type', 'ALL').strip().upper()
    if term_type not in dict(ClassAddOnStructure.TERM_CHOICES):
        raise ValueError('Invalid billing schedule.')

    custom_terms = request.POST.getlist('custom_terms')
    try:
        custom_terms = sorted({int(value) for value in custom_terms if value in {'1', '2', '3'}})
    except (TypeError, ValueError):
        custom_terms = []

    if term_type == 'CUSTOM' and not custom_terms:
        raise ValueError('Select at least one custom term.')

    return {
        'term_type': term_type,
        'custom_terms': custom_terms if term_type == 'CUSTOM' else [],
        'apply_to_new_students_only': request.POST.get('apply_to_new_students_only') == 'on',
        'is_required': request.POST.get('is_required') == 'on',
        'is_active': request.POST.get('is_active') == 'on',
    }


@login_required
@require_http_methods(['GET', 'POST'])
def class_addon_create(request):
    """
    Create one or more class add-on items in a single batch.

    Each submitted row becomes its own ClassAddOnStructure (own name, fee
    category, description) with one ClassAddOnItem priced for the chosen
    class — matching how every other row in the app already renders each
    item (see class_addon_form_modal.html, which reads
    ``item.addon_structure.name`` / ``.fee_category`` / ``.description`` per
    item). If a row's name matches an existing add-on for this school, that
    add-on is reused instead of creating a near-duplicate, and if that
    add-on already has pricing for the chosen class the row is skipped as a
    duplicate rather than silently creating a second copy.
    """
    if not user_can_manage_finance(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Permission denied.', 403)
        messages.error(request, 'Permission denied.')
        return redirect('finance:fee_addon_list')

    school = request.user.school
    if request.method == 'GET':
        return render(request, 'finance/class_addon_form_modal.html', _class_addon_context(school, 'create'))

    try:
        school_class, rows = _parse_class_addon_rows(request, school)
        common_data = _class_addon_common_data(request)

        created_count = 0
        skipped_names = []

        with transaction.atomic():
            for row in rows:
                structure = _get_or_create_addon_structure(
                    school, row['name'], row['fee_category'], row['description'], common_data,
                )

                # Duplicate protection: don't re-price the same add-on twice
                # for the same class.
                already_priced = ClassAddOnItem.objects.filter(
                    addon_structure=structure,
                    school_class=school_class,
                ).exists()

                if already_priced:
                    skipped_names.append(row['name'])
                    continue

                ClassAddOnItem.objects.create(
                    addon_structure=structure,
                    school=school,
                    school_class=school_class,
                    grade_level=school_class.grade_level,
                    amount=row['amount'],
                )
                created_count += 1

    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error(str(exc))
        messages.error(request, f'Error creating class add-ons: {exc}')
        return redirect('finance:fee_addon_list')

    if created_count:
        message = f'{created_count} add-on item(s) created successfully for {school_class.name}.'
    else:
        message = f'No new items created — all submitted add-ons already exist for {school_class.name}.'
    if skipped_names:
        message += f' Skipped duplicate(s): {", ".join(skipped_names)}.'

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': message,
            'created_count': created_count,
            'skipped_count': len(skipped_names),
        })
    messages.success(request, message)
    return redirect('finance:fee_addon_list')


@login_required
@require_http_methods(['GET', 'POST'])
def class_addon_edit(request, class_id):
    """
    Edit every add-on item priced for one school class.

    Editing is keyed by class (not by a single add-on) because a class can
    have several add-on items, each backed by its own ClassAddOnStructure.
    Existing rows (matched by ``item_id``) update their own structure's
    name/category/description and the item's amount; rows without an
    ``item_id`` are treated as new items (reusing a matching existing
    add-on by name if one exists, and skipped if that add-on is already
    priced for this class); items removed from the form are deleted, and
    any add-on left with no items anywhere is cleaned up.
    """
    if not user_can_manage_finance(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Permission denied.', 403)
        messages.error(request, 'Permission denied.')
        return redirect('finance:fee_addon_list')

    school = request.user.school
    school_class = get_object_or_404(
        SchoolClass.objects.select_related('grade_level'),
        id=class_id,
        school=school,
    )

    if request.method == 'GET':
        return render(
            request,
            'finance/class_addon_form_modal.html',
            _class_addon_context(school, 'edit', school_class=school_class),
        )

    try:
        posted_school_class, rows = _parse_class_addon_rows(request, school)
        common_data = _class_addon_common_data(request)

        existing_items = {
            str(item.id): item
            for item in ClassAddOnItem.objects.filter(
                addon_structure__school=school,
                school_class=school_class,
            ).select_related('addon_structure')
        }

        submitted_item_ids = set()
        updated_count = 0
        created_count = 0
        skipped_names = []

        with transaction.atomic():
            for row in rows:
                item_id = row.get('item_id', '')

                if item_id and item_id in existing_items:
                    # Update this row's OWN item and its OWN add-on
                    # structure — never another row's.
                    item = existing_items[item_id]
                    structure = item.addon_structure

                    # If renaming this row would collide with a different
                    # existing add-on, merge into that add-on instead of
                    # raising a hard database error.
                    conflict = ClassAddOnStructure.objects.filter(
                        school=school, name__iexact=row['name']
                    ).exclude(id=structure.id).first()
                    if conflict:
                        structure = conflict
                        item.addon_structure = structure

                    structure.name = row['name']
                    structure.fee_category = row['fee_category']
                    structure.description = row['description']
                    for field, value in common_data.items():
                        setattr(structure, field, value)
                    structure.save()

                    item.amount = row['amount']
                    item.school_class = posted_school_class
                    item.grade_level = posted_school_class.grade_level
                    item.save()

                    submitted_item_ids.add(item_id)
                    updated_count += 1
                else:
                    # New row - reuse a matching add-on by name if one
                    # exists, otherwise create it.
                    structure = _get_or_create_addon_structure(
                        school, row['name'], row['fee_category'], row['description'], common_data,
                    )

                    already_priced = ClassAddOnItem.objects.filter(
                        addon_structure=structure,
                        school_class=posted_school_class,
                    ).exists()
                    if already_priced:
                        skipped_names.append(row['name'])
                        continue

                    ClassAddOnItem.objects.create(
                        addon_structure=structure,
                        school=school,
                        school_class=posted_school_class,
                        grade_level=posted_school_class.grade_level,
                        amount=row['amount'],
                    )
                    created_count += 1

            # Remove items the user deleted from the form, and clean up any
            # add-on structure left with no items anywhere.
            for item_id, item in existing_items.items():
                if item_id not in submitted_item_ids:
                    structure = item.addon_structure
                    item.delete()
                    if not structure.items.exists():
                        structure.delete()

    except Exception as exc:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error(str(exc))
        messages.error(request, f'Error updating class add-ons: {exc}')
        return redirect('finance:fee_addon_list')

    message = f'{updated_count} item(s) updated, {created_count} item(s) added for {posted_school_class.name}.'
    if skipped_names:
        message += f' Skipped duplicate(s): {", ".join(skipped_names)}.'

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': message})
    messages.success(request, message)
    return redirect('finance:fee_addon_list')


@login_required
@require_POST
def class_addon_delete(request, class_id):
    """Delete every class add-on item priced for one school class."""
    if not user_can_manage_finance(request.user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return json_error('Permission denied.', 403)
        messages.error(request, 'Permission denied.')
        return redirect('finance:fee_addon_list')

    school = request.user.school
    school_class = get_object_or_404(SchoolClass, id=class_id, school=school)

    items = list(
        ClassAddOnItem.objects.filter(
            addon_structure__school=school,
            school_class=school_class,
        ).select_related('addon_structure')
    )
    count = len(items)
    structure_ids = {item.addon_structure_id for item in items}

    with transaction.atomic():
        ClassAddOnItem.objects.filter(id__in=[item.id for item in items]).delete()
        # Clean up any add-on structure that's now empty everywhere.
        for structure in ClassAddOnStructure.objects.filter(id__in=structure_ids):
            if not structure.items.exists():
                structure.delete()

    message = f'{count} add-on item(s) deleted for {school_class.name}.'
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': message, 'class_id': str(class_id)})
    messages.success(request, message)
    return redirect('finance:fee_addon_list')


@login_required
def payment_modal(request):
    """Return the payment modal content."""
    if not user_can_manage_finance(request.user):
        return HttpResponseForbidden("You don't have permission to record payments.")

    school = request.user.school
    student_id = request.GET.get('student_id')
    invoice_id = request.GET.get('invoice_id')

    # Get all invoices that are NOT paid or void
    if invoice_id:
        # Filter for specific invoice
        invoices = Invoice.objects.filter(
            school=school,
            id=invoice_id
        ).exclude(
            status='PAID'
        ).exclude(
            status='VOID'
        ).select_related('student__user', 'academic_term')
    elif student_id:
        # Filter invoices for specific student
        invoices = Invoice.objects.filter(
            school=school,
            student_id=student_id
        ).exclude(
            status='PAID'
        ).exclude(
            status='VOID'
        ).select_related('student__user', 'academic_term')
    else:
        # Show all unpaid and partially paid invoices
        invoices = Invoice.objects.filter(
            school=school
        ).exclude(
            status='PAID'
        ).exclude(
            status='VOID'
        ).select_related('student__user', 'academic_term')

    # Order by due date (oldest first)
    invoices = invoices.order_by('due_date', 'created_at')

    return render(request, 'finance/payment_modal.html', {
        'invoices': invoices,
    })


# finance/views.py - Add this new view at the end of the file

@login_required
@require_POST
def api_rebuild_class_fees(request):
    """Rebuild fees for all students in a class, including add-ons."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    try:
        data = json.loads(request.body or '{}')
        class_id = data.get('class_id')
        term_id = data.get('term_id')
        force_rebuild = data.get('force_rebuild', True)

        if not class_id:
            return json_error('Class ID is required.')

        school = request.user.school
        school_class = get_object_or_404(SchoolClass, id=class_id, school=school)

        # Get term (use active term if not specified)
        if term_id:
            academic_term = get_object_or_404(AcademicTerm, id=term_id, academic_year__school=school)
        else:
            academic_term = AcademicTerm.objects.filter(
                academic_year__school=school,
                academic_year__is_active=True,
                is_active=True
            ).first()

            if not academic_term:
                return json_error('No active term found.')

        # Prepare fees for all students in the class with add-ons
        from .services.fee_preparation import prepare_class_fees
        result = prepare_class_fees(
            school=school,
            school_class=school_class,
            academic_term=academic_term,
            prepared_by=request.user,
            force_rebuild=force_rebuild,
        )

        return JsonResponse({
            'success': True,
            'message': f'Rebuilt fees for {result["prepared_count"]} student(s) in {school_class.name}.',
            'prepared': result['prepared_count'],
            'total': result['total_students'],
            'errors': result['errors'],
        })

    except json.JSONDecodeError:
        return json_error('Invalid JSON request.')
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return json_error(str(exc), status=500)


# finance/views.py - Add this new view

@login_required
@require_POST
def api_rebuild_all_fees(request):
    """Rebuild fees for ALL students in the school."""
    if not user_can_manage_finance(request.user):
        return json_error('Permission denied.', status=403)

    school = request.user.school

    try:
        # Get active term
        academic_term = AcademicTerm.objects.filter(
            academic_year__school=school,
            academic_year__is_active=True,
            is_active=True
        ).first()

        if not academic_term:
            return json_error('No active term found.')

        # Get all students with a class
        students = Student.objects.filter(
            school=school,
            school_class__isnull=False,
            is_active=True
        ).select_related('school_class')

        total = students.count()
        updated = 0
        errors = []

        for student in students:
            try:
                with transaction.atomic():
                    from .services.fee_preparation import prepare_student_fee
                    result = prepare_student_fee(
                        student=student,
                        academic_term=academic_term,
                        prepared_by=request.user,
                        force_rebuild=True,
                        include_addons=True,
                    )
                    if result:
                        updated += 1
            except Exception as e:
                errors.append(f"{student}: {str(e)}")

        message = f'Rebuilt fees for {updated} out of {total} students.'
        if errors:
            message += f' Errors: {len(errors)}'

        return JsonResponse({
            'success': True,
            'message': message,
            'updated': updated,
            'total': total,
            'errors': errors[:10] if errors else [],
        })

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return json_error(str(exc), status=500)
