from django.db import migrations, models


CONSTRAINT_NAME = 'uniq_notification_reference_per_recipient'


def normalize_empty_references(apps, schema_editor):
    NotificationLog = apps.get_model('communication', 'NotificationLog')

    # Convert empty strings to NULL so that optional references remain
    # consistent across database backends.
    NotificationLog.objects.filter(reference_id='').update(reference_id=None)
    NotificationLog.objects.filter(reference_type='').update(reference_type=None)


def drop_existing_constraint_if_present(apps, schema_editor):
    NotificationLog = apps.get_model('communication', 'NotificationLog')

    # Check whether the old conditional constraint exists in the database.
    # Database introspection is backend-aware and works with PostgreSQL and
    # MySQL-compatible databases.
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor,
            NotificationLog._meta.db_table,
        )

    if CONSTRAINT_NAME not in constraints:
        return

    # Use Django's public schema-editor API. Do not call private methods such
    # as _constraint_names() or _delete_constraint_sql(), because their
    # signatures vary between Django/database backends.
    existing_constraint = models.UniqueConstraint(
        fields=(
            'recipient',
            'category',
            'reference_id',
            'reference_type',
        ),
        name=CONSTRAINT_NAME,
    )

    schema_editor.remove_constraint(
        NotificationLog,
        existing_constraint,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('communication', '0002_notification_reference_uniqueness'),
    ]

    operations = [
        migrations.RunPython(
            normalize_empty_references,
            migrations.RunPython.noop,
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    drop_existing_constraint_if_present,
                    migrations.RunPython.noop,
                ),
                migrations.AddConstraint(
                    model_name='notificationlog',
                    constraint=models.UniqueConstraint(
                        fields=(
                            'recipient',
                            'category',
                            'reference_id',
                            'reference_type',
                        ),
                        name=CONSTRAINT_NAME,
                    ),
                ),
            ],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='notificationlog',
                    name=CONSTRAINT_NAME,
                ),
                migrations.AddConstraint(
                    model_name='notificationlog',
                    constraint=models.UniqueConstraint(
                        fields=(
                            'recipient',
                            'category',
                            'reference_id',
                            'reference_type',
                        ),
                        name=CONSTRAINT_NAME,
                    ),
                ),
            ],
        ),
    ]