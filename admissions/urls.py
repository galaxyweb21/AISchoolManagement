from django.urls import path
from . import views

app_name = 'admissions'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('applications/', views.application_list, name='application_list'),
    path('applications/new/', views.application_create, name='application_create'),
    path('applications/<uuid:application_id>/', views.application_detail, name='application_detail'),
    path('applications/<uuid:application_id>/admit/', views.admit_application, name='admit_application'),
    path('applications/<uuid:application_id>/<str:action>/', views.application_status, name='application_status'),
]
