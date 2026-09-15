# communication/urls.py
from django.urls import path
from . import views

app_name = 'communication'

urlpatterns = [
    # Main inbox
    path('', views.communication_inbox, name='inbox'),
    path('announcements/manage/', views.announcement_management, name='announcement_management'),

    # Announcements
    path('announcement/<uuid:announcement_id>/', views.announcement_detail, name='announcement_detail'),
    path('api/announcement/post/', views.api_post_announcement, name='api_post_announcement'),
    path('api/announcement/<uuid:announcement_id>/toggle-archive/', views.announcement_toggle_archive,
         name='announcement_toggle_archive'),
    path('api/announcement/<uuid:announcement_id>/publish/', views.announcement_publish, name='announcement_publish'),

    # Notifications
    path('notifications/', views.notification_list, name='notification_list'),
    path('notification-center/', views.notification_center, name='notification_center'),
    path('notifications/<uuid:notification_id>/read/', views.notification_mark_read, name='notification_mark_read'),
    path('notifications/mark-all-read/', views.notification_mark_all_read, name='notification_mark_all_read'),
    path('preferences/', views.notification_preferences, name='notification_preferences'),

    # Logs (Admin only)
    path('logs/', views.notification_log_list, name='notification_log_list'),
    path('analytics/', views.notification_analytics, name='notification_analytics'),
    path('logs/<uuid:notification_id>/retry/', views.notification_retry, name='notification_retry'),
]