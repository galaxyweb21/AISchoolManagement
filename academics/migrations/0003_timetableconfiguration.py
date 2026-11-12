from django.db import migrations, models
import django.db.models.deletion
import uuid
from datetime import time


def default_schedule_days():
    return ['MON', 'TUE', 'WED', 'THU', 'FRI']


def default_schedule_blocks():
    return [
        {'type': 'BREAK', 'label': 'Break', 'after_period': 2, 'minutes': 30},
        {'type': 'LUNCH', 'label': 'Lunch', 'after_period': 5, 'minutes': 30},
    ]


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0002_initial'),
        ('school', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TimetableConfiguration',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('template_name', models.CharField(default='GES-based starting template', help_text='Friendly name for this school timetable structure.', max_length=120)),
                ('start_time', models.TimeField(default=time(8, 0))),
                ('period_length_minutes', models.PositiveSmallIntegerField(default=50)),
                ('periods_per_day', models.PositiveSmallIntegerField(default=8)),
                ('days', models.JSONField(default=default_schedule_days)),
                ('blocks', models.JSONField(default=default_schedule_blocks)),
                ('allow_double_periods', models.BooleanField(default=False, help_text='Allow the AI timetabler to place the same subject in consecutive periods when useful.')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('school', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='timetable_configuration', to='school.school')),
            ],
            options={'ordering': ['school__name']},
        ),
    ]
