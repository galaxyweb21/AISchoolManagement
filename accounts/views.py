from core.pagination import paginate_queryset
# accounts/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.views.generic import TemplateView, UpdateView
from django.urls import reverse_lazy
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
import json

from .models import User
from .forms import *
from .models import Role

# Import dashboard context helpers from dashboard app
from dashboard.views import (
    get_admin_dashboard_context,
    get_teacher_dashboard_context,
    get_parent_dashboard_context,
    get_bursar_dashboard_context,
    get_registrar_dashboard_context,
    get_hod_dashboard_context,
    get_secretary_dashboard_context,
)


# ============================================================
# USER ACCESS VIEWS
# ============================================================

def user_access_list(request):
    users = User.objects.prefetch_related("user_roles__role")
    return render(request, "accounts/users/user_access.html", {"users": paginate_queryset(users, request)})


def user_access_detail(request, pk):
    user = get_object_or_404(User, pk=pk)
    context = {"user_obj": user}
    return render(request, "accounts/users/user_detail.html", context)


# ============================================================
# ROLE-BASED DASHBOARD VIEW
# ============================================================

class RoleBasedDashboardView(LoginRequiredMixin, TemplateView):
    """
    Renders a unified dashboard route that tailors content
    and metrics according to the user's assigned role.
    """

    def get_template_names(self):
        user = self.request.user
        role_templates = {
            'SUPER_ADMIN': ['dashboard/index.html'],
            'SCHOOL_ADMIN': ['dashboard/index.html'],
            'BURSAR': ['dashboard/bursar_dashboard.html'],
            'REGISTRAR': ['dashboard/registrar_dashboard.html'],
            'HOD': ['dashboard/hod_dashboard.html'],
            'SECRETARY': ['dashboard/secretary_dashboard.html'],
            'TEACHER': ['dashboard/teacher_dashboard.html'],
            'PARENT': ['dashboard/parent_dashboard.html'],
            'STUDENT': ['dashboard/student_dashboard.html'],
        }
        return role_templates.get(user.role, ['dashboard/index.html'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        school = user.school

        context['user'] = user
        context['school'] = school
        context['user_role'] = user.role

        # Get role-specific context
        if user.role in ['SUPER_ADMIN', 'SCHOOL_ADMIN'] and school:
            context.update(get_admin_dashboard_context(school))
        elif user.role == 'BURSAR' and school:
            context.update(get_bursar_dashboard_context(school))
        elif user.role == 'REGISTRAR' and school:
            context.update(get_registrar_dashboard_context(school))
        elif user.role == 'HOD' and school:
            context.update(get_hod_dashboard_context(user, school))
        elif user.role == 'SECRETARY' and school:
            context.update(get_secretary_dashboard_context(school))
        elif user.role == 'TEACHER':
            context.update(get_teacher_dashboard_context(user, school))
        elif user.role == 'PARENT':
            context.update(get_parent_dashboard_context(user, school))

        return context


# ============================================================
# AUTHENTICATION VIEWS
# ============================================================

class UserLoginView(View):
    template_name = 'registration/login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('accounts:dashboard')
        form = LoginForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f"Welcome back, {user.first_name or user.username}!")
                return redirect('accounts:dashboard')
            else:
                messages.error(request, "Invalid username or password.")
        return render(request, self.template_name, {'form': form})


class UserLogoutView(View):
    def get(self, request):
        logout(request)
        messages.info(request, "You have been logged out.")
        return redirect('accounts:login')

    def post(self, request):
        logout(request)
        messages.info(request, "You have been logged out.")
        return redirect('accounts:login')


# ============================================================
# PROFILE VIEWS
# ============================================================

class UserProfileView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserProfileForm
    template_name = 'accounts/profile.html'
    success_url = reverse_lazy('accounts:profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Profile updated successfully.")
        return super().form_valid(form)


@login_required
def profile_view(request):
    """Enhanced user profile view with full update capabilities."""
    user = request.user

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()

        current_password = request.POST.get('current_password', '')
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        errors = []

        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        if email and email != user.email:
            if User.objects.filter(email=email).exclude(id=user.id).exists():
                errors.append('This email is already in use.')
            else:
                user.email = email

        if phone_number:
            user.phone_number = phone_number

        if current_password or new_password or confirm_password:
            if not user.check_password(current_password):
                errors.append('Current password is incorrect.')
            elif new_password and len(new_password) < 8:
                errors.append('New password must be at least 8 characters long.')
            elif new_password != confirm_password:
                errors.append('New passwords do not match.')
            elif new_password:
                user.set_password(new_password)
                messages.info(request, 'Your password has been updated. Please login again.')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            user.save(update_fields=['first_name', 'last_name', 'email', 'phone_number'])
            messages.success(request, 'Profile updated successfully!')

            if new_password:
                logout(request)
                messages.info(request, 'Please login with your new password.')
                return redirect('accounts:login')

        return redirect('accounts:profile')

    context = {
        'user': user,
        'role_display': user.get_role_display(),
        'school': user.school,
    }
    return render(request, 'accounts/profile.html', context)


@login_required
def profile_edit(request):
    """Edit profile with AJAX support."""
    user = request.user

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        bio = request.POST.get('bio', '').strip()

        profile_picture = request.FILES.get('profile_picture')

        errors = []

        if first_name:
            user.first_name = first_name
        if last_name:
            user.last_name = last_name
        if email and email != user.email:
            if User.objects.filter(email=email).exclude(id=user.id).exists():
                errors.append('Email already in use.')
            else:
                user.email = email
        if phone_number:
            user.phone_number = phone_number
        if bio:
            user.bio = bio

        if profile_picture:
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            import os
            import uuid

            ext = os.path.splitext(profile_picture.name)[1]
            filename = f'profile_pics/{user.id}_{uuid.uuid4().hex}{ext}'
            saved_path = default_storage.save(filename, ContentFile(profile_picture.read()))
            user.profile_picture = saved_path

        if errors:
            return JsonResponse({'success': False, 'errors': errors})

        user.save(update_fields=['first_name', 'last_name', 'email', 'phone_number'])

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Profile updated successfully!',
                'user': {
                    'full_name': user.get_full_name(),
                    'email': user.email,
                    'phone_number': user.phone_number,
                    'role': user.get_role_display(),
                }
            })

        messages.success(request, 'Profile updated successfully!')
        return redirect('accounts:profile')

    return render(request, 'accounts/profile_edit.html', {'user': user})


