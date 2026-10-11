from django.urls import path
from .views import (
    attendance_tracker,
    api_toggle_attendance,
    api_capture_attendance,
    api_register_face,
    api_live_capture,
    student_attendance_history,
)
from .staff_views import (
    staff_attendance_dashboard,
    api_staff_toggle_attendance,
    api_staff_checkout,
    api_register_staff_face,
    api_staff_live_capture,
)

app_name = 'attendance'

urlpatterns = [
    path('tracker/', attendance_tracker, name='attendance_tracker'),
    path('api/toggle/', api_toggle_attendance, name='api_toggle_attendance'),
    path('api/capture/', api_capture_attendance, name='api_capture_attendance'),
    path('api/register-face/', api_register_face, name='api_register_face'),
    path('api/live-capture/', api_live_capture, name='api_live_capture'),
    path('student/<uuid:student_id>/history/', student_attendance_history, name='student_attendance_history'),

    # Staff attendance
    path('staff/', staff_attendance_dashboard, name='staff_attendance_dashboard'),
    path('api/staff/toggle/', api_staff_toggle_attendance, name='api_staff_toggle_attendance'),
    path('api/staff/checkout/', api_staff_checkout, name='api_staff_checkout'),
    path('api/staff/register-face/', api_register_staff_face, name='api_register_staff_face'),
    path('api/staff/live-capture/', api_staff_live_capture, name='api_staff_live_capture'),
]
