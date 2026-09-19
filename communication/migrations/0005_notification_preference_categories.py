from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("communication", "0004_remove_notificationlog_uniq_notification_reference_per_recipient"),
    ]

    operations = [
        migrations.AddField(
            model_name="usernotificationpreference",
            name="payment_receipt_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="usernotificationpreference",
            name="system_alert_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="usernotificationpreference",
            name="staff_reminder_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
