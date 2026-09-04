# finance/services/fee_preparation.py
import io
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q
from django.template.loader import render_to_string
import logging

from ..models import (
    FeeStructure,
    FeeWaiver,
    StudentFee,
    StudentFeeItem,
    Invoice,
    InvoiceLineItem,
    StudentFinancialLedger,
    FeeAddOnStructure,
    FeeAddOnItem,
    StudentFeeAdjustment,
    EnrollmentFeePackage,
    StudentFeeEnrollment,
    ClassAddOnStructure,
    ClassAddOnItem,
)
from students.models import Student, StudentEnrollmentType
from school.models import AcademicTerm

ZERO = Decimal("0.00")
logger = logging.getLogger(__name__)


class FeePreparationError(Exception):
    """Raised when a student fee cannot be prepared."""
    pass


def get_student_arrears(student, academic_term):
    """Return outstanding balances from previous invoices."""
    previous_invoices = (
        Invoice.objects
            .filter(
            student=student,
            school=student.school,
        )
            .exclude(academic_term=academic_term)
            .exclude(status='VOID')
    )

    total_due = ZERO
    total_paid = ZERO

    for invoice in previous_invoices:
        total_due += invoice.total_amount
        total_paid += invoice.amount_paid

    return max(total_due - total_paid, ZERO)


def get_student_waivers(student, academic_term):
    """Return active waivers applicable to the student."""
    return FeeWaiver.objects.filter(
        school=student.school,
        student=student,
        is_active=True,
    ).filter(
        Q(academic_term=academic_term) | Q(academic_term__isnull=True)
    )


def calculate_item_discount(item, waivers):
    """Calculate the total waiver applicable to one fee category."""
    discount = ZERO
    applicable_waivers = waivers.filter(fee_category=item.fee_category)

    for waiver in applicable_waivers:
        discount += waiver.amount_for(item.amount)

    return min(discount, item.amount)


def calculate_whole_invoice_discount(base_amount, waivers):
    """Calculate waivers that apply to the whole student's fee."""
    discount = ZERO
    whole_invoice_waivers = waivers.filter(fee_category__isnull=True)

    for waiver in whole_invoice_waivers:
        discount += waiver.amount_for(base_amount)

    return min(discount, base_amount)


def get_student_fee_structure(student, academic_term):
    """Find the active fee structure for the student's current class."""
    if not student.school_class:
        raise FeePreparationError(f"{student} is not assigned to a school class.")

    try:
        return (
            FeeStructure.objects
                .select_related('school_class', 'academic_term')
                .prefetch_related('items__fee_category')
                .get(
                school=student.school,
                school_class=student.school_class,
                academic_term=academic_term,
            )
        )
    except FeeStructure.DoesNotExist:
        raise FeePreparationError(
            f"No fee structure exists for {student.school_class.name} for {academic_term.name}."
        )


def get_student_enrollment_type(student, academic_term):
    """
    Return the enrollment type that applies to this student for this term.

    Priority:
    1. StudentFeeEnrollment record (source of truth)
    2. Student's selected enrollment_type
    3. Fallback based on is_new_student flag
    """
    if not student or not academic_term:
        return None

    # Check StudentFeeEnrollment first (source of truth)
    fee_enrollment = (
        StudentFeeEnrollment.objects
            .select_related('enrollment_type')
            .filter(student=student, academic_term=academic_term)
            .first()
    )
    if fee_enrollment:
        return fee_enrollment.enrollment_type

    # Check if student has a previous enrollment in any term
    has_previous_enrollment = StudentFeeEnrollment.objects.filter(
        student=student
    ).exclude(
        academic_term=academic_term
    ).exists()

    if has_previous_enrollment:
        returning = StudentEnrollmentType.objects.filter(
            school=student.school, code='RETURNING', is_active=True
        ).first()
        if returning:
            return returning

    # Use student's enrollment_type if set
    if student.enrollment_type_id:
        return student.enrollment_type

    # Fallback to is_new_student flag
    fallback_code = 'NEW' if getattr(student, 'is_new_student', False) else 'RETURNING'
    return StudentEnrollmentType.objects.filter(
        school=student.school, code=fallback_code, is_active=True
    ).first()


