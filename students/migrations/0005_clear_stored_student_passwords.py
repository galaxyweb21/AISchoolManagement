from django.db import migrations


def clear_plaintext_passwords(apps, schema_editor):
    Student = apps.get_model('students', 'Student')
    Student.objects.exclude(default_password__isnull=True).update(default_password=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('students', '0004_admissionapplication'),
        ('accounts', '0003_clear_stored_plaintext_passwords'),
    ]
    operations = [migrations.RunPython(clear_plaintext_passwords, noop)]
