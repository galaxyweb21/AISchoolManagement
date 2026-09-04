# ai_engine/urls.py
from django.urls import path
from . import views
from ai_engine.views.command_center import StudentInterventionView, intervention_center
from ai_engine.views.ghana_education import (
    ghana_education_home,
    ghana_education_topic_detail,
    ghana_education_search,
    ghana_education_ask_copilot,
)
from ai_engine.views.exports import (
    export_exam,
    export_report_card,
    export_risk_assessment,
    export_finance_insights,
)

app_name = 'ai_engine'

urlpatterns = [
    # ============================================================
    # GHANA EDUCATION ROUTES
    # ============================================================
    path('ghana-education/', ghana_education_home, name='ghana_education_home'),
    path('ghana-education/topic/<slug:slug>/', ghana_education_topic_detail, name='ghana_education_topic_detail'),
    path('ghana-education/search/', ghana_education_search, name='ghana_education_search'),
    path('ghana-education/ask-copilot/', ghana_education_ask_copilot, name='ghana_education_ask_copilot'),

    # ============================================================
    # AI COPILOT ROUTES
    # ============================================================
    path('copilot/', views.ai_copilot_page, name='ai_copilot'),
    path('copilot/api/', views.ai_copilot_api, name='ai_copilot_api'),
    path('copilot/api/conversation/<uuid:conversation_id>/messages/', views.get_conversation_messages, name='get_conversation_messages'),
    path('copilot/api/conversation/<uuid:conversation_id>/delete/', views.delete_conversation, name='delete_conversation'),

    # ============================================================
    # API Endpoints
    # ============================================================
    path('generate-feedback/', views.api_generate_feedback, name='api_generate_feedback'),

    # Risk Assessment
    path('risk-dashboard/', views.risk_dashboard, name='risk_dashboard'),
    path('risk-dashboard/run/', views.trigger_risk_assessment, name='trigger_risk_assessment'),
    path('risk-dashboard/student/<uuid:assessment_id>/', views.student_risk_detail, name='student_risk_detail'),

    # Report Cards
    path('report-cards/', views.report_card_dashboard, name='report_card_dashboard'),
    path('report-cards/run/', views.trigger_report_card_batch, name='trigger_report_card_batch'),
    path('report-cards/comments/run/', views.trigger_report_comment_batch, name='trigger_report_comment_batch'),
    path('report-cards/<uuid:report_card_id>/', views.report_card_detail, name='report_card_detail'),
    path('report-cards/<uuid:report_card_id>/save/', views.save_report_card_narrative, name='save_report_card_narrative'),
    path('report-cards/<uuid:report_card_id>/regenerate/', views.regenerate_report_card_narrative, name='regenerate_report_card_narrative'),
    path('report-cards/<uuid:report_card_id>/comments/<str:comment_type>/generate/', views.generate_report_card_comment, name='generate_report_card_comment'),
    path('report-cards/<uuid:report_card_id>/finalize/', views.finalize_report_card, name='finalize_report_card'),
    path('report-cards/<uuid:report_card_id>/unfinalize/', views.unfinalize_report_card, name='unfinalize_report_card'),

    # Finance Insights
    path('finance-insights/', views.finance_insights_dashboard, name='finance_insights_dashboard'),
    path('finance-insights/invoice/<uuid:invoice_id>/', views.invoice_risk_detail, name='invoice_risk_detail'),
    path('finance-insights/invoice/<uuid:invoice_id>/remind/', views.generate_reminder, name='generate_reminder'),
    path('finance-insights/reminder/<uuid:reminder_id>/save/', views.save_reminder, name='save_reminder'),
    path('finance-insights/reminder/<uuid:reminder_id>/sent/', views.mark_reminder_sent, name='mark_reminder_sent'),

    # Exams
    path('exams/', views.exam_dashboard, name='exam_dashboard'),
    path('exams/create/', views.create_exam, name='create_exam'),
    path('exams/<uuid:exam_id>/', views.exam_detail, name='exam_detail'),
    path('exams/<uuid:exam_id>/unlink-assessment/', views.unlink_exam_from_assessment, name='unlink_exam_from_assessment'),
    path('exams/<uuid:exam_id>/questions/add/', views.add_exam_question, name='add_exam_question'),
    path('exams/<uuid:exam_id>/questions/<uuid:question_id>/save/', views.save_exam_question, name='save_exam_question'),
    path('exams/<uuid:exam_id>/questions/<uuid:question_id>/regenerate/', views.regenerate_exam_question, name='regenerate_exam_question'),
    path('exams/<uuid:exam_id>/questions/<uuid:question_id>/delete/', views.delete_exam_question, name='delete_exam_question'),
    path('exams/<uuid:exam_id>/link-assessment/', views.link_exam_to_assessment, name='link_exam_to_assessment'),
    path('exams/<uuid:exam_id>/delete/', views.delete_exam, name='delete_exam'),
    path('exams/<uuid:exam_id>/questions/delete-all/', views.delete_all_exam_questions, name='delete_all_exam_questions'),

    # Parent Assistant
    path('parent-assistant/', views.parent_children_list, name='parent_children_list'),
    path('parent-assistant/<uuid:student_id>/', views.parent_chat_thread, name='parent_chat_thread'),

    # AI Command Center
    path('command-center/', views.ai_command_center, name='ai_command_center'),
    path('automation/<uuid:task_id>/approve/', views.approve_task, name='approve_ai_task'),

    # Intervention Center
    path('intervention-center/', intervention_center, name='intervention_center'),

    # Absence Management
    path('absences/', views.absence_list, name='absence_list'),
    path('absences/report/', views.report_absence, name='report_absence'),
    path('absences/<uuid:absence_id>/', views.cover_plan_detail, name='cover_plan_detail'),
    path('absences/<uuid:absence_id>/regenerate/', views.regenerate_cover_plan, name='regenerate_cover_plan'),
    path('absences/assignment/<uuid:assignment_id>/confirm/', views.confirm_substitute, name='confirm_substitute'),
    path('absences/assignment/<uuid:assignment_id>/unconfirm/', views.unconfirm_substitute, name='unconfirm_substitute'),
    path('absences/assignment/<uuid:assignment_id>/note/', views.save_handover_note, name='save_handover_note'),

    # Predictive Intelligence
    path('predictive/student/<uuid:student_id>/', views.predictive_student_detail, name='predictive_student_detail'),

    # API Endpoints
    path('api/interventions/<int:student_id>/', StudentInterventionView.as_view(), name='student-intervention-api'),

    # ============================================================
    # EXPORT ROUTES
    # ============================================================
    path('export/exam/<uuid:exam_id>/<str:format>/', export_exam, name='export_exam'),
    path('export/exam/<uuid:exam_id>/', export_exam, {'format': 'pdf'}, name='export_exam_pdf'),
    path('export/report-card/<uuid:report_card_id>/<str:format>/', export_report_card, name='export_report_card'),
    path('export/report-card/<uuid:report_card_id>/', export_report_card, {'format': 'pdf'},
         name='export_report_card_pdf'),
    path('export/risk-assessment/<uuid:assessment_id>/<str:format>/', export_risk_assessment,
         name='export_risk_assessment'),
    path('export/risk-assessment/<uuid:assessment_id>/', export_risk_assessment, {'format': 'pdf'},
         name='export_risk_assessment_pdf'),
    path('export/finance-insights/<str:format>/', export_finance_insights, name='export_finance_insights'),
    path('export/finance-insights/', export_finance_insights, {'format': 'pdf'}, name='export_finance_insights_pdf'),

]