def ensure_student_fee_enrollment(student, academic_term, applied_by=None):
    """Create the immutable term enrollment record used by the fee engine."""
    existing = StudentFeeEnrollment.objects.filter(
        student=student, academic_term=academic_term
    ).select_related('enrollment_type', 'package_used').first()
    if existing:
        return existing

    enrollment_type = get_student_enrollment_type(student, academic_term)
    if not enrollment_type:
        raise FeePreparationError('No active enrollment type is available for this student.')

    package = EnrollmentFeePackage.objects.filter(
        school=student.school,
        enrollment_type=enrollment_type,
        academic_term=academic_term,
        is_active=True,
    ).order_by('-is_default', '-created_at').first()

    return StudentFeeEnrollment.objects.create(
        school=student.school,
        student=student,
        academic_term=academic_term,
        enrollment_type=enrollment_type,
        package_used=package,
        is_automatic=True,
        applied_by=applied_by,
    )


def get_enrollment_fee_package(student, academic_term):
    """Get the fee package for a student based on their enrollment type."""
    if not student or not academic_term:
        return None

    enrollment_type = get_student_enrollment_type(student, academic_term)
    if not enrollment_type:
        return None

    # Try to get the default package for this enrollment type
    package = EnrollmentFeePackage.objects.filter(
        school=student.school,
        enrollment_type=enrollment_type,
        academic_term=academic_term,
        is_active=True,
        is_default=True
    ).first()

    if not package:
        # Try any active package
        package = EnrollmentFeePackage.objects.filter(
            school=student.school,
            enrollment_type=enrollment_type,
            academic_term=academic_term,
            is_active=True
        ).first()

    return package


def get_student_adjustments(student_fee):
    """Get active adjustments for a student fee."""
    return StudentFeeAdjustment.objects.filter(
        student_fee=student_fee,
        is_active=True,
    )


def get_term_number(academic_term):
    """Get the term number (1, 2, or 3) from an AcademicTerm."""
    if not academic_term:
        return 1

    terms = academic_term.academic_year.terms.order_by('start_date')
    term_list = list(terms)

    for idx, term in enumerate(term_list, 1):
        if term.id == academic_term.id:
            return idx

    return 1


# ============================================================
# CLASS ADD-ON FUNCTIONS
# ============================================================


def get_applicable_legacy_addons(student, academic_term):
    """Legacy add-ons from FeeAddOnStructure (for backward compatibility)."""
    addon_items = []

    addon_structures = FeeAddOnStructure.objects.filter(
        school=student.school,
        academic_term=academic_term,
        is_active=True,
    ).prefetch_related('items__fee_category')

    for addon in addon_structures:
        should_apply = True

        if addon.apply_to_new_students_only:
            enrollment_type = get_student_enrollment_type(student, academic_term)
            is_new = bool(
                enrollment_type
                and getattr(enrollment_type, 'code', None) == 'NEW'
            )
            if not is_new:
                should_apply = False

        if should_apply:
            for item in addon.items.all():
                addon_items.append({
                    'fee_category': item.fee_category,
                    'amount': item.amount,
                    'description': item.description or f"{item.fee_category.name} (Add-on)",
                    'addon_name': addon.name,
                    'source': 'legacy_addon'
                })

    return addon_items


