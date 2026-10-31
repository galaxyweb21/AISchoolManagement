from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('online_exams', '0003_onlineexam_assessment_record'),
    ]

    operations = [
        migrations.AddField(
            model_name='onlineexam',
            name='student_access_enabled',
            field=models.BooleanField(default=True, help_text='When disabled, this examination remains staff-managed and is not shown in the student online examination portal.'),
        ),
    ]
