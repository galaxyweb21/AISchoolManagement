from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotQueryRoutingRegressionTests(SimpleTestCase):
    def setUp(self):
        self.engine = FullSchoolDatabaseIntelligence(user=Mock(), school=Mock(), allowed_students=None)

    def test_absence_count_routes_to_attendance_before_student_directory(self):
        expected = {"answer": "attendance handler"}
        with patch.object(self.engine, "attendance", return_value=expected) as attendance, \
             patch.object(self.engine, "student", return_value={"answer": "student directory"}) as student:
            self.assertIs(self.engine.answer("How many students were absent today?"), expected)
            attendance.assert_called_once()
            student.assert_not_called()

    def test_average_assessment_question_routes_to_academic_summary(self):
        expected = {"answer": "academic average"}
        with patch.object(self.engine, "academic_summary", return_value=expected), \
             patch.object(self.engine, "generic_entity", return_value={"answer": "record counts"}) as generic:
            self.assertIs(self.engine.answer("What is the average assessment score?"), expected)
            generic.assert_not_called()

    def test_overdue_books_routes_to_library_loans_not_book_catalogue(self):
        expected = {"answer": "overdue loans"}
        with patch.object(self.engine, "library", return_value=expected), \
             patch.object(self.engine, "generic_entity", return_value={"answer": "book catalogue"}) as generic:
            self.assertIs(self.engine.answer("Which books are overdue?"), expected)
            generic.assert_not_called()

    def test_admission_application_count_has_dedicated_handler(self):
        expected = {"answer": "admission applications"}
        with patch.object(self.engine, "admissions", return_value=expected), \
             patch.object(self.engine, "generic_entity", return_value={"answer": "generic records"}) as generic:
            self.assertIs(self.engine.answer("How many admission applications do we have?"), expected)
            generic.assert_not_called()

    def test_staff_merit_question_precedes_staff_directory(self):
        expected = {"answer": "staff merit"}
        with patch.object(self.engine, "staff_merit_question", return_value=expected), \
             patch.object(self.engine, "staff_question", return_value={"answer": "staff directory"}) as directory:
            self.assertIs(self.engine.answer("Who is the best staff this term?"), expected)
            directory.assert_not_called()
    def test_online_exam_question_uses_online_exam_handler_before_academic_summary(self):
        expected = {"answer": "online exam summary"}
        with patch.object(self.engine, "online_exams", return_value=expected), \
             patch.object(self.engine, "academic_summary", return_value={"answer": "generic exam summary"}) as academic:
            self.assertIs(self.engine.answer("How many online exams are published?"), expected)
            academic.assert_not_called()

    def test_lesson_plan_question_uses_lesson_plan_handler(self):
        expected = {"answer": "lesson plan summary"}
        with patch.object(self.engine, "lesson_plan_metrics", return_value=expected), \
             patch.object(self.engine, "generic_entity", return_value={"answer": "generic records"}) as generic:
            self.assertIs(self.engine.answer("How many lesson plans are awaiting review?"), expected)
            generic.assert_not_called()
    def test_academic_performance_queries_are_classified_as_academics(self):
        questions = (
            "What is the school's overall academic performance this term?",
            "Which subject has the lowest average?",
            "Which subject performed best this term?",
            "Compare class performance this term",
            "Show students below 40%",
            "Which students failed three or more subjects?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(self.engine.plan_question(question)["domain"], "academics")

    def test_academic_summary_delegates_to_performance_intelligence(self):
        expected = {"answer": "academic intelligence"}
        with patch.object(self.engine, "academic_performance_intelligence", return_value=expected) as intelligence:
            self.assertIs(self.engine.academic_summary("What is the overall academic performance?"), expected)
            intelligence.assert_called_once()
    def test_lowest_subject_average_is_not_misrouted_to_finance(self):
        self.assertEqual(self.engine.plan_question("Which subject has the lowest average?")["domain"], "academics")
        self.assertEqual(self.engine.plan_question("Which students owe fees?")["domain"], "finance")
    def test_academic_risk_queries_are_classified_as_academics(self):
        questions = (
            "Which students are at academic risk this term?",
            "Show students who are struggling academically",
            "Prepare an early intervention list",
            "Which students are falling behind?",
            "Which students are failing in multiple subjects?",
            "Show students whose grades declined",
            "Which students' grades have declined?",
            "Show students with declining grades",
            "What support should we provide to students at risk?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(self.engine.plan_question(question)["domain"], "academics")


    def test_grade_decline_question_routes_to_academic_risk_not_student_directory(self):
        expected = {"answer": "academic grade decline"}
        with patch.object(self.engine, "academic_summary", return_value=expected) as academic, \
             patch.object(self.engine, "student", return_value={"answer": "student directory"}) as directory:
            self.assertIs(self.engine.answer("Show students whose grades declined"), expected)
            academic.assert_called_once()
            directory.assert_not_called()

    def test_academic_summary_prioritizes_early_warning_queries(self):
        expected = {"answer": "early warning"}
        with patch.object(self.engine, "academic_risk_intelligence", return_value=expected) as risk, \
             patch.object(self.engine, "academic_performance_intelligence", return_value={"answer": "performance"}) as performance:
            self.assertIs(self.engine.academic_summary("Which students are at academic risk?"), expected)
            risk.assert_called_once()
            performance.assert_not_called()

    def test_academic_risk_bands_are_deterministic_and_explainable(self):
        classify = self.engine.academic_risk_band
        self.assertEqual(classify(35, 0, None), "CRITICAL")
        self.assertEqual(classify(55, 3, None), "CRITICAL")
        self.assertEqual(classify(48, 1, None), "HIGH")
        self.assertEqual(classify(65, 0, -12), "HIGH")
        self.assertEqual(classify(58, 0, None), "WATCH")
        self.assertEqual(classify(75, 0, -6), "WATCH")
        self.assertEqual(classify(75, 0, 2), "ON_TRACK")

