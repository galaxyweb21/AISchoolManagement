from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ai_engine', '0007_repair_aimessage_conversation_uuid'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportcard',
            name='teacher_signature_snapshot',
            field=models.ImageField(blank=True, null=True, upload_to='report_card_signatures/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='reportcard',
            name='teacher_signature_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='reportcard',
            name='headteacher_signature_snapshot',
            field=models.ImageField(blank=True, null=True, upload_to='report_card_signatures/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='reportcard',
            name='headteacher_signature_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
