from django.urls import path
from .views import (
    teacher_grading_portal, terminal_results_register, terminal_student_report, api_submit_grade, api_generate_ai_grade_feedback,
    api_create_assessment, api_save_question, api_delete_question, api_save_terminal_results,
)
app_name = 'assessments'
urlpatterns = [
    path('portal/', teacher_grading_portal, name='grading_portal'),
    path('results/', terminal_results_register, name='terminal_results_register'),
    path('results/student/<uuid:student_id>/', terminal_student_report, name='terminal_student_report'),
    path('api/save/', api_submit_grade, name='api_submit_grade'),
    path('api/create/', api_create_assessment, name='api_create_assessment'),
    path('api/terminal-results/save/', api_save_terminal_results, name='api_save_terminal_results'),
    path('api/ai-feedback/', api_generate_ai_grade_feedback, name='api_generate_ai_grade_feedback'),
    path('api/questions/save/', api_save_question, name='api_save_question'),
    path('api/questions/<uuid:question_id>/delete/', api_delete_question, name='api_delete_question'),
]
