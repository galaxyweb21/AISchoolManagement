from types import SimpleNamespace
from unittest.mock import patch
import sys
import types

from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class FakeQuerySet:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, **kwargs):
        rows = self.rows
        for key, expected in kwargs.items():
            field = key[:-4] if key.endswith("__in") else key
            # The fake rows model the already school-scoped records; only
            # status predicates need to be represented in these unit tests.
            if field in ("school", "teacher__school", "created_by"):
                continue
            if key.endswith("__in"):
                rows = [row for row in rows if row.get(field) in expected]
            else:
                rows = [row for row in rows if row.get(field) == expected]
        return FakeQuerySet(rows)

    def count(self):
        return len(self.rows)

    def select_related(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def __getitem__(self, item):
        return self.rows[item]


class FakeManager:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, **kwargs):
        return FakeQuerySet(self.rows).filter(**kwargs)


class CopilotStatusCountConsistencyTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(role="SCHOOL_ADMIN")
        self.school = object()
        self.engine = FullSchoolDatabaseIntelligence(
            user=self.user, school=self.school, allowed_students=None
        )
        self.engine.can = lambda permission: True
        self.engine.meta = lambda status="ok": {"source": "test", "status": status}

    def test_published_online_exam_question_returns_only_published_count(self):
        class OnlineExam:
            STATUS_CHOICES = (
                ("DRAFT", "Draft"),
                ("PUBLISHED", "Published"),
                ("CLOSED", "Closed"),
            )

        OnlineExam.objects = FakeManager([
            {"status": "DRAFT"},
            {"status": "PUBLISHED"},
            {"status": "CLOSED"},
            {"status": "CLOSED"},
        ])

        fake_module = types.ModuleType("online_exams.models")
        fake_module.OnlineExam = OnlineExam
        fake_module.ExamAttempt = type("ExamAttempt", (), {"objects": FakeManager([])})
        with patch.dict(sys.modules, {"online_exams.models": fake_module}):
            result = self.engine.online_exams("how many online examinations are published?")

        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["status"], "PUBLISHED")
        self.assertIn("1 published online examination", result["answer"])
        self.assertNotIn("Draft:", result["answer"])

    def test_lesson_plan_awaiting_review_returns_only_submitted_count(self):
        class WeeklyLessonPlan:
            STATUS_DRAFT = "DRAFT"
            STATUS_SUBMITTED = "SUBMITTED"
            STATUS_REVISION = "REVISION_REQUESTED"
            STATUS_APPROVED = "APPROVED"
            STATUS_CHOICES = (
                ("DRAFT", "Draft"),
                ("SUBMITTED", "Submitted for review"),
                ("REVISION_REQUESTED", "Revision requested"),
                ("APPROVED", "Approved"),
            )

        WeeklyLessonPlan.objects = FakeManager([
            {"status": "SUBMITTED"},
            {"status": "APPROVED"},
            {"status": "APPROVED"},
        ])

        fake_module = types.ModuleType("lesson_plans.models")
        fake_module.WeeklyLessonPlan = WeeklyLessonPlan
        with patch.dict(sys.modules, {"lesson_plans.models": fake_module}):
            result = self.engine.lesson_plan_metrics("how many lesson plans are awaiting review?")

        self.assertEqual(result["data"]["count"], 1)
        self.assertEqual(result["data"]["status"], "SUBMITTED")
        self.assertIn("1 lesson plan submitted for review", result["answer"])
        self.assertNotIn("Approved:", result["answer"])

    def test_online_exam_summary_breakdown_reconciles_to_total(self):
        class OnlineExam:
            STATUS_CHOICES = (
                ("DRAFT", "Draft"),
                ("PUBLISHED", "Published"),
                ("CLOSED", "Closed"),
            )

        OnlineExam.objects = FakeManager([
            {"status": "DRAFT"},
            {"status": "PUBLISHED"},
            {"status": "CLOSED"},
            {"status": "CLOSED"},
        ])
        fake_module = types.ModuleType("online_exams.models")
        fake_module.OnlineExam = OnlineExam
        fake_module.ExamAttempt = type("ExamAttempt", (), {"objects": FakeManager([])})
        with patch.dict(sys.modules, {"online_exams.models": fake_module}):
            result = self.engine.online_exams("give me an online examination summary")

        self.assertEqual(result["data"]["count"], 4)
        self.assertEqual(sum(result["data"]["status_breakdown"].values()), 4)

    def test_lesson_plan_summary_breakdown_reconciles_to_total(self):
        class WeeklyLessonPlan:
            STATUS_DRAFT = "DRAFT"
            STATUS_SUBMITTED = "SUBMITTED"
            STATUS_REVISION = "REVISION_REQUESTED"
            STATUS_APPROVED = "APPROVED"
            STATUS_CHOICES = (
                ("DRAFT", "Draft"),
                ("SUBMITTED", "Submitted for review"),
                ("REVISION_REQUESTED", "Revision requested"),
                ("APPROVED", "Approved"),
            )

        WeeklyLessonPlan.objects = FakeManager([
            {"status": "SUBMITTED"},
            {"status": "APPROVED"},
            {"status": "APPROVED"},
        ])
        fake_module = types.ModuleType("lesson_plans.models")
        fake_module.WeeklyLessonPlan = WeeklyLessonPlan
        with patch.dict(sys.modules, {"lesson_plans.models": fake_module}):
            result = self.engine.lesson_plan_metrics("give me a lesson plan summary")

        self.assertEqual(result["data"]["count"], 3)
        self.assertEqual(sum(result["data"]["status_breakdown"].values()), 3)
