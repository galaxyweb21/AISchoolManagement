# students/urls.py
from django.urls import path
from . import views

app_name = 'students'

urlpatterns = [
    # Student views
    path('', views.student_list, name='student_list'),
    path('create/', views.create_student, name='create_student'),
    path('<uuid:student_id>/', views.student_detail, name='student_detail'),
    path('<uuid:student_id>/edit/', views.edit_student, name='edit_student'),
    path('<uuid:student_id>/toggle-active/', views.toggle_student_active, name='toggle_student_active'),

    # Face registration
    path('<uuid:student_id>/face/register/', views.api_register_face, name='api_register_face'),
    path('<uuid:student_id>/face/delete/', views.api_delete_face, name='api_delete_face'),
    path('<uuid:student_id>/face/preview/', views.api_face_preview, name='api_face_preview'),
    path('bulk-face-registration/', views.bulk_face_registration, name='bulk_face_registration'),
    path('api/bulk-face-register/', views.api_bulk_face_registration, name='api_bulk_face_registration'),

    # Parent APIs
    path('api/parent/<uuid:parent_id>/', views.api_get_parent, name='api_get_parent'),
    path('api/parent/<uuid:parent_id>/edit/', views.api_edit_parent, name='api_edit_parent'),
    path('api/parent/<uuid:parent_id>/edit-email/', views.api_edit_parent_email, name='api_edit_parent_email'),  # NEW

    # Student credentials
    path('api/student-credentials/<uuid:student_id>/', views.api_student_credentials, name='api_student_credentials'),

    # Student self-service
    path('my/grades/', views.my_grades, name='my_grades'),
    path('my/attendance/', views.my_attendance, name='my_attendance'),
    path('my/fees/', views.my_fees, name='my_fees'),

    # Grade levels
    path('grade-levels/', views.grade_level_list, name='grade_level_list'),
    path('grade-levels/create/', views.grade_level_create, name='grade_level_create'),
    path('grade-levels/<uuid:grade_level_id>/edit/', views.grade_level_edit, name='grade_level_edit'),
    path('grade-levels/<uuid:grade_level_id>/delete/', views.grade_level_delete, name='grade_level_delete'),


]