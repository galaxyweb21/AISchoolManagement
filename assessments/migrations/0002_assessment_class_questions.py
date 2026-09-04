from django.db import migrations, models
import django.db.models.deletion
import uuid

class Migration(migrations.Migration):
    dependencies = [('assessments', '0001_initial'), ('academics', '0002_initial')]
    operations = [
        migrations.AddField(
            model_name='assessment', name='school_class',
            field=models.ForeignKey(blank=True, help_text='Class this assessment belongs to.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assessments', to='academics.schoolclass'),
        ),
        migrations.CreateModel(
            name='AssessmentQuestion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('order', models.PositiveIntegerField(default=0)),
                ('question_type', models.CharField(choices=[('MCQ','Multiple Choice'),('TRUE_FALSE','True / False'),('SHORT_ANSWER','Short Answer'),('ESSAY','Essay')], default='SHORT_ANSWER', max_length=20)),
                ('question_text', models.TextField()),
                ('options', models.JSONField(blank=True, default=list)),
                ('correct_answer', models.TextField(blank=True)),
                ('marks', models.PositiveIntegerField(default=1)),
                ('assessment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='assessments.assessment')),
            ],
            options={'ordering': ['order', 'id']},
        ),
    ]