@login_required
def profile_settings(request):
    """User settings page with theme and notification preferences."""
    user = request.user

    if request.method == 'POST':
        theme = request.POST.get('theme', 'light')
        request.session['theme'] = theme

        email_notifications = request.POST.get('email_notifications') == 'on'
        sms_notifications = request.POST.get('sms_notifications') == 'on'
        ai_insights = request.POST.get('ai_insights') == 'on'

        request.session['email_notifications'] = email_notifications
        request.session['sms_notifications'] = sms_notifications
        request.session['ai_insights'] = ai_insights

        messages.success(request, 'Settings updated successfully!')
        return redirect('accounts:profile_settings')

    theme = request.session.get('theme', 'light')
    email_notifications = request.session.get('email_notifications', True)
    sms_notifications = request.session.get('sms_notifications', False)
    ai_insights = request.session.get('ai_insights', True)

    context = {
        'user': user,
        'theme': theme,
        'email_notifications': email_notifications,
        'sms_notifications': sms_notifications,
        'ai_insights': ai_insights,
    }
    return render(request, 'accounts/profile_settings.html', context)


# ============================================================
# THEME UPDATE API
# ============================================================

@login_required
@csrf_exempt
def update_theme(request):
    """API endpoint to update theme via AJAX."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            theme = data.get('theme', 'light')

            if theme not in ['light', 'dark']:
                return JsonResponse({'success': False, 'error': 'Invalid theme'}, status=400)

            request.session['theme'] = theme
            return JsonResponse({'success': True, 'theme': theme})
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)


# ============================================================
# ROLE MANAGEMENT VIEWS
# ============================================================

def role_list(request):
    roles = Role.objects.prefetch_related("permissions")
    context = {
        "roles": paginate_queryset(roles, request),
        "page_title": "Role Management",
    }
    return render(request, "accounts/roles/role_list.html", context)


def role_create(request):
    form = RoleForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, "Role created successfully.")
        return redirect("accounts:role_list")
    return render(request, "accounts/roles/role_form.html", {"form": form})


def role_update(request, pk):
    role = get_object_or_404(Role, pk=pk)
    form = RoleForm(request.POST or None, instance=role)
    if form.is_valid():
        form.save()
        messages.success(request, "Role updated successfully.")
        return redirect("accounts:role_list")
    return render(request, "accounts/roles/role_form.html", {"form": form, "role": role})


def role_delete(request, pk):
    role = get_object_or_404(Role, pk=pk)
    role.delete()
    messages.success(request, "Role deleted successfully.")
    return redirect("accounts:role_list")
