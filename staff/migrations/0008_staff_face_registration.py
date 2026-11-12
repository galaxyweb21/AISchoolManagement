from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("staff", "0007_rename_staff_grade_allowance_idx_staff_grade_staff_g_3ecd81_idx_and_more"),
    ]

    operations = [
        migrations.AddField(model_name="staffprofile", name="face_encoding", field=models.JSONField(blank=True, null=True, help_text="Face encoding data used for staff face attendance.")),
        migrations.AddField(model_name="staffprofile", name="face_registered", field=models.BooleanField(default=False, help_text="Whether this staff member has a registered face.")),
        migrations.AddField(model_name="staffprofile", name="face_photo", field=models.ImageField(blank=True, null=True, upload_to="staff_faces/%Y/%m/", help_text="Reference photo captured during face registration.")),
        migrations.AddField(model_name="staffprofile", name="face_registered_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="staffprofile", name="face_registered_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="registered_staff_profile_faces", to=settings.AUTH_USER_MODEL)),
    ]
