import uuid

from django.db import models

from school.services import managers
from .timetable_configuration_model import TimetableConfiguration, DAY_CHOICES, BLOCK_TYPES


class TimetableScheduleBlock(models.Model):
    """An explicit non-teaching block in a school's timetable structure.

    day is NULL for a block that applies to every configured school day.
    A specific day can be selected when a school has a different assembly,
    activity or other block on only one day.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    configuration = models.ForeignKey(
        TimetableConfiguration,
        on_delete=models.CASCADE,
        related_name='schedule_blocks',
    )
    day = models.CharField(
        max_length=3,
        choices=DAY_CHOICES,
        null=True,
        blank=True,
        help_text='Leave blank to apply this block to every configured school day.',
    )
    block_type = models.CharField(max_length=20, choices=BLOCK_TYPES)
    label = models.CharField(max_length=60)
    after_period = models.PositiveSmallIntegerField(
        default=2,
        help_text='0 = before Period 1; otherwise the block starts after this teaching period.',
    )
    minutes = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = managers.related_tenant_manager("configuration__school")()

    class Meta:
        ordering = ['day', 'after_period', 'sort_order', 'label']
        indexes = [
            models.Index(fields=['configuration', 'day', 'after_period']),
        ]

    def __str__(self):
        scope = self.get_day_display() if self.day else 'All days'
        return f'{self.label} - {scope} - after P{self.after_period}'
