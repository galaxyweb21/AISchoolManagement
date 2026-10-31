import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ('ai_engine', '0010_email_health_delivery_retry'),
        ('school', '0001_initial'),
        ('students', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AcademicInterventionPlan',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=180)),
                ('concern', models.TextField()),
                ('baseline', models.CharField(blank=True, default='', max_length=240)),
                ('goal', models.TextField()),
                ('strategies', models.TextField()),
                ('priority', models.CharField(choices=[('LOW', 'Low'), ('MEDIUM', 'Medium'), ('HIGH', 'High'), ('CRITICAL', 'Critical')], default='MEDIUM', max_length=10)),
                ('status', models.CharField(choices=[('ACTIVE', 'Active'), ('ON_HOLD', 'On hold'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled')], default='ACTIVE', max_length=12)),
                ('start_date', models.DateField(default=django.utils.timezone.now)),
                ('review_date', models.DateField(blank=True, null=True)),
                ('outcome', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='intervention_plans', to='school.academicterm')),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_academic_interventions', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_academic_interventions', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='academic_intervention_plans', to='school.school')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='academic_intervention_plans', to='students.student')),
            ],
            options={'ordering': ['-updated_at', '-created_at']},
        ),
        migrations.AddIndex(model_name='academicinterventionplan', index=models.Index(fields=['school', 'status'], name='acad_interv_school_status')),
        migrations.AddIndex(model_name='academicinterventionplan', index=models.Index(fields=['student', 'status'], name='acad_interv_student_status')),
        migrations.AddIndex(model_name='academicinterventionplan', index=models.Index(fields=['review_date', 'status'], name='acad_interv_review_status')),
        migrations.CreateModel(
            name='InterventionProgressEntry',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('session_date', models.DateField(default=django.utils.timezone.now)),
                ('activity', models.CharField(max_length=180)),
                ('observation', models.TextField()),
                ('next_step', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='progress_entries', to='ai_engine.academicinterventionplan')),
                ('recorded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='intervention_progress_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-session_date', '-created_at']},
        ),
    ]
