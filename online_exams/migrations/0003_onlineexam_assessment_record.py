from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('assessments', '0004_rename_assessments_school_3f7d2c_idx_assessments_school__449aee_idx_and_more'),
        ('online_exams', '0002_onlineexam_topic'),
    ]

    operations = [
        migrations.AddField(
            model_name='onlineexam',
            name='assessment_record',
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='source_online_exam', to='assessments.assessment',
                help_text='Assessment record created when reviewed online exam results are exported.',
            ),
        ),
    ]
