from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('staff', '0004_alter_gradeallowance_unique_together_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffprofile',
            name='signature_image',
            field=models.ImageField(
                blank=True,
                help_text='Official handwritten signature used on report cards. Prefer a transparent PNG.',
                null=True,
                upload_to='staff_signatures/',
            ),
        ),
        migrations.AddField(
            model_name='staffprofile',
            name='signature_uploaded_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When the current official signature was uploaded.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='staffprofile',
            name='signature_is_active',
            field=models.BooleanField(
                default=True,
                help_text='When enabled, this signature may be automatically placed on official report cards.',
            ),
        ),
        migrations.AddField(
            model_name='staffprofile',
            name='is_headteacher',
            field=models.BooleanField(
                default=False,
                help_text="Designate this staff member as the school's Headteacher / Head of School for report-card approvals.",
            ),
        ),
    ]