@transaction.atomic
def prepare_student_fee(
        student,
        academic_term,
        prepared_by=None,
        force_rebuild=False,
        include_addons=True,
):
    """Prepare or rebuild the fee for one student."""
    if not student.school:
        raise FeePreparationError("Student does not belong to a school.")

    # Get the fee structure (from enrollment package or class default)
    fee_structure = None
    enrollment_type = None
    package = None

    # Check if there's an enrollment package
    package = get_enrollment_fee_package(student, academic_term)
    if package and package.fee_structure:
        fee_structure = package.fee_structure
        enrollment_type = package.enrollment_type
    else:
        # Fall back to class-based fee structure
        fee_structure = get_student_fee_structure(student, academic_term)
        enrollment_type = get_student_enrollment_type(student, academic_term)

    if not fee_structure:
        raise FeePreparationError(
            f"No fee structure found for {student.school_class.name} for {academic_term.name}."
        )

    existing = (
        StudentFee.objects
            .filter(
            school=student.school,
            student=student,
            fee_structure=fee_structure,
        )
            .first()
    )

    if existing:
        if existing.status in ['APPROVED', 'INVOICED'] and not force_rebuild:
            raise FeePreparationError(
                f"Fee for {student} is already {existing.get_status_display().lower()} and cannot be rebuilt."
            )
        if existing.status == 'CANCELLED':
            raise FeePreparationError(f"Fee preparation for {student} has been cancelled.")
        student_fee = existing
        if force_rebuild:
            student_fee.items.all().delete()
            student_fee.base_amount = ZERO
            student_fee.discount_amount = ZERO
            student_fee.adjustment_amount = ZERO
            student_fee.arrears_amount = ZERO
            student_fee.final_amount = ZERO
    else:
        student_fee = StudentFee.objects.create(
            school=student.school,
            student=student,
            fee_structure=fee_structure,
            academic_term=academic_term,
            prepared_by=prepared_by,
            status='DRAFT',
        )

    waivers = get_student_waivers(student, academic_term)
    base_amount = ZERO
    total_discount = ZERO

    # ============================================================
    # MAIN FEE STRUCTURE ITEMS
    # ============================================================
    for structure_item in fee_structure.items.all():
        category = structure_item.fee_category
        standard_amount = structure_item.amount

        # Check if optional fee should be included
        include_item = True
        if category.is_optional:
            if category.category_type == 'TRANSPORT':
                try:
                    subscription = student.transport
                    if not subscription.is_active:
                        include_item = False
                except Exception:
                    include_item = False

        if not include_item:
            continue

        discount = calculate_item_discount(structure_item, waivers)
        final_amount = max(standard_amount - discount, ZERO)

        StudentFeeItem.objects.create(
            student_fee=student_fee,
            fee_category=category,
            description=f"{category.name} - {academic_term.name}",
            standard_amount=standard_amount,
            discount_amount=discount,
            adjustment_amount=ZERO,
            final_amount=final_amount,
            is_optional=category.is_optional,
            is_waived=(discount >= standard_amount and standard_amount > ZERO),
        )

        base_amount += standard_amount
        total_discount += discount

    # Apply whole-invoice waivers
    remaining_base = max(base_amount - total_discount, ZERO)
    whole_invoice_discount = calculate_whole_invoice_discount(remaining_base, waivers)
    total_discount += whole_invoice_discount

    # Apply whole invoice discount against available items
    remaining_discount = whole_invoice_discount
    if remaining_discount > ZERO:
        fee_items = list(student_fee.items.order_by('created_at'))
        for item in fee_items:
            if remaining_discount <= ZERO:
                break
            available = max(item.standard_amount - item.discount_amount, ZERO)
            applied = min(available, remaining_discount)
            if applied > ZERO:
                item.discount_amount += applied
                item.final_amount = max(item.standard_amount - item.discount_amount, ZERO)
                item.save(update_fields=['discount_amount', 'final_amount'])
                remaining_discount -= applied

    # ============================================================
    # ENROLLMENT PACKAGE DISCOUNT
    # ============================================================
    if package and package.discount_percentage > 0:
        discount_amount = (base_amount * package.discount_percentage) / 100
        total_discount += discount_amount

        remaining_package_discount = discount_amount
        if remaining_package_discount > ZERO:
            fee_items = list(student_fee.items.order_by('created_at'))
            for item in fee_items:
                if remaining_package_discount <= ZERO:
                    break
                available = max(item.standard_amount - item.discount_amount, ZERO)
                applied = min(available, remaining_package_discount)
                if applied > ZERO:
                    item.discount_amount += applied
                    item.final_amount = max(item.standard_amount - item.discount_amount, ZERO)
                    item.save(update_fields=['discount_amount', 'final_amount'])
                    remaining_package_discount -= applied

    # ============================================================
    # CLASS-BASED ADD-ON ITEMS
    # ============================================================
    if include_addons:
        class_addons = get_applicable_class_addons(student, academic_term)
        for addon in class_addons:
            # Check if this add-on already exists for this student
            existing_addon = student_fee.items.filter(
                fee_category=addon['fee_category'],
                description__icontains=addon['addon_name']
            ).first()

            if not existing_addon:
                StudentFeeItem.objects.create(
                    student_fee=student_fee,
                    fee_category=addon['fee_category'],
                    description=addon['description'],
                    standard_amount=addon['amount'],
                    discount_amount=ZERO,
                    adjustment_amount=ZERO,
                    final_amount=addon['amount'],
                    is_optional=not addon['is_required'],
                    is_waived=False,
                )
            else:
                # Update existing add-on amount if it changed
                if existing_addon.standard_amount != addon['amount']:
                    existing_addon.standard_amount = addon['amount']
                    existing_addon.final_amount = addon['amount']
                    existing_addon.save(update_fields=['standard_amount', 'final_amount'])

    # ============================================================
    # LEGACY ADD-ON ITEMS (for backward compatibility)
    # ============================================================
    if include_addons:
        legacy_addons = get_applicable_legacy_addons(student, academic_term)
        for addon in legacy_addons:
            existing_addon = student_fee.items.filter(
                fee_category=addon['fee_category'],
                description__icontains=addon['addon_name']
            ).first()

            if not existing_addon:
                StudentFeeItem.objects.create(
                    student_fee=student_fee,
                    fee_category=addon['fee_category'],
                    description=addon['description'],
                    standard_amount=addon['amount'],
                    discount_amount=ZERO,
                    adjustment_amount=ZERO,
                    final_amount=addon['amount'],
                    is_optional=True,
                    is_waived=False,
                )

    # ============================================================
    # MANUAL ADJUSTMENTS
    # ============================================================
    adjustments = get_student_adjustments(student_fee)
    total_adjustments = ZERO

    for adjustment in adjustments:
        existing_adj = student_fee.items.filter(
            fee_category=adjustment.fee_category,
            description__icontains=adjustment.description
        ).first()

        if not existing_adj:
            adj_amount = adjustment.amount if adjustment.adjustment_type != 'DISCOUNT' else -adjustment.amount
            StudentFeeItem.objects.create(
                student_fee=student_fee,
                fee_category=adjustment.fee_category,
                description=adjustment.description,
                standard_amount=abs(adj_amount),
                discount_amount=ZERO if adj_amount > 0 else abs(adj_amount),
                adjustment_amount=adj_amount,
                final_amount=adj_amount if adj_amount > 0 else ZERO,
                is_optional=True,
                is_waived=adj_amount < 0,
            )
            if adj_amount > 0:
                total_adjustments += adj_amount

    # ============================================================
    # FINAL CALCULATION - Sum ALL items including add-ons
    # ============================================================
    # Force a refresh of the items queryset to include newly created items
    all_items = student_fee.items.all()
    current_items_total = all_items.aggregate(total=Sum('final_amount'))['total'] or ZERO
    arrears = get_student_arrears(student, academic_term)

    student_fee.base_amount = base_amount
    student_fee.discount_amount = total_discount
    student_fee.adjustment_amount = total_adjustments
    student_fee.arrears_amount = arrears
    student_fee.final_amount = max(current_items_total + arrears, ZERO)
    student_fee.status = 'PREPARED'

    if prepared_by:
        student_fee.prepared_by = prepared_by

    student_fee.save(update_fields=[
        'base_amount', 'discount_amount', 'adjustment_amount',
        'arrears_amount', 'final_amount', 'status', 'prepared_by', 'updated_at'
    ])

    # ============================================================
    # CREATE ENROLLMENT RECORD
    # ============================================================
    if enrollment_type:
        StudentFeeEnrollment.objects.update_or_create(
            school=student.school,
            student=student,
            academic_term=academic_term,
            defaults={
                'enrollment_type': enrollment_type,
                'package_used': package,
                'is_automatic': True,
                'applied_by': prepared_by,
            }
        )

    return student_fee


