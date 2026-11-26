from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from ai_engine.services.copilot_engine import SchoolCopilotEngine


class CopilotTenantBoundaryTests(SimpleTestCase):
    def test_engine_rejects_a_school_other_than_the_users_school(self):
        user = Mock()
        user.pk = "user-1"
        user.school_id = 10
        user.role = "TEACHER"
        requested_school = Mock()
        requested_school.pk = 20

        result = SchoolCopilotEngine(user).answer(
            school=requested_school,
            question="How many students are active?",
        )

        self.assertEqual(result["mode"], "permission_denied")
        self.assertIn("that school", result["answer"])

    def test_engine_rejects_missing_school_context(self):
        user = Mock()
        user.pk = "user-1"
        user.school_id = None
        user.role = "TEACHER"

        result = SchoolCopilotEngine(user).answer(
            school=None,
            question="How many students are active?",
        )

        self.assertEqual(result["mode"], "permission_denied")
        self.assertIn("not linked to a school", result["answer"])

    @patch("ai_engine.services.copilot_engine.can_use", return_value=True)
    @patch("ai_engine.services.copilot_context.allowed_students", side_effect=RuntimeError("scope failure"))
    def test_student_scope_resolution_failure_returns_empty_queryset(self, _resolver, _capability):
        from students.models import Student

        user = Mock()
        user.role = "TEACHER"
        user.pk = "user-1"
        school = Mock()

        scoped = SchoolCopilotEngine(user)._get_authorized_students(school)

        self.assertIsNotNone(scoped)
        self.assertTrue(scoped.query.is_empty())
        self.assertEqual(scoped.model, Student)
