# ai_engine/views/__init__.py
from .api import api_generate_feedback
from .risk import risk_dashboard, trigger_risk_assessment, student_risk_detail
from .reports import (
    report_card_dashboard, trigger_report_card_batch, report_card_detail,
    save_report_card_narrative, regenerate_report_card_narrative,
    finalize_report_card, unfinalize_report_card, trigger_report_comment_batch, generate_report_card_comment
)
from .finance import (
    finance_insights_dashboard, invoice_risk_detail,
    generate_reminder, save_reminder, mark_reminder_sent
)
from .exams import (
    exam_dashboard, create_exam, exam_detail,
    save_exam_question, regenerate_exam_question, delete_exam_question,
    add_exam_question, link_exam_to_assessment,
    unlink_exam_from_assessment,
    delete_exam, delete_all_exam_questions
)
from .parents import parent_children_list, parent_chat_thread
from .command_center import ai_command_center, predictive_student_detail, intervention_center

# IMPORTANT: Import from copilot module
from .copilot import (
    ai_copilot_page,
    ai_copilot_api,
    get_conversation_messages,
    delete_conversation,
)

from .automation import approve_task
from .absences import (
    absence_list, report_absence, cover_plan_detail,
    regenerate_cover_plan, confirm_substitute, unconfirm_substitute,
    save_handover_note
)
from .ghana_education import (
    ghana_education_home,
    ghana_education_topic_detail,
    ghana_education_search,
    ghana_education_ask_copilot,
)
from .exports import (
    export_exam,
    export_report_card,
    export_risk_assessment,
    export_finance_insights,
)

__all__ = [
    'api_generate_feedback',
    'risk_dashboard', 'trigger_risk_assessment', 'student_risk_detail',
    'report_card_dashboard', 'trigger_report_card_batch', 'report_card_detail',
    'save_report_card_narrative', 'regenerate_report_card_narrative',
    'finalize_report_card', 'unfinalize_report_card', 'trigger_report_comment_batch', 'generate_report_card_comment',
    'finance_insights_dashboard', 'invoice_risk_detail',
    'generate_reminder', 'save_reminder', 'mark_reminder_sent',
    'exam_dashboard', 'create_exam', 'exam_detail',
    'save_exam_question', 'regenerate_exam_question', 'delete_exam_question',
    'add_exam_question', 'link_exam_to_assessment',
    'unlink_exam_from_assessment',
    'delete_exam', 'delete_all_exam_questions',
    'parent_children_list', 'parent_chat_thread',
    'ai_command_center', 'predictive_student_detail', 'intervention_center',
    'ai_copilot_page', 'ai_copilot_api',
    'get_conversation_messages',
    'delete_conversation',
    'approve_task',
    'absence_list', 'report_absence', 'cover_plan_detail',
    'regenerate_cover_plan', 'confirm_substitute', 'unconfirm_substitute',
    'save_handover_note',
    'ghana_education_home',
    'ghana_education_topic_detail',
    'ghana_education_search',
    'ghana_education_ask_copilot',
    'export_exam',
    'export_report_card',
    'export_risk_assessment',
    'export_finance_insights',
]