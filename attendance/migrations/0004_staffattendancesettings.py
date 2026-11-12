from django.db import migrations, models
import datetime
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('attendance', '0003_rename_attendance_sch_date_idx_attendance__school__d91bbe_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffAttendanceSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('check_in_start', models.TimeField(default=datetime.time(6, 0))),
                ('check_in_end', models.TimeField(default=datetime.time(9, 0))),
                ('school_end', models.TimeField(default=datetime.time(14, 0))),
                ('enforce_time_windows', models.BooleanField(default=False, help_text='When enabled, attendance officers can only mark check-ins during the configured window. School admins can override.')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('school', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='staff_attendance_settings', to='school.school')),
            ],
            options={'verbose_name': 'Staff attendance settings', 'verbose_name_plural': 'Staff attendance settings'},
        ),
    ]
