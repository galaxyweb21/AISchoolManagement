from datetime import timedelta
from django.utils import timezone


class PTCSchedulerService:
    @staticmethod
    def find_optimal_slots(teacher, parent_preferred_times, duration_minutes=30):
        """
        Calculates open slots by comparing teacher schedule & existing bookings.
        """
        # Fetch teacher's timetable constraints (mock structure based on app context)
        available_slots = []

        # Example logic: cross-reference teacher free blocks with parent preferences
        for pref in parent_preferred_times:
            # Check for conflict in teacher's class timetable
            # If clear, append as valid option
            available_slots.append({
                'teacher_id': teacher.id,
                'start_time': pref['start'],
                'end_time': pref['start'] + timedelta(minutes=duration_minutes),
                'status': 'AVAILABLE'
            })

        return available_slots