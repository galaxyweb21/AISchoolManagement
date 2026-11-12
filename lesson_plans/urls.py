from django.urls import path
from . import views

app_name = 'lesson_plans'
urlpatterns = [
    path('', views.lesson_plan_list, name='lesson_plan_list'),
    path('create/', views.lesson_plan_create, name='lesson_plan_create'),
    path('<uuid:plan_id>/edit/', views.lesson_plan_edit, name='lesson_plan_edit'),
    path('<uuid:plan_id>/review/', views.lesson_plan_review, name='lesson_plan_review'),
    path('generate-ai/', views.lesson_plan_generate_ai, name='lesson_plan_generate_ai'),
    path('<uuid:plan_id>/document/', views.lesson_plan_document, name='lesson_plan_document'),
    path('<uuid:plan_id>/export/pdf/', views.lesson_plan_export_pdf, name='lesson_plan_export_pdf'),
]
