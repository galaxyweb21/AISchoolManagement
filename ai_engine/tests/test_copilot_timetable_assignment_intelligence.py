from unittest.mock import Mock

from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotTimetableAssignmentIntelligenceTests(SimpleTestCase):
    def setUp(self):
        self.engine = FullSchoolDatabaseIntelligence(user=Mock(), school=Mock())

    def test_teacher_workload_routes_to_operations(self):
        plan = self.engine.plan_question("Which teachers have the highest teaching workload?")
        self.assertEqual(plan["domain"], "operations")

    def test_missing_teacher_allocations_route_to_operations(self):
        plan = self.engine.plan_question("Which classes have subjects without assigned teachers?")
        self.assertEqual(plan["domain"], "operations")

    def test_timetable_clash_question_routes_to_operations(self):
        plan = self.engine.plan_question("Are there any teacher timetable clashes?")
        self.assertEqual(plan["domain"], "operations")

    def test_unrelated_question_does_not_trigger_timetable_handler(self):
        self.assertIsNone(
            self.engine.timetable_assignment_intelligence("show student attendance this week")
        )

    def test_permission_is_checked_before_timetable_queries(self):
        self.engine.can = Mock(return_value=False)
        result = self.engine.timetable_assignment_intelligence(
            "Which teachers have the highest teaching workload?"
        )
        self.assertIn("permission", result["mode"])
