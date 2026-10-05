from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0007_subject_curriculum_level'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='subject',
            unique_together={('school', 'name', 'curriculum_level')},
        ),
    ]