def create_student_fee_ledger_entry(student_fee, created_by=None):
    """Create a provisional fee debit before an official invoice exists.

    Once an Invoice is created, the provisional FEE-* ledger entry must be
    removed and the invoice's line items become the single source of truth.
    This prevents double-counting a student's charges.
    """
    if not student_fee:
        return None

    if student_fee.status == 'INVOICED':
        StudentFinancialLedger.objects.filter(
            school=student_fee.school,
            student=student_fee.student,
            academic_term=student_fee.academic_term,
            entry_type='INVOICE',
            reference=f"FEE-{student_fee.id}",
        ).delete()
        return None

    billable_amount = sum(
        (item.final_amount or ZERO)
        for item in student_fee.items.all()
    ) + (student_fee.arrears_amount or ZERO)

    if billable_amount <= ZERO:
        return None

    existing = StudentFinancialLedger.objects.filter(
        school=student_fee.school,
        student=student_fee.student,
        academic_term=student_fee.academic_term,
        entry_type='INVOICE',
        reference=f"FEE-{student_fee.id}"
    ).first()

    if existing:
        return existing

    return StudentFinancialLedger.objects.create(
        school=student_fee.school,
        student=student_fee.student,
        academic_term=student_fee.academic_term,
        entry_type='INVOICE',
        side='DEBIT',
        amount=billable_amount,
        description=f"Student Fee - {student_fee.academic_term.name}",
        reference=f"FEE-{student_fee.id}",
        created_by=created_by,
        transaction_date=student_fee.updated_at or timezone.now(),
    )


