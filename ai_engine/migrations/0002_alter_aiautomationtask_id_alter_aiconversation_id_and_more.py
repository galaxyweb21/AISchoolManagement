"""
Gives AIConversation, AIMessage, and AIAutomationTask a UUID primary key
instead of the BigAutoField they were created with in 0001_initial.

WHY NOT A PLAIN AlterField (what this migration used to do)
-------------------------------------------------------------
The previous version of this migration used AlterField to change these
three id columns from BigAutoField straight to UUIDField in place. That
is a valid *operation* on MySQL - MODIFY COLUMN there stringifies each
existing integer (e.g. 1 becomes the string "1") - but it is not valid
on PostgreSQL at all: Postgres has no cast from any integer type to
uuid, so the SQL Django generates for it,

    ALTER TABLE ... ALTER COLUMN id TYPE uuid USING id::uuid

fails immediately with "cannot cast type bigint to uuid" - on every
PostgreSQL database, empty or not, every single time. This project
deploys on Render's managed Postgres (see render.yaml -> databases),
so that migration could never actually succeed there, which is why
"python manage.py migrate" was failing before ever reaching the app -
or, if it had been force-marked as applied without truly running,
would leave the real column still an integer while Django's ORM
believed it was UUID, producing exactly the crash described in
0003_repair_invalid_uuid_primary_keys.py's docstring
("badly formed hexadecimal UUID string" -> 500 on GET /ai-engine/copilot/).

WHY DeleteModel + CreateModel INSTEAD
---------------------------------------
These three tables only ever hold Copilot chat history / automation-task
audit rows - nothing else in the schema reads their row data (only
AIMessage.conversation_id points *into* AIConversation, and that FK is
recreated fresh below, right after AIConversation). Dropping and
recreating them with the UUID primary key from the start sidesteps the
impossible cast entirely and behaves identically on Postgres, MySQL,
and SQLite. The only cost is discarding any AI chat history created
before this migration runs, which is an acceptable trade for a school
app where that history is not business-critical data - versus a
migration that cannot run at all against this project's real database.
"""

import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('ai_engine', '0001_initial'),
    ]

    operations = [
        # Child model first (has a ForeignKey to AIConversation).
        migrations.DeleteModel(name='AIMessage'),
        migrations.DeleteModel(name='AIConversation'),
        migrations.DeleteModel(name='AIAutomationTask'),

        migrations.CreateModel(
            name='AIConversation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_archived', models.BooleanField(default=False)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='school.school')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='AIMessage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('role', models.CharField(choices=[('USER', 'User'), ('AI', 'AI'), ('SYSTEM', 'System')], max_length=20)),
                ('content', models.TextField()),
                ('execution_time', models.FloatField(default=0)),
                ('model_name', models.CharField(blank=True, max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='ai_engine.aiconversation')),
            ],
        ),
        migrations.CreateModel(
            name='AIAutomationTask',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('task_type', models.CharField(max_length=100)),
                ('priority', models.CharField(choices=[('LOW', 'Low'), ('MEDIUM', 'Medium'), ('HIGH', 'High'), ('CRITICAL', 'Critical')], default='MEDIUM', max_length=20)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('RUNNING', 'Running'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed'), ('CANCELLED', 'Cancelled')], default='PENDING', max_length=20)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_ai_tasks', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_ai_tasks', to=settings.AUTH_USER_MODEL)),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='automation_tasks', to='school.school')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['school', 'status'], name='ai_engine_a_school__000148_idx'), models.Index(fields=['task_type'], name='ai_engine_a_task_ty_c56980_idx'), models.Index(fields=['priority'], name='ai_engine_a_priorit_e42efb_idx')],
            },
        ),
    ]
