# accounts/models.py
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from school.models import School
import uuid


# accounts/models.py - Add default_password field to User model

class User(AbstractUser):
    ROLE_CHOICES = (
        ('SUPER_ADMIN', 'Super Admin'),
        ('SCHOOL_ADMIN', 'School Admin'),
        ('BURSAR', 'Bursar/Finance'),
        ('REGISTRAR', 'Registrar'),
        ('HOD', 'Head of Department'),
        ('SECRETARY', 'Secretary'),
        ('TEACHER', 'Teacher'),
        ('STUDENT', 'Student'),
        ('PARENT', 'Parent'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users'
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='STUDENT')
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)

    # Store default password for admin reference
    default_password = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="The default password assigned when the account was created"
    )

    def clean(self):
        """Ensure non-Super Admins are always linked to a School."""
        super().clean()
        if self.role != 'SUPER_ADMIN' and not self.school:
            raise ValidationError({'school': 'School is required for all roles except Super Admin.'})

    def get_school(self):
        return self.school

    def get_role_display(self):
        """Helper to display role nicely in templates"""
        return dict(self.ROLE_CHOICES).get(self.role, self.role)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


# ============================================================
# ENTERPRISE RBAC SYSTEM (Kept exactly as you had it, cleaned)
# ============================================================

class Permission(models.Model):
    ACTIONS = (
        ("view", "View"),
        ("create", "Create"),
        ("edit", "Edit"),
        ("delete", "Delete"),
        ("approve", "Approve"),
        ("export", "Export"),
        ("print", "Print"),
    )

    module = models.CharField(max_length=100)
    code = models.CharField(max_length=100, unique=True)
    action = models.CharField(max_length=30, choices=ACTIONS, null=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["module", "action"]
        unique_together = ("module", "action")

    def save(self, *args, **kwargs):
        self.code = f"{self.module}.{self.action}"
        if not self.name:
            self.name = f"{self.module.title()} - {self.action.title()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="#4f46e5")
    icon = models.CharField(max_length=50, default="bi bi-person-badge")
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    permissions = models.ManyToManyField(Permission, through="RolePermission", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("role", "permission")


class UserRole(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name="role_assignments",
                                    on_delete=models.SET_NULL)
    assigned_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["user"]

    def __str__(self):
        return f"{self.user} - {self.role}"


class UserSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    session_key = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    browser = models.CharField(max_length=255, blank=True)
    operating_system = models.CharField(max_length=255, blank=True)
    device = models.CharField(max_length=255, blank=True)
    last_activity = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.session_key[:8]}"