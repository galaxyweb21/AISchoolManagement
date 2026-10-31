import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("accounts", "0004_user_attendance_officer_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="PasskeyCredential",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("credential_id", models.TextField()),
                ("credential_id_hash", models.CharField(max_length=64, unique=True)),
                ("public_key", models.BinaryField()),
                ("sign_count", models.PositiveBigIntegerField(default=0)),
                ("device_name", models.CharField(default="This device", max_length=120)),
                ("transports", models.JSONField(blank=True, default=list)),
                ("device_type", models.CharField(blank=True, max_length=32)),
                ("backed_up", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="passkey_credentials", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="passkeycredential",
            index=models.Index(fields=["user", "is_active"], name="acct_passkey_user_active_idx"),
        ),
    ]
