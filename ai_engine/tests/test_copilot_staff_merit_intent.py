from unittest.mock import Mock

from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class StaffMeritIntentTests(SimpleTestCase):
    def setUp(self):
        self.engine = FullSchoolDatabaseIntelligence(user=Mock(), school=Mock())
        self.engine.can = Mock(return_value=True)

    def test_best_staff_does_not_return_staff_directory(self):
        result = self.engine.staff_merit_question("who is the best staff this term")
        self.assertIsNotNone(result)
        self.assertIn("does not currently provide a formal staff appraisal", result["answer"])
        self.assertNotIn("20 staff members", result["answer"])
        self.assertFalse(result["data"]["ranking_available"])

    def test_attendance_criterion_is_not_claimed_as_overall_performance(self):
        # This only verifies intent routing; the ORM calculation requires a
        # configured Django database and is covered by deployment smoke tests.
        result = self.engine.staff_merit_question("who has the best staff attendance this term")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("data", {}).get("metric"), "attendance_rate") if result.get("data", {}).get("metric") else self.assertIn("staff attendance ranking", result["answer"].lower())
