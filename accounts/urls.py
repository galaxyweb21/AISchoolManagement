# accounts/urls.py - Add theme update URL

from django.urls import path
from .views import (
    RoleBasedDashboardView,
    UserLoginView,
    UserLogoutView,
    UserProfileView,
    profile_view,
    profile_edit,
    profile_settings,
    update_theme,  # <-- ADD THIS
    role_list,
    role_create,
    role_update,
    role_delete,
    user_access_list,
    user_access_detail,
)
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('dashboard/', RoleBasedDashboardView.as_view(), name='dashboard'),

    # Profile
    path('profile/', profile_view, name='profile'),
    path('profile/edit/', profile_edit, name='profile_edit'),
    path('profile/settings/', profile_settings, name='profile_settings'),

    # Theme API
    path('update-theme/', update_theme, name='update_theme'),  # <-- ADD THIS

    # Role Management
    path("roles/", role_list, name="role_list"),
    path("roles/create/", role_create, name="role_create"),
    path("roles/<int:pk>/edit/", role_update, name="role_update"),
    path("roles/<int:pk>/delete/", role_delete, name="role_delete"),

    # User Access
    path("users/", user_access_list, name="user_access_list"),
    path("users/<int:pk>/", user_access_detail, name="user_access_detail"),
]