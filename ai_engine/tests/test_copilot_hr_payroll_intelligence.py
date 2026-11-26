from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotHRPayrollIntentTests(SimpleTestCase):
    def test_payroll_workflow_questions_route_to_operations(self):
        for question in (
            "How many pending payroll runs are there?",
            "Show calculated payroll runs",
            "Give me a payroll status breakdown",
            "How much net pay was approved this month?",
            "How much gross pay was approved this month?",
            "Show calculated payroll runs",
        ):
            with self.subTest(question=question):
                self.assertEqual(FullSchoolDatabaseIntelligence.plan_question(question)["domain"], "operations")

    def test_leave_balance_and_request_questions_route_to_leave(self):
        for question in (
            "Show staff leave balances",
            "How many leave requests are pending?",
            "Give me a leave status summary",
            "How many staff are currently on leave?",
        ):
            with self.subTest(question=question):
                self.assertEqual(FullSchoolDatabaseIntelligence.plan_question(question)["domain"], "leave")

    def test_staff_headcount_by_department_routes_to_staff(self):
        plan = FullSchoolDatabaseIntelligence.plan_question("Give me the staff headcount by department")
        self.assertEqual(plan["domain"], "staff")

    def test_payroll_question_is_not_misclassified_as_general_finance(self):
        plan = FullSchoolDatabaseIntelligence.plan_question("How much payroll was paid this month?")
        self.assertEqual(plan["domain"], "operations")

    def test_calculated_payroll_does_not_trigger_attendance_substring(self):
        self.assertEqual(
            FullSchoolDatabaseIntelligence.plan_question("Show calculated payroll runs")["domain"],
            "operations",
        )

    def test_net_pay_question_routes_to_operations(self):
        self.assertEqual(
            FullSchoolDatabaseIntelligence.plan_question("How much net pay was approved this month?")["domain"],
            "operations",
        )

    def test_student_lateness_question_still_routes_to_attendance(self):
        plan = FullSchoolDatabaseIntelligence.plan_question("Show students who were late yesterday")
        self.assertEqual(plan["domain"], "attendance")

