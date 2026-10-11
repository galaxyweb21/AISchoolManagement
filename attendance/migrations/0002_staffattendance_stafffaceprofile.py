# Generated for staff attendance and optional face-recognition enrollment.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('attendance', '0001_initial'),
        ('school', '0001_initial'),
        ('staff', '0007_rename_staff_grade_allowance_idx_staff_grade_staff_g_3ecd81_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffAttendance',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('date', models.DateField()),
                ('status', models.CharField(choices=[('PRESENT', 'Present'), ('LATE', 'Late'), ('ABSENT', 'Absent'), ('EXCUSED', 'Excused')], default='PRESENT', max_length=15)),
                ('method', models.CharField(choices=[('MANUAL', 'Manual'), ('FACE', 'Face Recognition')], default='MANUAL', max_length=10)),
                ('check_in', models.DateTimeField(blank=True, null=True)),
                ('check_out', models.DateTimeField(blank=True, null=True)),
                ('remarks', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('marked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='marked_staff_attendance', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_attendance_records', to='school.school')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attendance_records', to='staff.staffprofile')),
            ],
            options={
                'ordering': ['-date', 'staff__user__last_name', 'staff__user__first_name'],
                'indexes': [
                    models.Index(fields=['school', 'date'], name='attendance_sch_date_idx'),
                    models.Index(fields=['staff', 'date'], name='attendance_stf_date_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='StaffFaceProfile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('encoding', models.JSONField(blank=True, null=True)),
                ('photo', models.ImageField(blank=True, null=True, upload_to='staff_face_profiles/')),
                ('registered_at', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('registered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='registered_staff_faces', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='staff_face_profiles', to='school.school')),
                ('staff', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='face_profile', to='staff.staffprofile')),
            ],
            options={
                'ordering': ['staff__user__last_name', 'staff__user__first_name'],
                'indexes': [models.Index(fields=['school', 'is_active'], name='attendance_sch_active_idx')],
            },
        ),
        migrations.AddConstraint(
            model_name='staffattendance',
            constraint=models.UniqueConstraint(fields=('staff', 'date'), name='unique_staff_attendance_day'),
        ),
    ]
