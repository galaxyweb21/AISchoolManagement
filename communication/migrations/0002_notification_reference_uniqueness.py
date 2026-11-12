from django.db import migrations, models
from django.db.models import Count, Q


def remove_duplicate_notifications(apps, schema_editor):
    NotificationLog = apps.get_model('communication', 'NotificationLog')

    duplicates = (
        NotificationLog.objects
        .exclude(reference_id__isnull=True)
        .exclude(reference_id='')
        .exclude(reference_type__isnull=True)
        .exclude(reference_type='')
        .values('recipient_id', 'category', 'reference_id', 'reference_type')
        .annotate(row_count=Count('id'))
        .filter(row_count__gt=1)
    )

    for group in duplicates.iterator():
        qs = NotificationLog.objects.filter(
            recipient_id=group['recipient_id'],
            category=group['category'],
            reference_id=group['reference_id'],
            reference_type=group['reference_type'],
        ).order_by('-created_at', '-id')

        keep = qs.first()
        if not keep:
            continue

        # Keep the newest record and remove older duplicates. The newest record
        # represents the latest delivery/read state and therefore best matches
        # what the user currently sees in the Notification Center.
        qs.exclude(pk=keep.pk).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('communication', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(remove_duplicate_notifications, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='notificationlog',
            constraint=models.UniqueConstraint(
                fields=('recipient', 'category', 'reference_id', 'reference_type'),
                condition=(
                    Q(reference_id__isnull=False)
                    & ~Q(reference_id='')
                    & Q(reference_type__isnull=False)
                    & ~Q(reference_type='')
                ),
                name='uniq_notification_reference_per_recipient',
            ),
        ),
    ]
