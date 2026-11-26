from unittest.mock import Mock

from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotCrossModuleComparisonTests(SimpleTestCase):
    def setUp(self):
        self.engine = FullSchoolDatabaseIntelligence(user=Mock(), school=Mock())

    def test_unrelated_questions_do_not_trigger_cross_module_handler(self):
        self.assertIsNone(self.engine.attendance_academic_class_comparison("show student attendance this week"))
        self.assertIsNone(self.engine.attendance_academic_class_comparison("show academic results by class"))

    def test_class_comparison_requires_both_domains_and_comparison_intent(self):
        self.assertIsNone(self.engine.attendance_academic_class_comparison(
            "show attendance and academic performance by class"
        ))

    def test_permission_is_checked_before_database_access(self):
        self.engine.can = Mock(side_effect=lambda capability: capability == "attendance")
        result = self.engine.attendance_academic_class_comparison(
            "compare attendance and academic performance by class this term"
        )
        self.assertIn("permission", result["mode"])
        self.assertIn("academic", result["answer"].lower())

    def test_scoped_user_without_authorized_student_queryset_fails_closed(self):
        self.engine.can = Mock(return_value=True)
        with self.settings():
            from unittest.mock import patch
            with patch("ai_engine.services.role_ai_policy.get_student_scope", return_value="class"):
                result = self.engine.attendance_academic_class_comparison(
                    "compare attendance and academic performance by class this term"
                )
        self.assertEqual(result["mode"], "scope_verification_failed")
