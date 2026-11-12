from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('ai_engine', '0011_academic_intervention_management'),
        ('school', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='academicinterventionplan',
            name='baseline_term',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='baseline_intervention_plans', to='school.academicterm',
            ),
        ),
        migrations.AddField(
            model_name='academicinterventionplan',
            name='subject',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
    ]
