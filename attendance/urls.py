# attendance/urls.py
from django.urls import path
from .views import (
    attendance_tracker,
    api_toggle_attendance,
    api_capture_attendance,
    api_register_face,
    api_live_capture
)

app_name = 'attendance'

urlpatterns = [
    path('tracker/', attendance_tracker, name='attendance_tracker'),
    path('api/toggle/', api_toggle_attendance, name='api_toggle_attendance'),
    path('api/capture/', api_capture_attendance, name='api_capture_attendance'),
    path('api/register-face/', api_register_face, name='api_register_face'),
    path('api/live-capture/', api_live_capture, name='api_live_capture'),
]