from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('online_exams', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='onlineexam',
            name='topic',
            field=models.CharField(blank=True, default='', help_text='Topic or unit used for AI-assisted question generation.', max_length=200),
        ),
    ]
