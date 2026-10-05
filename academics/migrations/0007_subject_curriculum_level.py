from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0006_rename_academics_ts_config_day_after_idx_academics_t_configu_688a4f_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='subject',
            name='curriculum_level',
            field=models.CharField(
                choices=[
                    ('ALL', 'General / All levels'),
                    ('KG', 'KG Learning Areas'),
                    ('PRIMARY', 'Primary'),
                    ('JHS', 'JHS / Common Core'),
                    ('SHS', 'SHS'),
                ],
                default='ALL',
                help_text='Curriculum band this subject belongs to. Legacy/manual subjects use General / All levels until the school classifies them.',
                max_length=10,
            ),
        ),
    ]
