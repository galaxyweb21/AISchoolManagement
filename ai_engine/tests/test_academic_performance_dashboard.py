from django.test import SimpleTestCase
from django.urls import resolve, reverse


class AcademicPerformanceDashboardRouteTests(SimpleTestCase):
    def test_dashboard_url_resolves(self):
        url = reverse('ai_engine:academic_performance_dashboard')
        self.assertEqual(url, '/ai-engine/academic-performance/')
        self.assertEqual(resolve(url).url_name, 'academic_performance_dashboard')
