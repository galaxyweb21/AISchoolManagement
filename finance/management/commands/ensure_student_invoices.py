from django.core.management.base import BaseCommand
from finance.services.auto_invoicing import ensure_student_term_invoice, get_current_term
from students.models import Student


class Command(BaseCommand):
    help = 'Ensure every active student has a current-term invoice when eligible.'

    def add_arguments(self, parser):
        parser.add_argument('--school-id', dest='school_id')
        parser.add_argument('--student-id', dest='student_id')

    def handle(self, *args, **options):
        qs = Student.objects.filter(is_active=True).select_related('school', 'school_class')
        if options.get('school_id'):
            qs = qs.filter(school_id=options['school_id'])
        if options.get('student_id'):
            qs = qs.filter(id=options['student_id'])

        created = 0
        existing = 0
        skipped = 0
        errors = 0

        for student in qs.iterator():
            try:
                term = get_current_term(student.school)
                before = student.invoices.filter(academic_term=term).exists() if term else False
                invoice = ensure_student_term_invoice(student, created_by=None, academic_term=term)
                if invoice and before:
                    existing += 1
                elif invoice:
                    created += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                self.stderr.write(f'{student}: {exc}')

        self.stdout.write(
            self.style.SUCCESS(
                f'Invoice lifecycle complete. Created={created}, Existing={existing}, '
                f'Skipped={skipped}, Errors={errors}'
            )
        )
