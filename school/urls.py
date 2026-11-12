# school/urls.py
from django.urls import path
from . import views

app_name = 'school'

urlpatterns = [
    # Dashboard & Settings
    path('dashboard/', views.school_dashboard, name='school_dashboard'),
    path('settings/', views.school_settings, name='school_settings'),

    # Academic Year CRUD
    path('academic-years/create/', views.academic_year_create, name='academic_year_create'),
    path('academic-years/<uuid:year_id>/edit/', views.academic_year_edit, name='academic_year_edit'),
    path('academic-years/<uuid:year_id>/delete/', views.academic_year_delete, name='academic_year_delete'),

    # =========================================================
    # Academic Term CRUD (MISSING ROUTES ADDED HERE)
    # =========================================================
    path('academic-terms/create/', views.academic_term_create, name='academic_term_create'),
    path('academic-terms/<uuid:term_id>/edit/', views.academic_term_edit, name='academic_term_edit'),
    path('academic-terms/<uuid:term_id>/delete/', views.academic_term_delete, name='academic_term_delete'),
]