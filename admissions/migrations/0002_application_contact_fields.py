from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("admissions", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name="admissionapplication", name="applicant_phone", field=models.CharField(blank=True, max_length=30)),
        migrations.AddField(model_name="admissionapplication", name="applicant_email", field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name="admissionapplication", name="applicant_address", field=models.TextField(blank=True)),
        migrations.AddField(model_name="admissionapplication", name="parent_relationship", field=models.CharField(blank=True, max_length=60)),
        migrations.AddField(model_name="admissionapplication", name="parent_address", field=models.TextField(blank=True)),
        migrations.AddField(model_name="admissionapplication", name="parent", field=models.ForeignKey(blank=True, limit_choices_to={"role": "PARENT"}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="admission_applications_as_parent", to=settings.AUTH_USER_MODEL)),
    ]