def create_ledger_entries_for_approved_fees(school, student=None):
    """
    Create missing ledger entries for approved student fees.

    This is used as a backfill function to ensure all approved fees
    have corresponding ledger entries.

    Args:
        school: The school to process
        student: Optional specific student to process

    Returns:
        int: Number of ledger entries created
    """
    from ..models import StudentFinancialLedger

    # Get all approved student fees
    student_fees = StudentFee.objects.filter(
        school=school,
        status='APPROVED'
    ).select_related('student', 'academic_term')

    if student:
        student_fees = student_fees.filter(student=student)

    created_count = 0

    for student_fee in student_fees:
        # Official invoice ledger entries are the source of truth once a fee
        # has been invoiced. Never create a second provisional fee debit.
        if student_fee.status == 'INVOICED':
            StudentFinancialLedger.objects.filter(
                school=school, student=student_fee.student,
                academic_term=student_fee.academic_term,
                entry_type='INVOICE', reference=f"FEE-{student_fee.id}"
            ).delete()
            continue

        # Check if ledger entry already exists
        existing = StudentFinancialLedger.objects.filter(
            school=school,
            student=student_fee.student,
            academic_term=student_fee.academic_term,
            entry_type='INVOICE',
            reference=f"FEE-{student_fee.id}"
        ).exists()

        billable_amount = sum(
            (item.final_amount or ZERO)
            for item in student_fee.items.all()
        ) + (student_fee.arrears_amount or ZERO)

        if not existing and billable_amount > ZERO:
            StudentFinancialLedger.objects.create(
                school=school,
                student=student_fee.student,
                academic_term=student_fee.academic_term,
                entry_type='INVOICE',
                side='DEBIT',
                amount=billable_amount,
                description=f"Student Fee - {student_fee.academic_term.name}",
                reference=f"FEE-{student_fee.id}",
                transaction_date=student_fee.updated_at or timezone.now(),
            )
            created_count += 1

    return created_count


@transaction.atomic
def prepare_class_fees(
        school,
        school_class,
        academic_term,
        prepared_by=None,
        force_rebuild=False,
):
    """Prepare fees for every student currently enrolled in a school class."""
    students = (
        Student.objects
            .filter(school=school, school_class=school_class)
            .select_related('school_class', 'school', 'user')
            .order_by('user__last_name', 'user__first_name')
    )

    prepared = []
    errors = []

    for student in students:
        try:
            student_fee = prepare_student_fee(
                student=student,
                academic_term=academic_term,
                prepared_by=prepared_by,
                force_rebuild=force_rebuild,
            )
            prepared.append(student_fee)
        except (FeePreparationError, Exception) as exc:
            errors.append({
                'student_id': str(student.id),
                'student': str(student),
                'error': str(exc),
            })

    return {
        'prepared': prepared,
        'errors': errors,
        'total_students': students.count(),
        'prepared_count': len(prepared),
        'error_count': len(errors),
    }


