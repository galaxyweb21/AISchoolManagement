from django.db import migrations, models
import uuid
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('ai_engine','0009_report_card_release_automation')]
    operations=[
        migrations.CreateModel(name='EmailHealthCheck',fields=[
            ('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),
            ('recipient_email',models.EmailField(blank=True,default='',max_length=254)),
            ('success',models.BooleanField(default=False)),
            ('connection_verified',models.BooleanField(default=False)),
            ('message',models.TextField(blank=True,default='')),
            ('duration_ms',models.PositiveIntegerField(default=0)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('school',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='email_health_checks',to='school.school')),
            ('tested_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='accounts.user')),
        ],options={'ordering':['-created_at']}),
        migrations.AddField(model_name='reportcarddelivery',name='last_attempt_at',field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='reportcarddelivery',name='next_retry_at',field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='reportcarddelivery',name='retry_count',field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddIndex(model_name='reportcarddelivery',index=models.Index(fields=['status','next_retry_at'],name='rcdelivery_retry_idx')),
        migrations.AddIndex(model_name='reportcarddelivery',index=models.Index(fields=['release_batch','status'],name='rcdelivery_batch_status_idx')),
    ]
