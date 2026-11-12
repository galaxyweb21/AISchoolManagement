from django.db.models import Avg, Sum
from academics.models import Student
from attendance.models import Attendance
from finance.models import StudentFinancialLedger


class ExecutiveAnalyticsEngine:

    @classmethod
    def get_school_health_scorecard(cls) -> dict:
        """
        Aggregates operational metrics into a high-level executive scorecard.
        """
        total_students = Student.objects.filter(is_active=True).count() if hasattr(Student,
                                                                                   'is_active') else Student.objects.count()

        # Financial Health
        total_outstanding = StudentFinancialLedger.objects.aggregate(
            total=Sum('balance')
        )['total'] or 0.0

        # Attendance Rate overall (Last 30 Days)
        total_records = Attendance.objects.count()
        present_records = Attendance.objects.filter(status='PRESENT').count()
        attendance_rate = (present_records / total_records * 100) if total_records > 0 else 100.0

        return {
            'total_active_enrolment': total_students,
            'overall_attendance_rate': round(attendance_rate, 2),
            'total_outstanding_revenue': float(total_outstanding),
            'system_status': 'OPTIMAL' if attendance_rate >= 85 else 'REQUIRES_ATTENTION'
        }