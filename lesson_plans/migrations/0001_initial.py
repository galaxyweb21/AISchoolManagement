# Generated for EduAI teacher weekly lesson-plan workflow.
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('academics', '0008_subject_school_name_curriculum_level'),
        ('school', '0003_school_admissions_mode'),
        ('staff', '0009_clear_stored_staff_passwords'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='WeeklyLessonPlan',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('week_start', models.DateField(help_text='Monday of the teaching week')),
                ('topic', models.CharField(max_length=200)),
                ('subtopic', models.CharField(blank=True, max_length=200)),
                ('learning_objectives', models.TextField()),
                ('teaching_resources', models.TextField(blank=True)),
                ('introduction', models.TextField()),
                ('lesson_development', models.TextField()),
                ('conclusion', models.TextField(blank=True)),
                ('assessment', models.TextField()),
                ('reflection', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('SUBMITTED', 'Submitted for review'), ('REVISION_REQUESTED', 'Revision requested'), ('APPROVED', 'Approved')], db_index=True, default='DRAFT', max_length=24)),
                ('teacher_submitted_at', models.DateTimeField(blank=True, null=True)),
                ('reviewer_comment', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='weekly_lesson_plans', to='school.academicterm')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='weekly_lesson_plans', to='school.school')),
                ('school_class', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='weekly_lesson_plans', to='academics.schoolclass')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='weekly_lesson_plans', to='academics.subject')),
                ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='weekly_lesson_plans', to='staff.teacher')),
                ('reviewer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_lesson_plans', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-week_start', 'school_class__name', 'subject__name']},
        ),
        migrations.AddConstraint(
            model_name='weeklylessonplan',
            constraint=models.UniqueConstraint(fields=('school', 'teacher', 'academic_term', 'week_start', 'school_class', 'subject'), name='uniq_weekly_lesson_plan_scope'),
        ),
        migrations.AddIndex(
            model_name='weeklylessonplan',
            index=models.Index(fields=['school', 'status', 'week_start'], name='lesson_school_status_week_idx'),
        ),
        migrations.AddIndex(
            model_name='weeklylessonplan',
            index=models.Index(fields=['teacher', 'week_start'], name='lesson_teacher_week_idx'),
        ),
    ]
