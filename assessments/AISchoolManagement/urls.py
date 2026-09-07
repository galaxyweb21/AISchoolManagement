"""
URL configuration for AISchoolManagement project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

# AISchoolManagement/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", health_check, name="healthz"),
    path('admin/', admin.site.urls),

    # Authentication Routes
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    # App Routes
    path('', include('dashboard.urls')),
    path('accounts/', include('accounts.urls')),
    path('ai-engine/', include('ai_engine.urls')),
    path('assessments/', include('assessments.urls')),
    path('finance/', include('finance.urls')),
    path('attendance/', include('attendance.urls')),
    path('communication/', include('communication.urls')),
    path('school/', include('school.urls')),
    path('academics/', include('academics.urls')),
    path('students/', include('students.urls')),
    path('staff/', include('staff.urls')),
    path('library/', include('library.urls')),

]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)