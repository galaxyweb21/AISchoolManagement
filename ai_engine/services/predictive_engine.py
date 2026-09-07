from datetime import timedelta

from django.db.models import Avg
from django.utils import timezone

from attendance.models import Attendance
from assessments.models import Grade
from finance.models import Invoice

from ai_engine.models import StudentRiskAssessment


class PredictiveIntelligenceService:
    """
    Deterministic predictive layer built on top of the existing
    RiskEngineService.

    This service does NOT replace the current risk engine.

    RiskEngineService answers:
        "What is the student's current risk?"

    This service answers:
        "Is the student's situation improving or worsening?"
        "What is the likely near-term trajectory?"
    """

    LOOKBACK_DAYS = 60

    @staticmethod
    def _clamp(value, minimum=0, maximum=100):
        return max(minimum, min(maximum, value))

    @classmethod
    def attendance_trend(cls, student):
        """
        Compare the recent attendance period with the previous period.
        """

        today = timezone.localdate()

        recent_start = today - timedelta(days=29)
        previous_start = today - timedelta(days=59)
        previous_end = today - timedelta(days=30)

        recent = Attendance.objects.filter(
            school=student.school,
            student=student,
            date__gte=recent_start,
            date__lte=today,
        )

        previous = Attendance.objects.filter(
            school=student.school,
            student=student,
            date__gte=previous_start,
            date__lte=previous_end,
        )

        def rate(queryset):
            total = queryset.count()

            if not total:
                return None

            present = queryset.filter(
                status__in=["PRESENT", "LATE"]
            ).count()

            return round(
                (present / total) * 100,
                1
            )

        recent_rate = rate(recent)
        previous_rate = rate(previous)

        if recent_rate is None or previous_rate is None:
            return {
                "recent": recent_rate,
                "previous": previous_rate,
                "change": None,
                "direction": "INSUFFICIENT_DATA",
            }

        change = round(
            recent_rate - previous_rate,
            1
        )

        if change <= -10:
            direction = "RAPIDLY_WORSENING"

        elif change < -3:
            direction = "WORSENING"

        elif change >= 10:
            direction = "RAPIDLY_IMPROVING"

        elif change > 3:
            direction = "IMPROVING"

        else:
            direction = "STABLE"

        return {
            "recent": recent_rate,
            "previous": previous_rate,
            "change": change,
            "direction": direction,
        }

    @classmethod
    def academic_trend(cls, student):
        """
        Compare recent assessment performance with earlier performance.
        """

        grades = list(
            Grade.objects.filter(
                student=student,
                assessment__school=student.school,
            )
            .select_related("assessment")
            .order_by("updated_at")
        )

        if len(grades) < 2:
            return {
                "recent_average": None,
                "previous_average": None,
                "change": None,
                "direction": "INSUFFICIENT_DATA",
            }

        percentages = []

        for grade in grades:

            if not grade.assessment.max_score:
                continue

            percentage = (
                float(grade.score_achieved)
                / float(grade.assessment.max_score)
            ) * 100

            percentages.append(percentage)

        if len(percentages) < 2:
            return {
                "recent_average": None,
                "previous_average": None,
                "change": None,
                "direction": "INSUFFICIENT_DATA",
            }

        midpoint = len(percentages) // 2

        previous = percentages[:midpoint]
        recent = percentages[midpoint:]

        previous_average = sum(previous) / len(previous)
        recent_average = sum(recent) / len(recent)

        change = round(
            recent_average - previous_average,
            1
        )

        if change <= -10:
            direction = "RAPIDLY_WORSENING"

        elif change < -3:
            direction = "WORSENING"

        elif change >= 10:
            direction = "RAPIDLY_IMPROVING"

        elif change > 3:
            direction = "IMPROVING"

        else:
            direction = "STABLE"

        return {
            "recent_average": round(recent_average, 1),
            "previous_average": round(previous_average, 1),
            "change": change,
            "direction": direction,
        }

    @classmethod
    def finance_status(cls, student):
        """
        Evaluate the student's current outstanding financial position.
        """

        today = timezone.localdate()

        invoices = Invoice.objects.filter(
            school=student.school,
            student=student,
        )

        overdue = invoices.filter(
            status__in=["UNPAID", "PARTIAL"],
            due_date__lt=today,
        )

        overdue_count = overdue.count()

        overdue_amount = sum(
            (invoice.balance_due for invoice in overdue),
            0
        )

        if overdue_count == 0:

            direction = "STABLE"

        elif overdue_count == 1:

            direction = "ATTENTION"

        else:

            direction = "WORSENING"

        return {
            "overdue_count": overdue_count,
            "overdue_amount": float(overdue_amount),
            "direction": direction,
        }

    @classmethod
    def latest_risk(cls, student):
        """
        Retrieve the latest stored risk assessment for the student.
        """

        return (
            StudentRiskAssessment.objects
            .filter(
                school=student.school,
                student=student,
            )
            .select_related("run")
            .order_by("-run__computed_at")
            .first()
        )

    @classmethod
    def predict_student(cls, student):
        """
        Build a complete predictive profile for one student.
        """

        attendance = cls.attendance_trend(student)

        academic = cls.academic_trend(student)

        finance = cls.finance_status(student)

        latest_risk = cls.latest_risk(student)

        signals = []

        worsening_count = 0

        if attendance["direction"] in [
            "WORSENING",
            "RAPIDLY_WORSENING",
        ]:

            worsening_count += 1

            signals.append({
                "type": "attendance",
                "direction": attendance["direction"],
                "change": attendance["change"],
            })

        if academic["direction"] in [
            "WORSENING",
            "RAPIDLY_WORSENING",
        ]:

            worsening_count += 1

            signals.append({
                "type": "academic",
                "direction": academic["direction"],
                "change": academic["change"],
            })

        if finance["direction"] == "WORSENING":

            worsening_count += 1

            signals.append({
                "type": "finance",
                "direction": "WORSENING",
                "overdue_amount": finance["overdue_amount"],
            })

        improving_count = sum(
            1
            for direction in [
                attendance["direction"],
                academic["direction"],
            ]
            if direction in [
                "IMPROVING",
                "RAPIDLY_IMPROVING",
            ]
        )

        if worsening_count >= 2:

            trajectory = "WORSENING"

        elif worsening_count == 1:

            trajectory = "WATCH"

        elif improving_count >= 2:

            trajectory = "IMPROVING"

        else:

            trajectory = "STABLE"

        # -------------------------------------------------
        # Predict near-term risk
        # -------------------------------------------------

        current_score = (
            latest_risk.risk_score
            if latest_risk
            else 0
        )

        adjustment = 0

        if trajectory == "WORSENING":
            adjustment += 10

        elif trajectory == "WATCH":
            adjustment += 5

        elif trajectory == "IMPROVING":
            adjustment -= 5

        predicted_score = cls._clamp(
            round(current_score + adjustment, 1)
        )

        if predicted_score >= 75:
            predicted_band = "CRITICAL"

        elif predicted_score >= 50:
            predicted_band = "HIGH"

        elif predicted_score >= 25:
            predicted_band = "MEDIUM"

        else:
            predicted_band = "LOW"

        # -------------------------------------------------
        # Confidence
        # -------------------------------------------------

        available_signals = sum([
            attendance["direction"] != "INSUFFICIENT_DATA",
            academic["direction"] != "INSUFFICIENT_DATA",
            latest_risk is not None,
        ])

        confidence = min(
            95,
            45 + (available_signals * 15)
        )

        return {
            "student": student,
            "current_risk_score": current_score,
            "current_risk_band": (
                latest_risk.risk_band
                if latest_risk
                else "UNKNOWN"
            ),
            "predicted_risk_score": predicted_score,
            "predicted_risk_band": predicted_band,
            "trajectory": trajectory,
            "confidence": confidence,
            "attendance": attendance,
            "academic": academic,
            "finance": finance,
            "signals": signals,
        }


    @classmethod
    def predict_school(cls, school, limit=None):
        """
        Generate predictive intelligence for all active students
        in a school.

        This is a safe orchestration layer around the existing
        predict_student() engine.

        It does not change the underlying prediction logic.
        """

        from students.models import Student

        students = (
            Student.objects
                .filter(
                school=school,
                is_active=True
            )
                .select_related("user")
                .order_by("user__last_name", "user__first_name")
        )

        if limit:
            students = students[:limit]

        predictions = []

        for student in students:

            try:
                prediction = cls.predict_student(student)

                if prediction:
                    predictions.append(prediction)

            except Exception:
                # One student's data problem must not stop
                # predictions for the rest of the school.
                continue

        return predictions

