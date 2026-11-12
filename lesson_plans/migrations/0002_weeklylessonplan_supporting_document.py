# Generated for optional teacher-uploaded lesson note documents.
from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ('lesson_plans', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='weeklylessonplan',
            name='supporting_document',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='lesson_plan_documents/%Y/%m/',
                validators=[django.core.validators.FileExtensionValidator(allowed_extensions=['pdf', 'doc', 'docx'])],
                help_text='Optional lesson note document (PDF, DOC or DOCX; maximum 10 MB).',
            ),
        ),
    ]
