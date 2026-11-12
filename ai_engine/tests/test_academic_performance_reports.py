from django.test import SimpleTestCase
from django.urls import resolve, reverse

from ai_engine.views.academic_reports import _safe_csv_cell


class AcademicPerformanceReportSafetyTests(SimpleTestCase):
    def test_csv_formula_prefixes_are_neutralized(self):
        for value in ('=1+1', '+SUM(A1:A2)', '-2+3', '@cmd', '\tformula', '\rformula'):
            with self.subTest(value=value):
                self.assertTrue(_safe_csv_cell(value).startswith("'"))

    def test_normal_csv_values_are_preserved(self):
        self.assertEqual(_safe_csv_cell('Mathematics'), 'Mathematics')
        self.assertEqual(_safe_csv_cell(None), '')

    def test_report_routes_resolve(self):
        for name, path in (
            ('ai_engine:academic_performance_reports', '/ai-engine/academic-performance/reports/'),
            ('ai_engine:export_academic_performance_csv', '/ai-engine/academic-performance/reports/export/csv/'),
            ('ai_engine:export_academic_performance_print', '/ai-engine/academic-performance/reports/export/print/'),
        ):
            with self.subTest(name=name):
                url = reverse(name)
                self.assertEqual(url, path)
                self.assertEqual(resolve(url).url_name, name.split(':', 1)[1])
