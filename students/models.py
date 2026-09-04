# students/models.py
from django.db import models
from django.utils import timezone
from school.models import School
from django.conf import settings
from school.services import managers
import uuid
from dateutil.relativedelta import relativedelta
import json


class GradeLevel(models.Model):
    # Ghana Education Service (GES) / NaCCA Standards-Based Curriculum stages.
    # A school can still name levels however it likes (see `name` below --
    # kept freeform for schools outside Ghana, or ones using local aliases
    # like "Class 1" instead of "Basic 1"), but tagging the STAGE explicitly
    # is what lets the AI exam generator know which GES curriculum band
    # (and therefore which NaCCA strands/content standards) a level belongs
    # to, rather than guessing from an arbitrary name string.
    STAGE_CHOICES = (
        ('KG', 'Kindergarten'),
        ('PRIMARY', 'Primary (Basic 1-6)'),
        ('JHS', 'Junior High School (Basic 7-9)'),
        ('SHS', 'Senior High School'),
        ('OTHER', 'Other / Not GES-aligned'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='grade_levels')
    name = models.CharField(max_length=100, help_text="e.g., Basic 1 (Class 1), JHS 2, SHS 3")
    stage = models.CharField(
        max_length=10, choices=STAGE_CHOICES, default='OTHER',
        help_text="GES curriculum band this level belongs to -- used to align AI-generated "
                   "exam questions with the correct NaCCA Standards-Based Curriculum content."
    )
    order = models.PositiveIntegerField(default=0, help_text="Display order for sorting")

    class Meta:
        ordering = ['order', 'name']
        unique_together = ['school', 'name']

    def __str__(self):
        return self.name


# students/models.py - Add these new models

class StudentEnrollmentType(models.Model):
    """
    Defines different enrollment types for students.
    Used to determine which fee package applies to a student.
    """
    ENROLLMENT_TYPE_CHOICES = [
        ('NEW', 'New Student'),
        ('RETURNING', 'Returning Student'),
        ('TRANSFER', 'Transfer Student'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='enrollment_types')
    name = models.CharField(max_length=50, choices=ENROLLMENT_TYPE_CHOICES)
    code = models.CharField(max_length=20, choices=ENROLLMENT_TYPE_CHOICES)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    # Auto-apply settings
    auto_prepare_fees = models.BooleanField(default=True)
    auto_approve_fees = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['order', 'name']
        unique_together = ['school', 'code']

    def __str__(self):
        return self.get_name_display()


# students/models.py - Update Student model

class Student(models.Model):
    ID_CARD_CHOICES = (
        ('GHANA_CARD', 'Ghana Card'),
        ('VOTER_ID', 'Voter ID'),
        ('PASSPORT', 'Passport'),
        ('BIRTH_CERT', 'Birth Certificate'),
        ('OTHER', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='students')
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                limit_choices_to={'role': 'STUDENT'})
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        limit_choices_to={'role': 'PARENT'}
    )
    admission_number = models.CharField(max_length=50, unique=True, editable=False)
    date_of_birth = models.DateField()

    grade_level = models.ForeignKey(GradeLevel, on_delete=models.PROTECT, related_name='students')
    school_class = models.ForeignKey(
        'academics.SchoolClass',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_enrollments'
    )
    # ==========================================================
    # ENROLLMENT TYPE FIELDS
    # ==========================================================
    enrollment_type = models.ForeignKey(
        StudentEnrollmentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='students',
        help_text="The enrollment type for this student (New, Returning, Transfer)"
    )
    is_new_student = models.BooleanField(
        default=True,
        help_text="True if this is the student's first enrollment at the school"
    )
    previous_school = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Previous school if transfer student"
    )
    enrollment_history = models.JSONField(
        default=list,
        blank=True,
        help_text="Historical enrollment records"
    )
    # ==========================================================
    # CREDENTIALS STORAGE - Store raw password for admin reference
    # ==========================================================
    default_password = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="The default password assigned when the student account was created"
    )

    # ==========================================================
    # FACE RECOGNITION FIELDS
    # ==========================================================
    face_encoding = models.JSONField(
        null=True,
        blank=True,
        help_text="Face encoding data for facial recognition (stored as JSON array)"
    )
    face_registered = models.BooleanField(
        default=False,
        help_text="Whether the student's face has been registered for recognition"
    )
    profile_photo = models.ImageField(
        upload_to='student_faces/%Y/%m/',
        blank=True,
        null=True,
        help_text="Profile photo used for face recognition"
    )
    face_registered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the face was last registered/updated"
    )
    face_registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registered_faces',
        help_text="Who registered this student's face"
    )

    address = models.TextField(blank=True, null=True, help_text="Residential address of the student")
    contact_phone = models.CharField(max_length=20, blank=True, null=True, help_text="Student's direct phone number")
    id_card_type = models.CharField(max_length=20, choices=ID_CARD_CHOICES, blank=True, null=True)
    id_card_number = models.CharField(max_length=50, blank=True, null=True,
                                      help_text="Ghana Card / Voter ID / Passport number")

    enrollment_date = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    objects = managers.TenantManager()

    @classmethod
    def generate_admission_number(cls, school, year=None):
        year = year or timezone.localdate().year
        prefix = f"{school.subdomain[:4].upper()}-{year}-"
        sequence = cls.objects.filter(school=school, admission_number__startswith=prefix).count() + 1
        candidate = f"{prefix}{sequence:04d}"
        while cls.objects.filter(admission_number=candidate).exists():
            sequence += 1
            candidate = f"{prefix}{sequence:04d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.admission_number:
            self.admission_number = self.generate_admission_number(self.school)
        super().save(*args, **kwargs)

    @property
    def age(self):
        if not self.date_of_birth:
            return "N/A"
        today = timezone.localdate()
        diff = relativedelta(today, self.date_of_birth)
        if diff.years > 0:
            return f"{diff.years} years"
        elif diff.months > 0:
            return f"{diff.months} months"
        else:
            return f"{diff.days} days"

    @property
    def age_in_years(self):
        if not self.date_of_birth:
            return 0
        today = timezone.localdate()
        return today.year - self.date_of_birth.year - (
                (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )

    @property
    def has_face_registered(self):
        """Check if student has a valid face encoding"""
        return bool(self.face_registered and self.face_encoding)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.admission_number})"