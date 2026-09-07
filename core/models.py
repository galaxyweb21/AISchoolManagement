# core/models.py
from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from school.models import School
import uuid


class ActivityLog(models.Model):
    ACTION_CHOICES = (
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('VIEW', 'View'),
        ('LOGIN', 'Login'),
        ('LOGOUT', 'Logout'),
    )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='activity_logs',
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='activity_logs',
    )

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
    )

    object_id = models.CharField(
        max_length=100,
    )

    content_object = GenericForeignKey(
        'content_type',
        'object_id',
    )

    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
    )

    description = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Human readable description of what happened"
        ),
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'

    def __str__(self):
        username = (
            self.user.username
            if self.user
            else "System"
        )

        return (
            f"{username} "
            f"{self.action} "
            f"{self.content_object} "
            f"at {self.created_at}"
        )