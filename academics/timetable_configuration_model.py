from datetime import time
import uuid

from django.db import models

from school.models import School
from school.services import managers


DAY_CHOICES = [
    ('MON', 'Monday'),
    ('TUE', 'Tuesday'),
    ('WED', 'Wednesday'),
    ('THU', 'Thursday'),
    ('FRI', 'Friday'),
]

BLOCK_TYPES = [
    ('ASSEMBLY', 'Assembly / Devotion'),
    ('BREAK', 'Break'),
    ('LUNCH', 'Lunch'),
    ('ACTIVITY', 'Activity'),
    ('CLUB', 'Club / Enrichment'),
    ('OTHER', 'Other'),
]


def default_schedule_days():
    return ['MON', 'TUE', 'WED', 'THU', 'FRI']


def default_schedule_blocks():
    return [
        {'type': 'BREAK', 'label': 'Break', 'after_period': 2, 'minutes': 30},
        {'type': 'LUNCH', 'label': 'Lunch', 'after_period': 5, 'minutes': 30},
    ]


class TimetableConfiguration(models.Model):
    """Persistent school-level timetable structure and non-teaching blocks.

    TimeSlot remains the actual scheduler input. This model is the friendly
    configuration layer used to generate/update that period grid safely.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.OneToOneField(
        School,
        on_delete=models.CASCADE,
        related_name='timetable_configuration',
    )
    template_name = models.CharField(
        max_length=120,
        default='GES-based starting template',
        help_text='Friendly name for this school timetable structure.',
    )
    start_time = models.TimeField(default=time(8, 0))
    period_length_minutes = models.PositiveSmallIntegerField(default=50)
    periods_per_day = models.PositiveSmallIntegerField(default=8)
    days = models.JSONField(default=default_schedule_days)
    blocks = models.JSONField(default=default_schedule_blocks)
    allow_double_periods = models.BooleanField(
        default=False,
        help_text='Allow the AI timetabler to place the same subject in consecutive periods when useful.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.TenantManager()

    class Meta:
        ordering = ['school__name']

    def __str__(self):
        return f'{self.school.name} - {self.template_name}'
