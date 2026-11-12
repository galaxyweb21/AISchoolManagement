# academics/services/ges_schedule.py
"""
Ghana Education Service (GES) proposed periods allocation and length of
school day, for Public Basic Schools (KG/Primary/JHS under the Standards-
Based / Common Core Curriculum):

    - 8 periods per day, 50 minutes each  -> 40 periods/week, 6h40 of
      actual instruction per day
    - 1 hour of daily break, split into two 30-minute breaks (typically
      a mid-morning break and a lunch break)

This module turns that into real academics.TimeSlot rows for a school.
It does NOT hard-code the numbers as immutable truth -- every value has
a default matching GES's proposal but can be overridden per school,
since schools have some flexibility in how they implement it and this
system supports schools outside Ghana too.

Breaks are folded into the day's timing (they push later periods'
start/end times back) but are NOT stored as their own TimeSlot rows --
academics.services.timetable_service only ever schedules lessons
against TimeSlot.period_index, so periods stay a clean 1..N sequence
per day and the timetabler needs no changes to consume this.
"""
from datetime import datetime, timedelta, time as time_cls

from django.db import transaction

from ..models import TimeSlot

# ============================================================
# GES DEFAULTS
# ============================================================

ALL_WEEKDAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI']

GES_STANDARD_DEFAULTS = {
    'start_time': time_cls(8, 0),
    'period_length_minutes': 50,
    'periods_per_day': 8,
    # {period_index_after_which_break_occurs: break_length_minutes}
    'breaks': {2: 30, 5: 30},
    'days': ALL_WEEKDAYS,
}

GES_TEMPLATE_LABEL = "GES Standard (8 x 50-minute periods)"


class GESScheduleError(Exception):
    """Raised when the requested schedule parameters can't produce a valid timetable."""
    pass


# ============================================================
# PURE CALCULATION (no DB writes) -- also used to render a preview
# in the UI before the school commits to generating real TimeSlots.
# ============================================================

def build_ges_schedule_preview(
    start_time=None,
    period_length_minutes=None,
    periods_per_day=None,
    breaks=None,
    days=None,
):
    """
    Returns a list of dicts, one per (day, period):
        {'day': 'MON', 'period_index': 1, 'start_time': time(8,0), 'end_time': time(8,50)}

    Raises GESScheduleError for nonsensical input rather than silently
    producing a broken schedule.
    """
    start_time = start_time or GES_STANDARD_DEFAULTS['start_time']
    period_length_minutes = period_length_minutes or GES_STANDARD_DEFAULTS['period_length_minutes']
    periods_per_day = periods_per_day or GES_STANDARD_DEFAULTS['periods_per_day']
    breaks = GES_STANDARD_DEFAULTS['breaks'] if breaks is None else breaks
    days = days or GES_STANDARD_DEFAULTS['days']

    if period_length_minutes <= 0:
        raise GESScheduleError("Period length must be greater than 0 minutes.")
    if periods_per_day <= 0:
        raise GESScheduleError("There must be at least 1 period per day.")
    if not days:
        raise GESScheduleError("Select at least one school day.")
    for after_period, minutes in breaks.items():
        if after_period < 1 or after_period >= periods_per_day:
            raise GESScheduleError(
                f"A break can't be placed after period {after_period} "
                f"when the day only has {periods_per_day} periods."
            )
        if minutes <= 0:
            raise GESScheduleError("Break length must be greater than 0 minutes.")

    rows = []
    anchor_date = datetime(2000, 1, 1)  # arbitrary date, only used to do time arithmetic
    for day in days:
        cursor = datetime.combine(anchor_date, start_time)
        for period_index in range(1, periods_per_day + 1):
            period_start = cursor
            period_end = cursor + timedelta(minutes=period_length_minutes)
            rows.append({
                'day': day,
                'period_index': period_index,
                'start_time': period_start.time(),
                'end_time': period_end.time(),
            })
            cursor = period_end
            if period_index in breaks:
                cursor += timedelta(minutes=breaks[period_index])

    return rows


def summarize_school_day(
    period_length_minutes=None,
    periods_per_day=None,
    breaks=None,
):
    """Human-readable totals for display in the UI (instruction time, break time, day length)."""
    period_length_minutes = period_length_minutes or GES_STANDARD_DEFAULTS['period_length_minutes']
    periods_per_day = periods_per_day or GES_STANDARD_DEFAULTS['periods_per_day']
    breaks = GES_STANDARD_DEFAULTS['breaks'] if breaks is None else breaks

    instruction_minutes = period_length_minutes * periods_per_day
    break_minutes = sum(breaks.values())
    return {
        'instruction_minutes': instruction_minutes,
        'break_minutes': break_minutes,
        'total_minutes': instruction_minutes + break_minutes,
        'periods_per_week': periods_per_day * 5,
    }


# ============================================================
# DB SEEDING
# ============================================================

@transaction.atomic
def generate_ges_standard_timeslots(school, replace_existing=False, **overrides):
    """
    Seed TimeSlot rows for `school` from the GES standard (or an
    overridden) period structure.

    Non-destructive by default: an existing TimeSlot for a given
    (day, period_index) is left untouched rather than overwritten, so
    running this again after a school has hand-edited a few slots
    won't clobber their edits. Pass replace_existing=True to instead
    delete and fully regenerate every slot for the requested days.

    Returns (created_count, skipped_count).
    """
    rows = build_ges_schedule_preview(**overrides)

    if replace_existing:
        days_touched = {row['day'] for row in rows}
        TimeSlot.objects.filter(school=school, day__in=days_touched).delete()

    created = 0
    skipped = 0
    for row in rows:
        _, was_created = TimeSlot.objects.get_or_create(
            school=school,
            day=row['day'],
            period_index=row['period_index'],
            defaults={
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'is_active': True,
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    return created, skipped
