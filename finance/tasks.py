from celery import shared_task
from django.db.models import Sum
from django.utils import timezone


@shared_task
def notify_overdue_fee_balances():
    """Create one in-app overdue-balance notification per overdue invoice.

    An invoice is overdue when its due date has passed and it still has a
    positive confirmed balance. Notifications are idempotent by invoice, so
    the daily task can safely run repeatedly.
    """
    from .models import Invoice
    from communication.models import NotificationLog, NotificationCategory, NotificationChannel
    from communication.services import NotificationService

    today = timezone.localdate()
    qs = (Invoice.objects
          .filter(due_date__lt=today)
          .exclude(status='VOID')
          .select_related('school', 'student__user', 'student__parent'))

    created = 0
    for invoice in qs.iterator():
        total = invoice.line_items.aggregate(total=Sum('amount'))['total'] or 0
        paid = invoice.payments.filter(status='CONFIRMED').aggregate(total=Sum('amount'))['total'] or 0
        balance = total - paid
        parent = invoice.student.parent
        if balance <= 0 or not parent:
            continue

        if NotificationLog.objects.filter(
            recipient=parent,
            category=NotificationCategory.OVERDUE_BALANCE,
            reference_id=str(invoice.id),
            reference_type='InvoiceOverdue',
        ).exists():
            continue

        subject = f"Overdue School Fee Balance - {invoice.invoice_number}"
        student_name = invoice.student.user.get_full_name() or invoice.student.admission_number
        message = (
            f"Dear {parent.get_full_name() or 'Parent/Guardian'},\n\n"
            f"The school fee invoice {invoice.invoice_number} for {student_name} is overdue.\n"
            f"Outstanding balance: GH¢ {balance:.2f}.\n"
            f"Due date: {invoice.due_date.strftime('%d %b %Y')}.\n\n"
            f"Please make payment at your earliest convenience.\n\n"
            f"{invoice.school.name}"
        )

        NotificationService.trigger(
            recipient=parent,
            category=NotificationCategory.OVERDUE_BALANCE,
            subject=subject,
            message=message,
            channel=NotificationChannel.IN_APP,
            reference_id=str(invoice.id),
            reference_type='InvoiceOverdue',
            school=invoice.school,
        )
        created += 1

    return created
