# AISchoolManagement/celery.py
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AISchoolManagement.settings')

app = Celery('AISchoolManagement')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
