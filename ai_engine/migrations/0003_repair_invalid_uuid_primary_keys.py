# ai_engine/migrations/0003_repair_invalid_uuid_primary_keys.py
"""
Repairs data left broken by 0002_alter_aiautomationtask_id_alter_aiconversation_id_and_more.

WHAT WENT WRONG
---------------
0002 changed AIConversation.id / AIMessage.id / AIAutomationTask.id from a
plain auto-incrementing integer to a UUIDField. That migration only
changes the column's *type* in the database - on MySQL, ALTER TABLE ...
MODIFY COLUMN converts each existing integer value to its string form
(e.g. the integer 1 becomes the 3-character string "1"), not to a real
UUID. Any conversation/message/task created before 0002 ran is left with
an id like "1", "2", "3" sitting in a column Django now expects to
contain 32-character UUID hex strings. Reading those rows back through
the ORM then fails with exactly this error:

    ValueError: badly formed hexadecimal UUID string

which is what shows up as a 500 on GET /ai-engine/copilot/ (that page
lists the user's existing conversations).

WHAT THIS MIGRATION DOES
-------------------------
For every row whose id is not a valid UUID, generates a real uuid4 and
rewrites it in place - repointing AIMessage.conversation_id first so no
message is ever left pointing at a conversation id that's about to
change. Brand new rows (already valid UUIDs, e.g. anything created after
0002 ran, or in a fresh database that never had integer ids to begin
with) are left untouched.

IMPORTANT: this deliberately reads and writes with a raw SQL cursor
instead of the ORM/QuerySet API. Using AIConversation.objects.all() (or
.values()) here would hit the exact same "badly formed hexadecimal UUID
string" crash while trying to read the broken rows, since Django applies
the same UUID conversion on every ORM read. A raw cursor returns the
stored value exactly as-is, with no conversion, which is what lets this
migration actually see and fix the broken values.

This is a one-way repair: the original invalid ids are gone once
replaced, so there is no meaningful way to reverse it.
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
    connection = schema_editor.connection
    is_mysql = connection.vendor == "mysql"

    with connection.cursor() as cursor:

        if is_mysql:
            # Updating a parent row's primary key while foreign key
            # constraints are enforced (InnoDB checks each statement
            # immediately, unlike Postgres' deferrable constraints)
            # would otherwise reject the UPDATE below. Safe here because
            # every dependent row is repointed to its matching new id
            # within this same migration before checks are re-enabled.
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")

        try:
            # ----------------------------------------------------------
            # AIConversation.id (+ dependent AIMessage.conversation_id)
            # ----------------------------------------------------------
            cursor.execute(
                "SELECT id FROM ai_engine_aiconversation"
            )
            conversation_ids = [row[0] for row in cursor.fetchall()]

            for old_id in conversation_ids:

                if _is_valid_uuid(old_id):
                    continue

                # Django's UUIDField stores values as 32-character
                # hex with no dashes on both MySQL and SQLite
                # (char(32) columns) - str(uuid.uuid4()) would
                # produce the 36-character dashed form instead,
                # which overflows/truncates against that column
                # width. .hex matches the column correctly.
                new_id = uuid.uuid4().hex

                cursor.execute(
                    "UPDATE ai_engine_aimessage "
                    "SET conversation_id = %s "
                    "WHERE conversation_id = %s",
                    [new_id, str(old_id)],
                )
                cursor.execute(
                    "UPDATE ai_engine_aiconversation "
                    "SET id = %s WHERE id = %s",
                    [new_id, str(old_id)],
                )

            # ----------------------------------------------------------
            # AIMessage.id (independent - nothing has a FK to a message)
            # ----------------------------------------------------------
            cursor.execute(
                "SELECT id FROM ai_engine_aimessage"
            )
            message_ids = [row[0] for row in cursor.fetchall()]

            for old_id in message_ids:

                if _is_valid_uuid(old_id):
                    continue

                # Django's UUIDField stores values as 32-character
                # hex with no dashes on both MySQL and SQLite
                # (char(32) columns) - str(uuid.uuid4()) would
                # produce the 36-character dashed form instead,
                # which overflows/truncates against that column
                # width. .hex matches the column correctly.
                new_id = uuid.uuid4().hex

                cursor.execute(
                    "UPDATE ai_engine_aimessage "
                    "SET id = %s WHERE id = %s",
                    [new_id, str(old_id)],
                )

            # ----------------------------------------------------------
            # AIAutomationTask.id (independent)
            # ----------------------------------------------------------
            cursor.execute(
                "SELECT id FROM ai_engine_aiautomationtask"
            )
            task_ids = [row[0] for row in cursor.fetchall()]

            for old_id in task_ids:

                if _is_valid_uuid(old_id):
                    continue

                # Django's UUIDField stores values as 32-character
                # hex with no dashes on both MySQL and SQLite
                # (char(32) columns) - str(uuid.uuid4()) would
                # produce the 36-character dashed form instead,
                # which overflows/truncates against that column
                # width. .hex matches the column correctly.
                new_id = uuid.uuid4().hex

                cursor.execute(
                    "UPDATE ai_engine_aiautomationtask "
                    "SET id = %s WHERE id = %s",
                    [new_id, str(old_id)],
                )

        finally:
            if is_mysql:
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")


def _noop_reverse(apps, schema_editor):
    # Not reversible - the original invalid ids are discarded once
    # replaced with real UUIDs, so there is nothing to restore them to.
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
