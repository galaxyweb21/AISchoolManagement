# academics/tasks.py
from celery import shared_task


@shared_task
def generate_timetable_task(timetable_id, population_size=80, generations=300, mutation_rate=0.15):
    """
    Runs the AI timetabler in the background so an admin generating a
    timetable for a large school doesn't sit on a spinning HTTP request.
    """
    from .models import Timetable
    from .services import AITimetableService

    try:
        timetable = Timetable.objects.get(id=timetable_id)
    except Timetable.DoesNotExist:
        return

    AITimetableService.run(
        timetable,
        population_size=population_size,
        generations=generations,
        mutation_rate=mutation_rate,
    )
