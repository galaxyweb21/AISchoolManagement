import uuid
from datetime import time
from django.conf import settings
from django.db import models
from school.models import School
from students.models import Student


class Attendance(models.Model):
    STATUS_CHOICES = (
        ('PRESENT', 'Present'),
        ('ABSENT', 'Absent'),
        ('LATE', 'Late'),
        ('EXCUSED', 'Excused'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name='attendance_records'
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='attendance_records'
    )
    date = models.DateField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PRESENT')
    remarks = models.CharField(max_length=255, blank=True, null=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role': 'TEACHER'},
    )

    class Meta:
        unique_together = ('student', 'date')

    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.date}: {self.status}"

class StaffAttendance(models.Model):
    """Daily attendance record for a staff member."""

    STATUS_CHOICES = (
        ('PRESENT', 'Present'),
        ('LATE', 'Late'),
        ('ABSENT', 'Absent'),
        ('EXCUSED', 'Excused'),
    )

    METHOD_CHOICES = (
        ('MANUAL', 'Manual'),
        ('FACE', 'Face Recognition'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='staff_attendance_records',
    )
    staff = models.ForeignKey(
        'staff.StaffProfile',
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    date = models.DateField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PRESENT')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='MANUAL')
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    remarks = models.CharField(max_length=255, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marked_staff_attendance',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'staff__user__last_name', 'staff__user__first_name']
        constraints = [
            models.UniqueConstraint(fields=['staff', 'date'], name='unique_staff_attendance_day'),
        ]
        indexes = [
            models.Index(fields=['school', 'date']),
            models.Index(fields=['staff', 'date']),
        ]

    def __str__(self):
        return f"{self.staff} - {self.date}: {self.status}"


class StaffFaceProfile(models.Model):
    """Face-recognition enrollment for a staff member.

    The model is deliberately separate from StaffProfile so existing HR and
    payroll data remain untouched. Face recognition stays optional: manual
    attendance continues to work when face_recognition/dlib is unavailable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='staff_face_profiles',
    )
    staff = models.OneToOneField(
        'staff.StaffProfile',
        on_delete=models.CASCADE,
        related_name='face_profile',
    )
    encoding = models.JSONField(null=True, blank=True)
    photo = models.ImageField(upload_to='staff_face_profiles/', null=True, blank=True)
    registered_at = models.DateTimeField(null=True, blank=True)
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registered_staff_faces',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['staff__user__last_name', 'staff__user__first_name']
        indexes = [models.Index(fields=['school', 'is_active'])]

    def __str__(self):
        return f"Face profile - {self.staff}"


class StaffAttendanceSettings(models.Model):
    """Per-school staff attendance window; enforcement is opt-in until configured."""
    school = models.OneToOneField(
        School, on_delete=models.CASCADE, related_name='staff_attendance_settings'
    )
    check_in_start = models.TimeField(default=time(6, 0))
    check_in_end = models.TimeField(default=time(9, 0))
    school_end = models.TimeField(default=time(14, 0))
    enforce_time_windows = models.BooleanField(
        default=False,
        help_text='When enabled, attendance officers can only mark check-ins during the configured window. School admins can override.'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Staff attendance settings'
        verbose_name_plural = 'Staff attendance settings'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.check_in_end <= self.check_in_start:
            raise ValidationError({'check_in_end': 'Check-in closing time must be after the opening time.'})
        if self.school_end <= self.check_in_start:
            raise ValidationError({'school_end': 'School closing time must be after check-in opening time.'})

    def __str__(self):
        return f'Staff attendance settings — {self.school}'
