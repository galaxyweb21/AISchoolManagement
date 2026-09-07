# school/models.py
from django.db import models
from django.utils.text import slugify
import uuid


# school/models.py
from django.db import models
from django.utils.text import slugify
import uuid


class School(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    subdomain = models.CharField(
        max_length=100, unique=True, blank=True,
        help_text=(
            "Short internal identifier used to prefix invoice/receipt/admission numbers "
            "(e.g. 'greenwood' -> INV-GREE-2026-00001). Doesn't need to be a real domain -- "
            "auto-generated from the school name if left blank."
        )
    )
    address = models.TextField()
    contact_email = models.EmailField()
    phone_number = models.CharField(max_length=20)
    logo = models.ImageField(
        upload_to='school_logos/',
        blank=True,
        null=True,
        help_text="Upload a logo for your school (recommended size: 200x200px)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def _generate_unique_subdomain(self):
        """Generate a unique subdomain from the school name."""
        base_slug = slugify(self.name)[:90]
        if not base_slug:
            base_slug = 'school'

        candidate = base_slug
        suffix = 2
        while School.objects.filter(subdomain=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base_slug}-{suffix}"[:100]
            suffix += 1

        return candidate

    def save(self, *args, **kwargs):
        if not self.subdomain:
            self.subdomain = self._generate_unique_subdomain()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AcademicYear(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='academic_years')
    name = models.CharField(max_length=100, help_text="e.g., 2025/2026 Academic Year")
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.school.name})"


class AcademicTerm(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name='terms')
    name = models.CharField(max_length=100, help_text="e.g., First Term, Fall Semester")
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.academic_year.name}"