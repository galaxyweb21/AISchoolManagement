from django.db import migrations


def clear_plaintext_passwords(apps, schema_editor):
    StaffProfile = apps.get_model('staff', 'StaffProfile')
    StaffProfile.objects.exclude(default_password__isnull=True).update(default_password=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('staff', '0008_staff_face_registration'),
        ('accounts', '0003_clear_stored_plaintext_passwords'),
    ]
    operations = [migrations.RunPython(clear_plaintext_passwords, noop)]
