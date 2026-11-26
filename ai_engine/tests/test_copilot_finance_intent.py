from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotFinanceIntentTests(SimpleTestCase):
    def classify(self, question):
        return FullSchoolDatabaseIntelligence._finance_query_intent(question)

    def test_outstanding_balance_takes_precedence_over_fee_keyword(self):
        self.assertEqual(self.classify("How much fees are outstanding?"), "outstanding")
        self.assertEqual(self.classify("Which students still owe fees?"), "outstanding")

    def test_collection_questions_are_not_misclassified_as_billed(self):
        self.assertEqual(self.classify("How much fees have we collected?"), "collections")
        self.assertEqual(self.classify("Show confirmed payments this term"), "collections")

    def test_billed_questions_are_distinct_from_collections(self):
        self.assertEqual(self.classify("What is the total fees billed?"), "billed")
        self.assertEqual(self.classify("How much was invoiced this term?"), "billed")

    def test_general_finance_summary_is_supported(self):
        self.assertEqual(self.classify("Give me a finance summary"), "summary")

    def test_unclassified_question_returns_none(self):
        self.assertIsNone(self.classify("Hello, how are you?"))
