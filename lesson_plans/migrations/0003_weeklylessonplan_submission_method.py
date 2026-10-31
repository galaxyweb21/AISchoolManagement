from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('lesson_plans', '0002_weeklylessonplan_supporting_document')]

    operations = [migrations.AddField(
        model_name='weeklylessonplan',
        name='submission_method',
        field=models.CharField(choices=[('MANUAL', 'Type lesson note manually'), ('AI', 'Generate with AI and review'), ('UPLOAD', 'Upload an existing document')], default='MANUAL', max_length=12),
    )]
