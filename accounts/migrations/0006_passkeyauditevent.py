# Generated for passkey security audit history.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_passkeycredential"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PasskeyAuditEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event", models.CharField(choices=[("registered", "Passkey registered"), ("authenticated", "Passkey authentication succeeded"), ("revoked", "Passkey revoked")], max_length=32)),
                ("device_name", models.CharField(blank=True, max_length=120)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("credential", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_events", to="accounts.passkeycredential")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="passkey_audit_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="passkeyauditevent",
            index=models.Index(fields=["user", "-created_at"], name="acct_passkey_audit_user_dt_idx"),
        ),
    ]
