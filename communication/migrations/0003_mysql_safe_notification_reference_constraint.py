from django.db import migrations, models


CONSTRAINT_NAME = 'uniq_notification_reference_per_recipient'


def normalize_empty_references(apps, schema_editor):
    NotificationLog = apps.get_model('communication', 'NotificationLog')

    NotificationLog.objects.filter(
        reference_id=''
    ).update(reference_id=None)

    NotificationLog.objects.filter(
        reference_type=''
    ).update(reference_type=None)


def drop_existing_constraint_if_present(apps, schema_editor):
    """
    Migration 0002 created a conditional UniqueConstraint.

    On PostgreSQL, Django represents a conditional UniqueConstraint as a
    unique index, not as an ALTER TABLE constraint. Therefore it must be
    removed with DROP INDEX rather than remove_constraint().
    """
    NotificationLog = apps.get_model('communication', 'NotificationLog')
    table_name = NotificationLog._meta.db_table
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor,
            table_name,
        )

    existing_constraint = constraints.get(CONSTRAINT_NAME)

    if not existing_constraint:
        return

    # The conditional unique constraint from migration 0002 is a PostgreSQL
    # unique index. Drop the index safely if it exists.
    if connection.vendor == 'postgresql':
        schema_editor.execute(
            'DROP INDEX IF EXISTS %s'
            % schema_editor.quote_name(CONSTRAINT_NAME)
        )
        return

    # This branch is retained for database backends where Django reports the
    # object as a regular table constraint.
    if existing_constraint.get('index') is False:
        schema_editor.execute(
            'ALTER TABLE %s DROP CONSTRAINT %s'
            % (
                schema_editor.quote_name(table_name),
                schema_editor.quote_name(CONSTRAINT_NAME),
            )
        )
        return

    # Generic index fallback for other supported database backends.
    if existing_constraint.get('unique') or existing_constraint.get('index'):
        if connection.vendor == 'mysql':
            schema_editor.execute(
                'DROP INDEX %s ON %s'
                % (
                    schema_editor.quote_name(CONSTRAINT_NAME),
                    schema_editor.quote_name(table_name),
                )
            )
        else:
            schema_editor.execute(
                'DROP INDEX IF EXISTS %s'
                % schema_editor.quote_name(CONSTRAINT_NAME)
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