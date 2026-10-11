from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('school', '0003_school_admissions_mode'),
        ('students', '0003_alter_studentenrollmenttype_code_and_more'),
        ('academics', '0008_subject_school_name_curriculum_level'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdmissionApplication',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('application_number', models.CharField(editable=False, max_length=40, unique=True)),
                ('first_name', models.CharField(max_length=100)),
                ('middle_name', models.CharField(blank=True, max_length=100)),
                ('last_name', models.CharField(max_length=100)),
                ('date_of_birth', models.DateField(blank=True, null=True)),
                ('gender', models.CharField(blank=True, max_length=20)),
                ('parent_name', models.CharField(max_length=200)),
                ('parent_phone', models.CharField(max_length=30)),
                ('parent_email', models.EmailField(blank=True, max_length=254)),
                ('previous_school', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('SUBMITTED', 'Submitted'), ('REVIEW', 'Under Review'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('ADMITTED', 'Admitted')], default='SUBMITTED', max_length=20)),
                ('rejection_reason', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('admitted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_year', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='admission_applications', to='school.academicyear')),
                ('admitted_student', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='admission_application', to='students.student')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_admission_applications', to=settings.AUTH_USER_MODEL)),
                ('grade_level', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='admission_applications', to='students.gradelevel')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_admission_applications', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='admission_applications', to='school.school')),
                ('school_class', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='admission_applications', to='academics.schoolclass')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(model_name='admissionapplication', index=models.Index(fields=['school', 'status'], name='admissions__school__e8b7f0_idx')),
        migrations.AddIndex(model_name='admissionapplication', index=models.Index(fields=['school', 'academic_year'], name='admissions__school__d2d7f1_idx')),
    ]
