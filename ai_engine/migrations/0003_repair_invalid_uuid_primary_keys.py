# ai_engine/migrations/0003_repair_invalid_uuid_primary_keys.py
"""
Originally repaired data left broken by
0002_alter_aiautomationtask_id_alter_aiconversation_id_and_more when
that migration used AlterField to change these three id columns from
integer to UUID in place.

0002 has since been rewritten to drop and recreate these three tables
with a UUID primary key from the start (see that file's docstring for
why - the in-place AlterField this repair was written for can never
succeed on PostgreSQL, which is what this project actually deploys on).
Because 0002 now always produces fresh, empty tables, there is no
legacy non-UUID data left for this migration to find or fix - the
repair loops below become an intentional no-op. This file is kept
(rather than deleted) only because 0004_reportcard_attendance_absent...
already depends on it by name; renumbering everything downstream is
unnecessary risk for zero benefit.
"""

import uuid

from django.db import migrations


def _is_valid_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def repair_invalid_uuid_primary_keys(apps, schema_editor):
    """
    No-op: kept only for historical/documentation purposes. See the
    module docstring above - 0002 now always produces fresh, empty
    AIConversation/AIMessage/AIAutomationTask tables, so there is never
    legacy non-UUID data here to repair.
    """
    return


def _noop_reverse(apps, schema_editor):
    # Not reversible - the original invalid ids (when this migration
    # actually did something, on databases where 0002 predates its
    # rewrite) are discarded once replaced, so there is nothing to
    # restore them to.
    pass


class Migration(migrations.Migration):

    dependencies = [
        (
            "ai_engine",
            "0002_alter_aiautomationtask_id_alter_aiconversation_id_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            repair_invalid_uuid_primary_keys,
            _noop_reverse,
        ),
    ]


class Migration(migrations.Migration):

    dependencies = [
        (
            "ai_engine",
            "0002_alter_aiautomationtask_id_alter_aiconversation_id_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            repair_invalid_uuid_primary_keys,
            _noop_reverse,
        ),
    ]
