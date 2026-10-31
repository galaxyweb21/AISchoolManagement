from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotIntentPlannerTests(SimpleTestCase):
    def test_absent_today_routes_to_attendance_not_student_directory(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many students were absent today?"
        )
        self.assertEqual(plan["domain"], "attendance")
        self.assertEqual(plan["action"], "count")
        self.assertEqual(plan["period"], "today")

    def test_basic_five_ranking_routes_to_student_merit(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "Who are the best students in Basic 5?"
        )
        self.assertEqual(plan["domain"], "student_academic_ranking")
        self.assertEqual(plan["action"], "rank")

    def test_staff_attendance_ranking_is_not_staff_directory(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "Who has the best staff attendance this term?"
        )
        self.assertEqual(plan["domain"], "staff_attendance_ranking")
        self.assertEqual(plan["period"], "current_term")

    def test_overall_staff_merit_does_not_assume_attendance(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "Who is the best staff this term?"
        )
        self.assertEqual(plan["domain"], "staff_performance")
        self.assertTrue(plan["ranking"])

    def test_average_assessment_routes_to_academic_aggregation(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "What is the average assessment score?"
        )
        self.assertEqual(plan["domain"], "academics")
        self.assertEqual(plan["action"], "average")

    def test_overdue_books_routes_to_library_loans(self):
        plan = FullSchoolDatabaseIntelligence.plan_question("Which books are overdue?")
        self.assertEqual(plan["domain"], "library")
        self.assertEqual(plan["action"], "list")

    def test_fee_collection_routes_to_finance(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How much school fees have we collected?"
        )
        self.assertEqual(plan["domain"], "finance")
        self.assertEqual(plan["action"], "sum")

    def test_admission_application_count_routes_to_admissions(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many admission applications do we have?"
        )
        self.assertEqual(plan["domain"], "admissions")
        self.assertEqual(plan["action"], "count")

    def test_payroll_questions_route_to_operational_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How much net payroll was paid this month?"
        )
        self.assertEqual(plan["domain"], "operations")
        self.assertEqual(plan["action"], "sum")

    def test_teacher_workload_questions_route_to_operational_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "Which teachers are overloaded this term?"
        )
        self.assertEqual(plan["domain"], "operations")

    def test_timetable_questions_route_to_operational_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many published timetables do we have?"
        )
        self.assertEqual(plan["domain"], "operations")

    def test_inventory_questions_route_to_operational_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "Which inventory items are out of stock?"
        )
        self.assertEqual(plan["domain"], "operations")

    def test_transport_questions_route_to_operational_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many active transport subscriptions do we have?"
        )
        self.assertEqual(plan["domain"], "operations")

    def test_promoted_students_routes_to_promotion_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many students were promoted?"
        )
        self.assertEqual(plan["domain"], "operations")

    def test_repeated_students_routes_to_promotion_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many students repeated?"
        )
        self.assertEqual(plan["domain"], "operations")

    def test_timetable_conflicts_route_to_operational_metrics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many timetable conflicts have been recorded?"
        )
        self.assertEqual(plan["domain"], "operations")
    def test_online_exam_attempts_route_to_online_exams_not_generic_academics(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many online exam attempts are awaiting marking?"
        )
        self.assertEqual(plan["domain"], "online_exams")
        self.assertEqual(plan["action"], "count")

    def test_online_exam_average_routes_to_online_exams(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "What is the average score for online examinations?"
        )
        self.assertEqual(plan["domain"], "online_exams")
        self.assertEqual(plan["action"], "average")

    def test_lesson_plan_submissions_route_to_lesson_plans(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "How many lesson plans are awaiting review?"
        )
        self.assertEqual(plan["domain"], "lesson_plans")
        self.assertEqual(plan["action"], "count")

    def test_lesson_note_listing_routes_to_lesson_plans(self):
        plan = FullSchoolDatabaseIntelligence.plan_question(
            "Show the approved lesson notes."
        )
        self.assertEqual(plan["domain"], "lesson_plans")
        self.assertEqual(plan["action"], "list")

