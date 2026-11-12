from django.test import SimpleTestCase
from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class StudentMeritIntentTests(SimpleTestCase):
    def test_top_five_numeric_and_word_forms(self):
        parser = FullSchoolDatabaseIntelligence._requested_rank_limit
        self.assertEqual(parser("give me the overall best five students", 10), 5)
        self.assertEqual(parser("show top 5 students", 10), 5)
        self.assertEqual(parser("list top 12 students", 10), 12)

    def test_default_limit_varies_by_purpose(self):
        parser = FullSchoolDatabaseIntelligence._requested_rank_limit
        self.assertEqual(parser("which students for scholarships", 10), 10)
        self.assertEqual(parser("best overall students", 5), 5)

    def test_intent_handler_is_dispatched_before_generic_student_list(self):
        import inspect
        source = inspect.getsource(FullSchoolDatabaseIntelligence.answer)
        self.assertLess(source.index("self.student_merit_ranking"), source.index("self.student,"))
