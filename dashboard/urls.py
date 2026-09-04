# dashboard/urls.py
from django.urls import path
from .views import (
    RoleBasedDashboardView,
    admin_dashboard,
    teacher_dashboard,
    parent_dashboard,
)

app_name = 'dashboard'

urlpatterns = [
    # Role-based dashboards
    path('', RoleBasedDashboardView.as_view(), name='dashboard'),

    # Legacy role-based dashboards (keep for backward compatibility)
    path('admin/', admin_dashboard, name='admin_dashboard'),
    path('teacher/', teacher_dashboard, name='teacher_dashboard'),
    path('parent/', parent_dashboard, name='parent_dashboard'),
]