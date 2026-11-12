from datetime import date
from unittest.mock import Mock

from django.test import SimpleTestCase

from ai_engine.services.full_school_database_intelligence import FullSchoolDatabaseIntelligence


class CopilotAttendanceIntelligenceTests(SimpleTestCase):
    def setUp(self):
        self.engine = FullSchoolDatabaseIntelligence(
            user=Mock(), school=Mock(), allowed_students=None
        )

    def test_today_window_defaults_to_today(self):
        start, end, label = self.engine._attendance_date_window("student attendance", date(2026, 10, 30))
        self.assertEqual((start, end, label), (date(2026, 10, 30), date(2026, 10, 30), "today"))

    def test_this_week_window_starts_on_monday(self):
        start, end, label = self.engine._attendance_date_window("attendance this week", date(2026, 10, 30))
        self.assertEqual(start, date(2026, 10, 26))
        self.assertEqual(end, date(2026, 10, 30))
        self.assertEqual(label, "this week")

    def test_last_week_window_is_previous_monday_to_sunday(self):
        start, end, label = self.engine._attendance_date_window("attendance last week", date(2026, 10, 30))
        self.assertEqual(start, date(2026, 10, 19))
        self.assertEqual(end, date(2026, 10, 25))
        self.assertEqual(label, "last week")

    def test_this_month_wins_when_comparing_with_last_month(self):
        start, end, label = self.engine._attendance_date_window(
            "compare attendance this month with last month", date(2026, 10, 30)
        )
        self.assertEqual(start, date(2026, 10, 1))
        self.assertEqual(end, date(2026, 10, 30))
        self.assertEqual(label, "this month")

    def test_last_month_alone_resolves_previous_calendar_month(self):
        start, end, label = self.engine._attendance_date_window("attendance last month", date(2026, 10, 30))
        self.assertEqual(start, date(2026, 9, 1))
        self.assertEqual(end, date(2026, 9, 30))
        self.assertEqual(label, "last month")

    def test_custom_date_range_is_supported(self):
        start, end, label = self.engine._attendance_date_window(
            "attendance from 2026-10-01 to 2026-10-15", date(2026, 10, 30)
        )
        self.assertEqual(start, date(2026, 10, 1))
        self.assertEqual(end, date(2026, 10, 15))
        self.assertEqual(label, "custom date range")

    def test_last_7_days_includes_today_and_six_previous_days(self):
        start, end, label = self.engine._attendance_date_window("attendance last 7 days", date(2026, 10, 30))
        self.assertEqual(start, date(2026, 10, 24))
        self.assertEqual(end, date(2026, 10, 30))
        self.assertEqual(label, "last 7 days")

    def test_relative_day_range_is_bounded_and_includes_today(self):
        start, end, label = self.engine._attendance_date_window("attendance last 14 days", date(2026, 10, 30))
        self.assertEqual(start, date(2026, 10, 17))
        self.assertEqual(end, date(2026, 10, 30))
        self.assertEqual(label, "last 14 days")

    def test_attendance_rate_excludes_excused_entries(self):
        queryset = Mock()
        queryset.aggregate.return_value = {
            "total": 10, "present": 6, "late": 1, "absent": 2, "excused": 1,
        }
        counts = self.engine._attendance_counts(queryset)
        self.assertEqual(counts["attendance_rate"], 87.5)
        self.assertEqual(counts["absence_rate"], 25.0)

    def test_attendance_question_routes_to_attendance_handler(self):
        plan = self.engine.plan_question("compare student attendance this week with last week")
        self.assertEqual(plan["domain"], "attendance")

    def test_staff_attendance_question_routes_to_attendance_handler(self):
        plan = self.engine.plan_question("show staff attendance trends this month")
        self.assertEqual(plan["domain"], "attendance")

    def test_late_yesterday_student_list_routes_to_attendance(self):
        plan = self.engine.plan_question("show students who were late yesterday")
        self.assertEqual(plan["domain"], "attendance")
        self.assertEqual(plan["action"], "list")
        self.assertEqual(plan["period"], "yesterday")

    def test_face_recognition_staff_count_routes_to_attendance(self):
        plan = self.engine.plan_question("how many staff attendance records were captured through face recognition")
        self.assertEqual(plan["domain"], "attendance")
        self.assertEqual(plan["action"], "count")

    def test_group_comparison_is_not_mistaken_for_period_comparison(self):
        self.assertFalse(self.engine._is_period_comparison("compare student and staff attendance this week"))

    def test_explicit_period_comparison_is_detected(self):
        self.assertTrue(self.engine._is_period_comparison("compare staff attendance this month with last month"))
