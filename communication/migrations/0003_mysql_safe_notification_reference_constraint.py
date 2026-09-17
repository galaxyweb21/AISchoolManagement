from django.db import migrations, models


def normalize_empty_references(apps, schema_editor):
    NotificationLog = apps.get_model('communication', 'NotificationLog')
    NotificationLog.objects.filter(reference_id='').update(reference_id=None)
    NotificationLog.objects.filter(reference_type='').update(reference_type=None)


def drop_existing_constraint_if_present(apps, schema_editor):
    model = apps.get_model('communication', 'NotificationLog')
    constraint_name = 'uniq_notification_reference_per_recipient'

    # Use backend introspection instead of Django's private _constraint_names()
    # because Django 4.2 does not accept 'name=' there. This is required for
    # Render/PostgreSQL deployments and keeps the migration backend-aware.
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor,
            model._meta.db_table,
        )

    if constraint_name not in constraints:
        return

    schema_editor.execute(
        schema_editor._delete_constraint_sql(model, constraint_name)
    )


class Migration(migrations.Migration):
    dependencies = [
        ('communication', '0002_notification_reference_uniqueness'),
    ]

    operations = [
        migrations.RunPython(normalize_empty_references, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    drop_existing_constraint_if_present,
                    migrations.RunPython.noop,
                ),
                migrations.AddConstraint(
                    model_name='notificationlog',
                    constraint=models.UniqueConstraint(
                        fields=('recipient', 'category', 'reference_id', 'reference_type'),
                        name='uniq_notification_reference_per_recipient',
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='notificationlog',
                    name='uniq_notification_reference_per_recipient',
                ),
                migrations.AddConstraint(
                    model_name='notificationlog',
                    constraint=models.UniqueConstraint(
                        fields=('recipient', 'category', 'reference_id', 'reference_type'),
                        name='uniq_notification_reference_per_recipient',
                    ),
                ),
            ],
        ),
    ]