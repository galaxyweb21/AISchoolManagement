from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [('ai_engine', '0004_reportcard_attendance_absent_and_more')]

    def mark_existing_comments_manual(apps, schema_editor):
        ReportCard = apps.get_model('ai_engine', 'ReportCard')
        ReportCard.objects.filter(teacher_comment__isnull=False).exclude(teacher_comment='').update(teacher_comment_source='MANUAL')
        ReportCard.objects.filter(headteacher_comment__isnull=False).exclude(headteacher_comment='').update(headteacher_comment_source='MANUAL')


    operations = [
        migrations.AddField(model_name='reportcard', name='teacher_comment_source', field=models.CharField(choices=[('BLANK','Blank'),('AI','AI Generated'),('MANUAL','Manually Edited')], default='BLANK', max_length=10)),
        migrations.AddField(model_name='reportcard', name='headteacher_comment_source', field=models.CharField(choices=[('BLANK','Blank'),('AI','AI Generated'),('MANUAL','Manually Edited')], default='BLANK', max_length=10)),
        migrations.AddField(model_name='reportcard', name='teacher_comment_generated_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='reportcard', name='headteacher_comment_generated_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='reportcard', name='teacher_comment_edited_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='reportcard', name='headteacher_comment_edited_at', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='reportcard', name='teacher_comment_edited_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='edited_teacher_report_comments', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='reportcard', name='headteacher_comment_edited_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='edited_headteacher_report_comments', to=settings.AUTH_USER_MODEL)),
        migrations.CreateModel(
            name='ReportCommentBatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(choices=[('PENDING','Queued'),('RUNNING','Generating'),('COMPLETE','Complete'),('FAILED','Failed')], default='PENDING', max_length=10)),
                ('only_missing', models.BooleanField(default=True)),
                ('regenerate_ai', models.BooleanField(default=False)),
                ('generate_teacher', models.BooleanField(default=True)),
                ('generate_headteacher', models.BooleanField(default=True)),
                ('students_processed', models.PositiveIntegerField(default=0)),
                ('teacher_comments_generated', models.PositiveIntegerField(default=0)),
                ('headteacher_comments_generated', models.PositiveIntegerField(default=0)),
                ('students_skipped_finalized', models.PositiveIntegerField(default=0)),
                ('failures', models.PositiveIntegerField(default=0)),
                ('error_message', models.CharField(blank=True, default='', max_length=500)),
                ('academic_term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='report_comment_batches', to='school.academicterm')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='report_comment_batches', to='school.school')),
                ('school_class', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='report_comment_batches', to='academics.schoolclass')),
                ('triggered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='report_comment_batches', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-generated_at']},
        ),
           migrations.RunPython(mark_existing_comments_manual, migrations.RunPython.noop),
    ]
