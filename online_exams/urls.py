from django.urls import path
from . import views

app_name = 'online_exams'
urlpatterns = [
    path('', views.exam_list, name='exam_list'),
    path('my-results/', views.student_results, name='student_results'),
    path('my-results/<uuid:exam_id>/', views.student_result_detail, name='student_result_detail'),
    path('create/', views.exam_create, name='exam_create'),
    path('<uuid:exam_id>/', views.exam_detail, name='exam_detail'),
    path('<uuid:exam_id>/gradebook/', views.exam_gradebook, name='exam_gradebook'),
    path('<uuid:exam_id>/analytics/', views.exam_analytics, name='exam_analytics'),
    path('<uuid:exam_id>/edit/', views.exam_edit, name='exam_edit'),
    path('<uuid:exam_id>/publish/', views.exam_publish, name='exam_publish'),
    path('<uuid:exam_id>/close/', views.exam_close, name='exam_close'),
    path('<uuid:exam_id>/release-results/', views.exam_release_results, name='exam_release_results'),
    path('<uuid:exam_id>/export-results/', views.exam_export_results, name='exam_export_results'),
    path('<uuid:exam_id>/gradebook.csv', views.exam_gradebook_csv, name='exam_gradebook_csv'),
    path('<uuid:exam_id>/bulk-finalize-reviews/', views.exam_bulk_finalize_reviews, name='exam_bulk_finalize_reviews'),
    path('<uuid:exam_id>/questions/<uuid:question_id>/save/', views.question_update, name='question_update'),
    path('<uuid:exam_id>/questions/<uuid:question_id>/regenerate/', views.question_regenerate, name='question_regenerate'),
    path('<uuid:exam_id>/questions/<uuid:question_id>/delete/', views.question_delete, name='question_delete'),
    path('<uuid:exam_id>/take/', views.exam_take, name='exam_take'),
    path('<uuid:exam_id>/autosave/', views.answer_autosave, name='answer_autosave'),
    path('<uuid:exam_id>/attempts/<uuid:attempt_id>/review/', views.attempt_review, name='attempt_review'),
]
