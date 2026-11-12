# Initial schema for scheduled online examinations and student attempts.
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('academics', '0008_subject_school_name_curriculum_level'),
        ('school', '0003_school_admissions_mode'),
        ('students', '0006_delete_admissionapplication'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='OnlineExam',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=200)),
                ('instructions', models.TextField(blank=True, default='')),
                ('duration_minutes', models.PositiveSmallIntegerField(default=45, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(300)])),
                ('opens_at', models.DateTimeField()),
                ('closes_at', models.DateTimeField()),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('PUBLISHED', 'Published'), ('CLOSED', 'Closed')], db_index=True, default='DRAFT', max_length=12)),
                ('randomize_questions', models.BooleanField(default=False)),
                ('results_released', models.BooleanField(default=False)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='online_exams', to='school.academicterm')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_online_exams', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='online_exams', to='school.school')),
                ('school_class', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='online_exams', to='academics.schoolclass')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='online_exams', to='academics.subject')),
            ],
            options={'ordering': ['-opens_at', '-created_at']},
        ),
        migrations.CreateModel(
            name='OnlineExamQuestion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('order', models.PositiveIntegerField(default=1)),
                ('question_type', models.CharField(choices=[('MCQ', 'Multiple choice'), ('TRUE_FALSE', 'True / False'), ('SHORT_ANSWER', 'Short answer'), ('ESSAY', 'Essay')], default='MCQ', max_length=20)),
                ('question_text', models.TextField()),
                ('options', models.JSONField(blank=True, default=list, help_text='Options for multiple-choice questions.')),
                ('correct_answer', models.TextField(blank=True, default='')),
                ('marks', models.PositiveSmallIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(100)])),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('exam', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='online_exams.onlineexam')),
            ],
            options={'ordering': ['order', 'created_at']},
        ),
        migrations.CreateModel(
            name='ExamAttempt',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('IN_PROGRESS', 'In progress'), ('SUBMITTED', 'Submitted'), ('EXPIRED', 'Expired')], db_index=True, default='IN_PROGRESS', max_length=15)),
                ('grading_status', models.CharField(choices=[('PENDING', 'Pending'), ('REVIEW_REQUIRED', 'Teacher review required'), ('GRADED', 'Graded')], db_index=True, default='PENDING', max_length=20)),
                ('started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('score_awarded', models.PositiveIntegerField(default=0)),
                ('total_marks', models.PositiveIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('exam', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempts', to='online_exams.onlineexam')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='online_exam_attempts', to='students.student')),
            ],
            options={'ordering': ['-started_at']},
        ),
        migrations.CreateModel(
            name='ExamAnswer',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('answer_text', models.TextField(blank=True, default='')),
                ('is_correct', models.BooleanField(blank=True, null=True)),
                ('marks_awarded', models.PositiveIntegerField(blank=True, null=True)),
                ('saved_at', models.DateTimeField(auto_now=True)),
                ('attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='online_exams.examattempt')),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='online_exams.onlineexamquestion')),
            ],
        ),
        migrations.AddConstraint(
            model_name='onlineexamquestion',
            constraint=models.UniqueConstraint(fields=('exam', 'order'), name='onex_q_order_uniq'),
        ),
        migrations.AddConstraint(
            model_name='examattempt',
            constraint=models.UniqueConstraint(fields=('exam', 'student'), name='onex_one_attempt_student'),
        ),
        migrations.AddConstraint(
            model_name='examanswer',
            constraint=models.UniqueConstraint(fields=('attempt', 'question'), name='onex_answer_question_uniq'),
        ),
        migrations.AddIndex(
            model_name='onlineexam',
            index=models.Index(fields=['school', 'status', 'opens_at'], name='onex_school_stat_open_idx'),
        ),
    ]
