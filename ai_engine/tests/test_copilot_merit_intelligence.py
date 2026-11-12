from unittest import TestCase
from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotMeritIntentTests(TestCase):
    def setUp(self):
        self.engine = FullSchoolDatabaseIntelligence(
            user=None, school=None, allowed_students=None
        )

    def test_student_award_query_is_recognized(self):
        self.assertIsNotNone(
            self.engine.student_merit_ranking.__func__
        )
        q = self.engine.norm("Who are the best overall students for awards and scholarships?")
        self.assertTrue(any(w in q for w in ("student", "students", "learner", "learners", "pupil", "pupils")))
        self.assertTrue(any(w in q for w in ("best", "award", "scholarship", "overall")))

    def test_staff_performance_query_is_recognized(self):
        q = self.engine.norm("Rank staff by performance and attendance reliability")
        self.assertTrue(any(w in q for w in ("staff", "employee", "employees", "teacher", "teachers", "personnel")))
        self.assertTrue(any(w in q for w in ("performance", "performing", "best", "top", "rank", "attendance rate", "reliability")))

    def test_shortlist_explains_not_final_eligibility(self):
        source = self.engine.student_merit_ranking.__doc__
        self.assertIn("not an automatic award", source)
