# Generated manually for the Admissions & Enrollment lifecycle.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ('students', '0003_alter_studentenrollmenttype_code_and_more'),
        ('school', '0002_school_logo'),
        ('academics', '0008_subject_school_name_curriculum_level'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AdmissionApplication',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('application_number', models.CharField(editable=False, max_length=50, unique=True)),
                ('first_name', models.CharField(max_length=100)),
                ('middle_name', models.CharField(blank=True, max_length=100)),
                ('last_name', models.CharField(max_length=100)),
                ('date_of_birth', models.DateField()),
                ('gender', models.CharField(blank=True, max_length=20)),
                ('previous_school', models.CharField(blank=True, max_length=200)),
                ('parent_first_name', models.CharField(max_length=100)),
                ('parent_last_name', models.CharField(max_length=100)),
                ('parent_email', models.EmailField(blank=True, max_length=254)),
                ('parent_phone', models.CharField(blank=True, max_length=30)),
                ('address', models.TextField(blank=True)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('SUBMITTED', 'Submitted'), ('UNDER_REVIEW', 'Under Review'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('ADMITTED', 'Admitted')], default='SUBMITTED', max_length=20)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_year', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='admission_applications', to='school.academicyear')),
                ('applying_class', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='admission_applications', to='academics.schoolclass')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_admission_applications', to=settings.AUTH_USER_MODEL)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_admission_applications', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='admission_applications', to='school.school')),
                ('student', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='admission_application', to='students.student')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='admissionapplication',
            index=models.Index(fields=['school', 'status'], name='students_ad_school__e9c1c4_idx'),
        ),
        migrations.AddIndex(
            model_name='admissionapplication',
            index=models.Index(fields=['school', 'academic_year'], name='students_ad_school__4f5f9e_idx'),
        ),
    ]
