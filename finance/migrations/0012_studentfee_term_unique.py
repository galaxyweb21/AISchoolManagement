from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0011_alter_classaddonitem_unique_together'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='studentfee',
            name='unique_student_fee_structure',
        ),
        migrations.AddConstraint(
            model_name='studentfee',
            constraint=models.UniqueConstraint(
                fields=('student', 'academic_term'),
                name='unique_student_fee_term',
            ),
        ),
    ]
