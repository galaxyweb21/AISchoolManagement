from django.db import migrations


def clear_plaintext_passwords(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.exclude(default_password__isnull=True).update(default_password=None)


def noop(apps, schema_editor):
    # Plaintext credentials cannot be reconstructed from password hashes.
    pass


class Migration(migrations.Migration):
    dependencies = [('accounts', '0002_user_gender')]
    operations = [migrations.RunPython(clear_plaintext_passwords, noop)]
