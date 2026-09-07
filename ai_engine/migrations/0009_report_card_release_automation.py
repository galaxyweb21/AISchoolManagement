from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [('ai_engine', '0008_reportcard_signature_snapshots')]
    operations = [
        migrations.CreateModel(
            name='ReportCardReleaseBatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('PENDING','Queued'),('RUNNING','Processing'),('COMPLETE','Complete'),('PARTIAL','Partial - some cards blocked'),('FAILED','Failed')], default='PENDING', max_length=12)),
                ('auto_finalize', models.BooleanField(default=True)),
                ('email_parents', models.BooleanField(default=True)),
                ('generate_print_pack', models.BooleanField(default=True)),
                ('generated_count', models.PositiveIntegerField(default=0)),
                ('finalized_count', models.PositiveIntegerField(default=0)),
                ('blocked_count', models.PositiveIntegerField(default=0)),
                ('emailed_count', models.PositiveIntegerField(default=0)),
                ('email_failed_count', models.PositiveIntegerField(default=0)),
                ('email_skipped_count', models.PositiveIntegerField(default=0)),
                ('print_pack_count', models.PositiveIntegerField(default=0)),
                ('print_pack', models.FileField(blank=True, null=True, upload_to='report_card_print_packs/%Y/%m/')),
                ('print_pack_generated_at', models.DateTimeField(blank=True, null=True)),
                ('blocked_details', models.JSONField(blank=True, default=list)),
                ('error_message', models.TextField(blank=True, default='')),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('academic_term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='report_card_release_batches', to='school.academicterm')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='report_card_release_batches', to='school.school')),
                ('triggered_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='accounts.user')),
            ],
            options={'ordering':['-created_at']},
        ),
        migrations.CreateModel(
            name='ReportCardDelivery',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('recipient_email', models.EmailField(blank=True, default='', max_length=254)),
                ('status', models.CharField(choices=[('PENDING','Pending'),('SENT','Sent'),('FAILED','Failed'),('SKIPPED','Skipped')], default='PENDING', max_length=10)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('release_batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='deliveries', to='ai_engine.reportcardreleasebatch')),
                ('report_card', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='deliveries', to='ai_engine.reportcard')),
            ],
            options={'constraints':[models.UniqueConstraint(fields=('release_batch','report_card'), name='unique_release_report_card_delivery')]},
        ),
    ]
