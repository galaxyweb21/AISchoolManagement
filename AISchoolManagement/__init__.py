# Ensures the Celery app is loaded whenever Django starts, so
# @shared_task-decorated functions (e.g. academics.tasks) work.
from .celery import app as celery_app

__all__ = ('celery_app',)