def get_applicable_class_addons(student, academic_term):
    """
    Return class-based add-ons applicable to one student for one term.

    Rules:
    1. If addon.apply_to_new_students_only = True: Only applies to NEW students
    2. If addon.is_optional = True: Applies to ALL students (can be opted in/out)
    3. If addon.is_required = True: Applies to ALL students
    """
    if not student or not student.school_class:
        return []

    # Lazy import to avoid circular dependency
    from ..models import ClassAddOnStructure

    school_class = student.school_class
    grade_level = school_class.grade_level
    term_number = get_term_number(academic_term)

    # Get the student's enrollment type - CRITICAL for new student detection
    enrollment_type = get_student_enrollment_type(student, academic_term)

    # IMPORTANT: the term enrollment record is the single source of truth.
    # Never use Student.is_new_student here. That field is a profile flag and
    # can remain True after the student has progressed to another term.
    is_new = bool(
        enrollment_type
        and getattr(enrollment_type, 'code', None) == 'NEW'
    )

    addon_structures = (
        ClassAddOnStructure.objects
            .filter(school=student.school, is_active=True)
            .select_related('fee_category')
            .prefetch_related('items')
    )

    applicable_addons = []

    for addon in addon_structures:
        # Check term applicability
        custom_terms = {int(value) for value in (addon.custom_terms or []) if str(value).isdigit()}

        if addon.term_type == 'FIRST' and term_number != 1:
            continue
        if addon.term_type == 'SECOND' and term_number != 2:
            continue
        if addon.term_type == 'THIRD' and term_number != 3:
            continue
        if addon.term_type == 'CUSTOM' and term_number not in custom_terms:
            continue

        # Check new student restriction
        if addon.apply_to_new_students_only and not is_new:
            continue

        # Find the add-on item for this class
        addon_item = addon.items.filter(school_class=school_class, is_active=True).first()
        if not addon_item:
            addon_item = addon.items.filter(
                grade_level=grade_level, school_class__isnull=True, is_active=True
            ).first()
        if not addon_item:
            addon_item = addon.items.filter(
                grade_level__isnull=True, school_class__isnull=True, is_active=True
            ).first()
        if not addon_item:
            continue

        amount = addon_item.get_amount_for_term(term_number)
        if amount is None or amount <= ZERO:
            continue

        applicable_addons.append({
            'fee_category': addon.fee_category,
            'amount': amount,
            'description': f"{addon.name} - {school_class.name}",
            'addon_name': addon.name,
            'is_required': addon.is_required,
            'is_optional': addon.is_optional,
            'apply_to_new_students_only': addon.apply_to_new_students_only,
            'addon_id': str(addon.id),
            'item_id': str(addon_item.id),
        })

    return applicable_addons


def get_class_fee_schedule(school, school_class, academic_term):
    """
    A generic, student-agnostic fee schedule for one class/term: the
    published FeeStructure's line items plus every ClassAddOnStructure
    applicable to that class/term -- exactly what a parent enquiring about
    fees for that class needs to see, with no student attached.

    Because a couple of add-ons only apply to NEW students (see
    ``apply_to_new_students_only`` on ClassAddOnStructure), amounts are
    grouped rather than collapsed into one number, and two indicative
    totals are returned: one for a continuing/returning student and one
    for a newly admitted student.
    """
    term_number = get_term_number(academic_term)
    grade_level = school_class.grade_level

    fee_structure = (
        FeeStructure.objects
            .filter(school=school, school_class=school_class, academic_term=academic_term)
            .prefetch_related('items__fee_category')
            .first()
    )
    base_items = list(fee_structure.items.select_related('fee_category').all()) if fee_structure else []
    base_total = sum((item.amount for item in base_items), ZERO)

    addon_structures = (
        ClassAddOnStructure.objects
            .filter(school=school, is_active=True)
            .select_related('fee_category')
            .prefetch_related('items')
    )

    all_students_addons = []
    new_student_addons = []
    optional_addons = []

    for addon in addon_structures:
        custom_terms = {int(value) for value in (addon.custom_terms or []) if str(value).isdigit()}

        if addon.term_type == 'FIRST' and term_number != 1:
            continue
        if addon.term_type == 'SECOND' and term_number != 2:
            continue
        if addon.term_type == 'THIRD' and term_number != 3:
            continue
        if addon.term_type == 'CUSTOM' and term_number not in custom_terms:
            continue

        addon_item = addon.items.filter(school_class=school_class, is_active=True).first()
        if not addon_item:
            addon_item = addon.items.filter(
                grade_level=grade_level, school_class__isnull=True, is_active=True
            ).first()
        if not addon_item:
            addon_item = addon.items.filter(
                grade_level__isnull=True, school_class__isnull=True, is_active=True
            ).first()
        if not addon_item:
            continue

        amount = addon_item.get_amount_for_term(term_number)
        if amount is None or amount <= ZERO:
            continue

        entry = {
            'fee_category': addon.fee_category,
            'name': addon.name,
            'description': addon.description,
            'amount': amount,
        }

        if addon.apply_to_new_students_only:
            new_student_addons.append(entry)
        elif addon.is_optional:
            optional_addons.append(entry)
        else:
            all_students_addons.append(entry)

    all_students_total = sum((a['amount'] for a in all_students_addons), ZERO)
    new_student_total = sum((a['amount'] for a in new_student_addons), ZERO)

    return {
        'school': school,
        'school_class': school_class,
        'academic_term': academic_term,
        'base_items': base_items,
        'base_total': base_total,
        'all_students_addons': all_students_addons,
        'new_student_addons': new_student_addons,
        'optional_addons': optional_addons,
        'estimated_total_returning': base_total + all_students_total,
        'estimated_total_new': base_total + all_students_total + new_student_total,
        'is_published': bool(fee_structure and fee_structure.is_published),
    }


