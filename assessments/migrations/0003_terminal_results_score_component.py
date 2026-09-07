from django.db import migrations, models
import django.db.models.deletion
import uuid


def classify_existing_assessments(apps, schema_editor):
    Assessment = apps.get_model('assessments', 'Assessment')
    Assessment.objects.filter(assessment_type='EXAM').update(score_component='EXAM')
    Assessment.objects.exclude(assessment_type='EXAM').update(score_component='CA')


class Migration(migrations.Migration):
    dependencies = [
        ('assessments', '0002_assessment_class_questions'),
        ('school', '0001_initial'),
        ('academics', '0002_initial'),
        ('students', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='assessment',
            name='score_component',
            field=models.CharField(
                choices=[('CA', 'Class / Continuous Assessment'), ('EXAM', 'End-of-Term Examination'), ('OTHER', 'Other Assessment')],
                db_index=True,
                default='CA',
                help_text='The terminal-results component this assessment contributes to.',
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name='grade',
            name='score_achieved',
            field=models.DecimalField(decimal_places=2, max_digits=7),
        ),
        migrations.CreateModel(
            name='TerminalResult',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('subject', models.CharField(db_index=True, max_length=150)),
                ('class_score', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('exam_score', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('final_score', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('grade', models.CharField(blank=True, default='', max_length=10)),
                ('remark', models.CharField(blank=True, default='', max_length=100)),
                ('class_raw_score', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('class_raw_max', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('exam_raw_score', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('exam_raw_max', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('entry_mode', models.CharField(choices=[('WEIGHTED', 'Weighted 30/70'), ('RAW', 'Raw marks converted to 30/70'), ('CALCULATED', 'Calculated from recorded assessments')], default='WEIGHTED', max_length=12)),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('COMPLETE', 'Complete')], default='DRAFT', max_length=10)),
                ('teacher_note', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('academic_term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='terminal_results', to='school.academicterm')),
                ('entered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='entered_terminal_results', to='accounts.user')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='terminal_results', to='school.school')),
                ('school_class', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='terminal_results', to='academics.schoolclass')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='terminal_results', to='students.student')),
            ],
            options={
                'ordering': ['student__user__last_name', 'student__user__first_name'],
                'unique_together': {('student', 'academic_term', 'school_class', 'subject')},
            },
        ),
        migrations.AddIndex(
            model_name='terminalresult',
            index=models.Index(fields=['school', 'academic_term', 'school_class', 'subject'], name='assessments_school_3f7d2c_idx'),
        ),
        migrations.RunPython(classify_existing_assessments, migrations.RunPython.noop),
    ]
