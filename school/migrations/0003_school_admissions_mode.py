from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('school', '0002_school_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='school',
            name='admissions_mode',
            field=models.CharField(
                choices=[
                    ('OFF', 'Disabled'),
                    ('JHS_SHS', 'JHS and SHS only'),
                    ('ALL', 'All school levels'),
                ],
                default='OFF',
                help_text='Controls whether the optional Admissions workflow is available and which school levels may use it.',
                max_length=10,
            ),
        ),
    ]
