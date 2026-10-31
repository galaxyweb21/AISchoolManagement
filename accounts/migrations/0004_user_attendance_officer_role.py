from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_clear_stored_plaintext_passwords'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('SUPER_ADMIN', 'Super Admin'),
                    ('SCHOOL_ADMIN', 'School Admin'),
                    ('BURSAR', 'Bursar/Finance'),
                    ('REGISTRAR', 'Registrar'),
                    ('HOD', 'Head of Department'),
                    ('SECRETARY', 'Secretary'),
                    ('ATTENDANCE_OFFICER', 'Attendance Officer'),
                    ('TEACHER', 'Teacher'),
                    ('STUDENT', 'Student'),
                    ('PARENT', 'Parent'),
                ],
                default='STUDENT',
                max_length=20,
            ),
        ),
    ]
