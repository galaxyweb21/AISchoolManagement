from django.test import SimpleTestCase
from unittest.mock import patch

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotLibraryIntentTests(SimpleTestCase):
    def test_library_questions_route_to_library_domain(self):
        questions = (
            "How many books are in the library?",
            "Show overdue library loans",
            "Which books are most borrowed?",
            "Give me the library inventory by category",
            "How many books have been returned this month?",
            "List books with no available copies",
            "How many library loans are active?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(FullSchoolDatabaseIntelligence.plan_question(question)["domain"], "library")

    def test_library_permission_is_required_before_database_access(self):
        engine = FullSchoolDatabaseIntelligence(user=object(), school=object())
        with patch.object(engine, "can", return_value=False):
            result = engine.library("show overdue library loans")
        self.assertEqual(result["mode"], "permission_denied")

    def test_unrelated_question_is_not_claimed_by_library_handler(self):
        engine = FullSchoolDatabaseIntelligence(user=object(), school=object())
        self.assertIsNone(engine.library("how many students are enrolled"))

    def test_library_is_a_school_fact_domain(self):
        engine = FullSchoolDatabaseIntelligence(user=object(), school=object())
        self.assertTrue(engine.looks_like_school_fact("How many library loans are overdue?"))
