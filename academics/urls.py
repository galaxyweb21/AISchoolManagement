# academics/urls.py
from django.urls import path
from . import views
from .timetable_setup_views import timetable_setup_assistant, timetable_setup
from .timetable_capacity_views import timetable_capacity_manager
from .curriculum_views import apply_curriculum_subjects, curriculum_subject_options, sync_subjects_to_classes

app_name = 'academics'

urlpatterns = [
    # Timetabler
    path('timetable/', views.timetable_workspace, name='timetable_workspace'),
    path('timetable/setup/', timetable_setup, name='timetable_setup'),
    path('timetable/configuration/', views.timetable_configuration, name='timetable_configuration'),
    path('timetable/setup-assistant/', timetable_setup_assistant, name='timetable_setup_assistant'),
    path('timetable/capacity-manager/', timetable_capacity_manager, name='timetable_capacity_manager'),
    path('timetable/generate/', views.generate_timetable, name='generate_timetable'),
    path('timetable/<uuid:timetable_id>/', views.timetable_detail, name='timetable_detail'),
    path('timetable/<uuid:timetable_id>/export/pdf/', views.timetable_export_pdf, name='timetable_export_pdf'),
    path('timetable/<uuid:timetable_id>/export/word/', views.timetable_export_word, name='timetable_export_word'),
    path('timetable/<uuid:timetable_id>/publish/', views.publish_timetable, name='publish_timetable'),
    path('timetable/<uuid:timetable_id>/delete/', views.delete_timetable, name='delete_timetable'),

    # Subjects
    path('subjects/', views.subject_list, name='subject_list'),
    path('subjects/curriculum/options/', curriculum_subject_options, name='curriculum_subject_options'),
    path('subjects/curriculum/apply-to-classes/', apply_curriculum_subjects, name='apply_curriculum_subjects'),
    path('subjects/curriculum/sync/', sync_subjects_to_classes, name='sync_subjects_to_classes'),
    path('subjects/create/', views.subject_create, name='subject_create'),
    path('subjects/<uuid:subject_id>/edit/', views.subject_edit, name='subject_edit'),
    path('subjects/<uuid:subject_id>/delete/', views.subject_delete, name='subject_delete'),

    # Classes (The ones we are fixing)
    path('classes/', views.school_class_list, name='school_class_list'),
    path('classes/create/', views.school_class_create, name='school_class_create'),
    path('classes/<uuid:class_id>/edit/', views.school_class_edit, name='school_class_edit'),
    path('classes/<uuid:class_id>/delete/', views.school_class_delete, name='school_class_delete'),

    # Rooms & Timeslots
    path('rooms/', views.room_list, name='room_list'),
    path('rooms/create/', views.room_create, name='room_create'),
    path('rooms/<uuid:room_id>/edit/', views.room_edit, name='room_edit'),
    path('rooms/<uuid:room_id>/delete/', views.room_delete, name='room_delete'),
    path('timeslots/', views.timeslot_list, name='timeslot_list'),
    path('timeslots/create/', views.timeslot_create, name='timeslot_create'),
    path('timeslots/generate-ges/', views.timeslot_generate_ges, name='timeslot_generate_ges'),
    path('timeslots/<uuid:timeslot_id>/edit/', views.timeslot_edit, name='timeslot_edit'),
    path('timeslots/<uuid:timeslot_id>/delete/', views.timeslot_delete, name='timeslot_delete'),

    # ============================================================
    # STUDENT PROMOTION URLS
    # ============================================================
    path('promotion/', views.promotion_dashboard, name='promotion_dashboard'),

    # Promotion Batches
    path('promotion/batches/', views.promotion_batch_list, name='promotion_batch_list'),
    path('promotion/batches/create/', views.promotion_batch_create, name='promotion_batch_create'),
    path('promotion/batches/<uuid:batch_id>/', views.promotion_batch_detail, name='promotion_batch_detail'),
    path('promotion/batches/<uuid:batch_id>/apply/', views.promotion_bulk_apply, name='promotion_bulk_apply'),
    path('promotion/results/<uuid:promotion_id>/', views.promotion_result_detail, name='promotion_result_detail'),

    # Promotion Actions
    path('promotion/<uuid:promotion_id>/apply/', views.promotion_apply, name='promotion_apply'),

    # Promotion Rules
    path('promotion/rules/', views.promotion_rule_list, name='promotion_rule_list'),
    path('promotion/rules/create/', views.promotion_rule_create, name='promotion_rule_create'),
    path('promotion/rules/<uuid:rule_id>/edit/', views.promotion_rule_edit, name='promotion_rule_edit'),
    path('promotion/rules/<uuid:rule_id>/delete/', views.promotion_rule_delete, name='promotion_rule_delete'),
]