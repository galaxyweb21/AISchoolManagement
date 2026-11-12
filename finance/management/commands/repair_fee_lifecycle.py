from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from finance.models import StudentFee, StudentFinancialLedger


class Command(BaseCommand):
    help = (
        'Repair legacy duplicate StudentFee/ledger records. Approved and '
        'invoiced records are never rebuilt; duplicate provisional fee debits '
        'are collapsed to one per StudentFee reference.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--school', dest='school_id', help='Optional school UUID')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        school_id = options.get('school_id')
        dry_run = options['dry_run']

        qs = StudentFee.objects.all()
        if school_id:
            qs = qs.filter(school_id=school_id)

        duplicate_groups = (
            qs.values('student_id', 'academic_term_id')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )

        fee_groups = list(duplicate_groups)
        removed_fees = 0
        removed_ledgers = 0

        for group in fee_groups:
            fees = list(
                qs.filter(
                    student_id=group['student_id'],
                    academic_term_id=group['academic_term_id'],
                ).order_by('-status', '-updated_at', '-created_at')
            )
            # Prefer the authoritative lifecycle state. Invoiced > Approved >
            # Prepared > Draft. This command is deliberately conservative.
            priority = {'INVOICED': 4, 'APPROVED': 3, 'PREPARED': 2, 'DRAFT': 1, 'CANCELLED': 0}
            fees.sort(key=lambda f: (priority.get(f.status, 0), f.updated_at), reverse=True)
            keep = fees[0]
            for duplicate in fees[1:]:
                if duplicate.status in ('APPROVED', 'INVOICED'):
                    self.stdout.write(self.style.WARNING(
                        f'Skipping duplicate authoritative fee {duplicate.id}; manual review required.'
                    ))
                    continue
                if dry_run:
                    removed_fees += 1
                    continue
                with transaction.atomic():
                    StudentFinancialLedger.objects.filter(
                        school=duplicate.school,
                        student=duplicate.student,
                        academic_term=duplicate.academic_term,
                        entry_type='INVOICE',
                        reference=f'FEE-{duplicate.id}',
                    ).delete()
                    duplicate.delete()
                    removed_fees += 1

        # Collapse duplicate provisional ledger rows for the same StudentFee
        # reference, preserving the oldest row as the audit anchor.
        ledger_qs = StudentFinancialLedger.objects.filter(entry_type='INVOICE')
        if school_id:
            ledger_qs = ledger_qs.filter(school_id=school_id)
        groups = ledger_qs.values('school_id', 'student_id', 'academic_term_id', 'reference').annotate(n=Count('id')).filter(n__gt=1)
        for group in groups:
            if not str(group['reference']).startswith('FEE-'):
                continue
            rows = list(ledger_qs.filter(**group).order_by('created_at'))
            for row in rows[1:]:
                if dry_run:
                    removed_ledgers += 1
                else:
                    row.delete()
                    removed_ledgers += 1

        self.stdout.write(self.style.SUCCESS(
            f'Fee lifecycle repair complete. Removed fees: {removed_fees}; '
            f'removed duplicate provisional ledger rows: {removed_ledgers}; '
            f'dry_run={dry_run}.'
        ))
