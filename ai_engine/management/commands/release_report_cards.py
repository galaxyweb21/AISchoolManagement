from django.core.management.base import BaseCommand, CommandError
from school.models import AcademicTerm
from ai_engine.models import ReportCardReleaseBatch
from ai_engine.services.report_card_release import ReportCardReleaseService


class Command(BaseCommand):
    help = 'Generate, finalize, email and build the A4 print pack for a term.'

    def add_arguments(self, parser):
        parser.add_argument('--term', required=True, help='AcademicTerm UUID')
        parser.add_argument('--no-email', action='store_true')
        parser.add_argument('--no-print-pack', action='store_true')

    def handle(self, *args, **opts):
        try:
            term = AcademicTerm.objects.select_related('academic_year__school').get(id=opts['term'])
        except AcademicTerm.DoesNotExist:
            raise CommandError('Academic term not found.')
        batch = ReportCardReleaseBatch.objects.create(
            school=term.academic_year.school,
            academic_term=term,
            email_parents=not opts['no_email'],
            generate_print_pack=not opts['no_print_pack'],
            auto_finalize=True,
        )
        result = ReportCardReleaseService.run(batch)
        self.stdout.write(self.style.SUCCESS(
            f'{result.status}: generated={result.generated_count}, finalized={result.finalized_count}, '
            f'emailed={result.emailed_count}, blocked={result.blocked_count}, '
            f'print_pages={result.print_pack_count}'
        ))
