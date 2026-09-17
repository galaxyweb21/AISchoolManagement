from django.db import migrations, models


def normalize_empty_references(apps, schema_editor):
    NotificationLog = apps.get_model('communication', 'NotificationLog')
    NotificationLog.objects.filter(reference_id='').update(reference_id=None)
    NotificationLog.objects.filter(reference_type='').update(reference_type=None)


def drop_existing_constraint_if_present(apps, schema_editor):
    model = apps.get_model('communication', 'NotificationLog')
    constraint_name = 'uniq_notification_reference_per_recipient'

    # Phase 1N originally created a conditional unique constraint. PostgreSQL
    # can have that constraint in the database, while the replacement in this
    # migration is an unconditional unique constraint.
    #
    # IMPORTANT: _delete_constraint_sql() requires BOTH the model and the
    # constraint name on Django 4.2. Passing the introspection dictionary entry
    # here causes Render/PostgreSQL to fail with:
    #   missing 2 required positional arguments: 'model' and 'name'
    #
    # Use Django's schema-editor constraint lookup so this remains backend-
    # aware instead of constructing raw SQL.
    existing_names = schema_editor._constraint_names(model, name=constraint_name)
    for existing_name in existing_names:
        schema_editor.execute(
            schema_editor._delete_constraint_sql(model, existing_name)
        )


class Migration(migrations.Migration):
    dependencies = [
        ('communication', '0002_notification_reference_uniqueness'),
    ]

    operations = [
        migrations.RunPython(normalize_empty_references, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(drop_existing_constraint_if_present, migrations.RunPython.noop),
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
