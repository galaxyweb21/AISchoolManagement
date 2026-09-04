from unittest.mock import patch

from django.test import TestCase

from ai_engine.services.report_comment_service import ReportCommentService


class ReportCommentServiceSafetyTests(TestCase):
    def test_service_exposes_role_specific_generators(self):
        self.assertTrue(callable(ReportCommentService.generate_teacher_comment))
        self.assertTrue(callable(ReportCommentService.generate_headteacher_comment))

    @patch('ai_engine.services.report_comment_service.AIService.generate_report_comment', return_value='A concise professional comment.')
    def test_generate_single_requires_valid_type(self, mocked):
        with self.assertRaises(ValueError):
            ReportCommentService.generate_single(None, None, 'invalid')
