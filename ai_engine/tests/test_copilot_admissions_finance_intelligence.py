from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotAdmissionsFinanceIntentTests(SimpleTestCase):
    def test_admissions_and_finance_questions_use_combined_domain(self):
        questions = (
            "How many approved admission applicants have outstanding fees?",
            "Which admitted students have unpaid admission invoices?",
            "How much admission fee revenue has been collected?",
            "Compare admission applications with completed fee payments",
            "Which applicants have outstanding balances?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(
                    FullSchoolDatabaseIntelligence.plan_question(question)["domain"],
                    "admissions_finance",
                )

    def test_admissions_only_questions_keep_the_admissions_domain(self):
        self.assertEqual(
            FullSchoolDatabaseIntelligence.plan_question(
                "How many admission applications were submitted this year?"
            )["domain"],
            "admissions",
        )

    def test_finance_only_questions_keep_the_finance_domain(self):
        self.assertEqual(
            FullSchoolDatabaseIntelligence.plan_question(
                "How much fees are outstanding this term?"
            )["domain"],
            "finance",
        )

    def test_combined_handler_requires_both_permissions(self):
        class DeniedIntelligence(FullSchoolDatabaseIntelligence):
            def can(self, capability):
                return capability == "students"

        engine = DeniedIntelligence(user=None, school=None)
        result = engine.admissions_finance_intelligence(
            "how many admission applicants have outstanding fees"
        )
        self.assertEqual(result["mode"], "permission_denied")
        self.assertIn("permission", result["answer"].lower())

    def test_combined_handler_ignores_unrelated_questions(self):
        engine = FullSchoolDatabaseIntelligence(user=None, school=None)
        self.assertIsNone(engine.admissions_finance_intelligence("how many students are enrolled"))