def generate_fee_schedule_pdf(school, school_class, academic_term, structure_id=None):
    """
    Render the generic (student-agnostic) fee schedule for a class/term as
    a PDF. Returns bytes, or None on failure. Mirrors
    finance/services/statements.py's generate_invoice_statement_pdf.
    """
    try:
        from xhtml2pdf import pisa
    except ImportError:
        logger.error("xhtml2pdf is not installed; cannot generate fee schedule PDFs.")
        return None

    from .receipts import _link_callback

    context = get_class_fee_schedule(school, school_class, academic_term)
    context['is_pdf'] = True
    context['structure_id'] = structure_id

    try:
        html = render_to_string('finance/fee_schedule.html', context)
    except Exception as exc:
        logger.error(f"Fee schedule PDF: failed to render template for {school_class} / {academic_term}: {exc}")
        return None

    buffer = io.BytesIO()
    try:
        result = pisa.CreatePDF(html, dest=buffer, encoding='UTF-8', link_callback=_link_callback)
    except Exception as exc:
        logger.error(f"Fee schedule PDF: pisa raised for {school_class} / {academic_term}: {exc}")
        return None

    if result.err:
        logger.error(f"Fee schedule PDF: {result.err} error(s) generating PDF for {school_class} / {academic_term}")
        return None

    return buffer.getvalue()


@transaction.atomic
def auto_prepare_student_fees(student, created_by=None, raise_errors=False):
    """
    Prepare the current-term fee and freeze the term enrollment decision.

    This function is safe for automatic workflows.  By default preparation
    errors are converted to ``None`` for backwards compatibility.  New
    enterprise automation paths may pass ``raise_errors=True`` so the exact
    finance failure is visible to the caller instead of being silently lost.
    """
    if not student or not student.school:
        return None

    current_term = (
        AcademicTerm.objects
        .filter(
            academic_year__school=student.school,
            academic_year__is_active=True,
            is_active=True,
        )
        .order_by('-start_date')
        .first()
    )
    if not current_term:
        return None

    try:
        enrollment = ensure_student_fee_enrollment(
            student, current_term, applied_by=created_by
        )

        # Respect the school's enrollment lifecycle settings.  If automatic
        # preparation is disabled for this enrollment type, do not silently
        # create a fee or invoice. Manual preparation can still be used.
        if not enrollment.enrollment_type.auto_prepare_fees:
            logger.info(
                "Automatic fee preparation disabled for %s (%s).",
                student,
                enrollment.enrollment_type.code,
            )
            return None

        # The term enrollment is the billing source of truth.  Do NOT promote
        # a student to NEW merely because the profile flag is still True.
        fee_structure = get_student_fee_structure(student, current_term)
        package = enrollment.package_used
        if package and package.fee_structure_id:
            fee_structure = package.fee_structure
        if not fee_structure:
            return None

        student_fee = prepare_student_fee(
            student=student,
            academic_term=current_term,
            prepared_by=created_by,
            force_rebuild=True,
            include_addons=True,
        )

        if enrollment.enrollment_type.auto_approve_fees:
            student_fee.status = 'APPROVED'
            student_fee.approved_by = created_by
            student_fee.save(update_fields=['status', 'approved_by', 'updated_at'])
            create_student_fee_ledger_entry(student_fee, created_by=created_by)

        return student_fee

    except FeePreparationError:
        if raise_errors:
            raise
        import logging
        logging.getLogger(__name__).warning(
            "Could not auto-prepare fees for %s", student, exc_info=True
        )
        return None
    except Exception:
        if raise_errors:
            raise
        import logging
        logging.getLogger(__name__).exception(
            "Unexpected error auto-preparing fees for %s", student
        )
        return None

