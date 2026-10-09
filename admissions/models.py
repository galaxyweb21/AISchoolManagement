import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from school.models import School, AcademicYear
from students.models import GradeLevel
from academics.models import SchoolClass
from school.services import managers


class AdmissionApplication(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('REVIEW', 'Under Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('ADMITTED', 'Admitted'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='admission_applications')
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name='admission_applications')
    application_number = models.CharField(max_length=40, unique=True, editable=False)

    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    applicant_phone = models.CharField(max_length=30, blank=True)
    applicant_email = models.EmailField(blank=True)
    applicant_address = models.TextField(blank=True)

    grade_level = models.ForeignKey(GradeLevel, on_delete=models.PROTECT, related_name='admission_applications')
    school_class = models.ForeignKey(SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name='admission_applications')

    parent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='admission_applications_as_parent', limit_choices_to={'role': 'PARENT'})
    parent_name = models.CharField(max_length=200)
    parent_relationship = models.CharField(max_length=60, blank=True)
    parent_phone = models.CharField(max_length=30)
    parent_email = models.EmailField(blank=True)
    parent_address = models.TextField(blank=True)
    previous_school = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUBMITTED')
    rejection_reason = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admitted_at = models.DateTimeField(null=True, blank=True)
    admitted_student = models.OneToOneField(
        'students.Student', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='admission_application'
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_admission_applications')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_admission_applications')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['school', 'status']),
            models.Index(fields=['school', 'academic_year']),
        ]

    def save(self, *args, **kwargs):
        if not self.application_number:
            year = self.academic_year.start_date.year if self.academic_year_id else timezone.localdate().year
            prefix = f"APP-{year}-"
            seq = AdmissionApplication.objects.filter(
                school=self.school, application_number__startswith=prefix
            ).count() + 1
            candidate = f"{prefix}{seq:04d}"
            while AdmissionApplication.objects.filter(application_number=candidate).exclude(pk=self.pk).exists():
                seq += 1
                candidate = f"{prefix}{seq:04d}"
            self.application_number = candidate
        super().save(*args, **kwargs)

    @property
    def applicant_name(self):
        return ' '.join(p for p in [self.first_name, self.middle_name, self.last_name] if p).strip()

    @property
    def can_admit(self):
        return self.status == 'APPROVED' and self.admitted_student_id is None

    def __str__(self):
        return f"{self.application_number} — {self.applicant_name}"
