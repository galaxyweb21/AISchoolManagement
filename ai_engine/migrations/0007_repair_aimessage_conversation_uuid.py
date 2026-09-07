"""
Repair the AIMessage conversation foreign-key column.

Some deployed PostgreSQL databases have ai_engine_aimessage.conversation_id
left as BIGINT even though AIConversation.id and the current Django model use
UUIDs.  The main Copilot page prefetches messages, which makes PostgreSQL
compare BIGINT conversation_id values with UUID conversation IDs and raises:

    operator does not exist: bigint = uuid

AI chat history is non-business-critical and can safely be rebuilt.  Recreate
AIMessage using the current model definition so PostgreSQL gets a UUID primary
key and, critically, a UUID conversation_id foreign key.

This migration deliberately does not modify AIConversation, Ghana Education
Copilot, or any other AI tables.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        (
            "ai_engine",
            "0006_alter_reportcommentbatch_triggered_by",
        ),
    ]

    operations = [
        # Drop the physically incorrect table first.  Existing Copilot chat
        # messages are intentionally discarded because their conversation FK
        # cannot be safely mapped from BIGINT to the UUID conversation IDs.
        migrations.DeleteModel(
            name="AIMessage",
        ),
        migrations.CreateModel(
            name="AIMessage",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("USER", "User"),
                            ("AI", "AI"),
                            ("SYSTEM", "System"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "content",
                    models.TextField(),
                ),
                (
                    "execution_time",
                    models.FloatField(default=0),
                ),
                (
                    "model_name",
                    models.CharField(
                        blank=True,
                        max_length=100,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="ai_engine.aiconversation",
                    ),
                ),
            ],
        ),
    ]
