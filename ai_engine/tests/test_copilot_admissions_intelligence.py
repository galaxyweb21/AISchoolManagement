from django.test import SimpleTestCase

from admissions.models import AdmissionApplication
from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotAdmissionsIntentTests(SimpleTestCase):
    def test_admissions_questions_route_to_admissions(self):
        questions = (
            "How many admission applications were submitted this year?",
            "Show applicants awaiting review",
            "Give me an admission status breakdown",
            "List admitted applicants",
            "Show applications by grade",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(
                    FullSchoolDatabaseIntelligence.plan_question(question)["domain"],
                    "admissions",
                )

    def test_admissions_domain_takes_priority_over_finance_terms(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many admission applications have outstanding fees?"
        )
        self.assertEqual(plan["domain"], "admissions")

    def test_application_statuses_match_the_real_model(self):
        configured = {value for value, _label in AdmissionApplication.STATUS_CHOICES}
        self.assertEqual(
            configured,
            {"DRAFT", "SUBMITTED", "REVIEW", "APPROVED", "REJECTED", "ADMITTED"},
        )
        self.assertNotIn("WAITLISTED", configured)

    def test_admissions_permission_is_required(self):
        class DeniedIntelligence(FullSchoolDatabaseIntelligence):
            def can(self, capability):
                return False

        engine = DeniedIntelligence(user=None, school=None)
        result = engine.admissions("how many admission applications")
        self.assertEqual(result["mode"], "permission_denied")
        self.assertIn("permission", result["answer"].lower())
