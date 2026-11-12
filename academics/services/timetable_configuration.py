from collections import Counter, defaultdict
from datetime import datetime, timedelta

from django.db import transaction

from academics.models import TimeSlot, TimetableEntry
from academics.timetable_configuration_model import (
    TimetableConfiguration,
    default_schedule_blocks,
    default_schedule_days,
)
from academics.timetable_schedule_block_model import TimetableScheduleBlock


DAY_ORDER = ['MON', 'TUE', 'WED', 'THU', 'FRI']


def _duration_minutes(start, end):
    anchor = datetime(2000, 1, 1)
    return int((datetime.combine(anchor, end) - datetime.combine(anchor, start)).total_seconds() // 60)


def _json_blocks(config):
    return [b for b in (config.blocks or []) if isinstance(b, dict)]


def _sync_legacy_json_from_blocks(config):
    """Keep the old JSON field populated for backward compatibility."""
    rows = list(
        TimetableScheduleBlock.objects.filter(
            configuration=config, is_active=True
        ).order_by('after_period', 'sort_order', 'label')
    )
    config.blocks = [
        {
            'type': row.block_type,
            'label': row.label,
            'after_period': row.after_period,
            'minutes': row.minutes,
        }
        for row in rows
        if not row.day
    ]
    config.save(update_fields=['blocks', 'updated_at'])


def ensure_explicit_blocks(config):
    """Backfill block rows for older T4 configurations without duplicating them."""
    if TimetableScheduleBlock.objects.filter(configuration=config).exists():
        return
    for index, block in enumerate(_json_blocks(config)):
        try:
            block_type = str(block.get('type') or 'OTHER').upper()
            label = str(block.get('label') or 'Block').strip()[:60]
            after_period = int(block.get('after_period', 0))
            minutes = int(block.get('minutes', 30))
        except (TypeError, ValueError):
            continue
        if not label or after_period < 0 or minutes <= 0:
            continue
        TimetableScheduleBlock.objects.create(
            configuration=config,
            block_type=block_type if block_type in dict(TimetableScheduleBlock._meta.get_field('block_type').choices) else 'OTHER',
            label=label,
            after_period=after_period,
            minutes=minutes,
            sort_order=index,
        )


def _infer_existing_configuration(school, config):
    slots = list(TimeSlot.objects.filter(school=school, is_active=True).order_by('day', 'period_index'))
    if not slots:
        ensure_explicit_blocks(config)
        return config

    days = [d for d in DAY_ORDER if any(s.day == d for s in slots)]
    durations = [_duration_minutes(s.start_time, s.end_time) for s in slots if s.start_time and s.end_time]
    period_length = Counter(durations).most_common(1)[0][0] if durations else 50
    start_time = min(s.start_time for s in slots)
    periods_per_day = max(s.period_index for s in slots)

    gaps = defaultdict(list)
    for day in days:
        day_slots = sorted([s for s in slots if s.day == day], key=lambda s: s.period_index)
        for current, nxt in zip(day_slots, day_slots[1:]):
            gap = _duration_minutes(current.end_time, nxt.start_time)
            if gap > 0:
                gaps[current.period_index].append(gap)

    inferred_blocks = []
    for after_period in sorted(gaps):
        minutes = Counter(gaps[after_period]).most_common(1)[0][0]
        inferred_blocks.append({
            'type': 'BREAK' if not inferred_blocks else 'LUNCH',
            'label': 'Break' if not inferred_blocks else 'Lunch',
            'after_period': after_period,
            'minutes': minutes,
        })

    config.days = days or default_schedule_days()
    config.start_time = start_time
    config.period_length_minutes = period_length
    config.periods_per_day = periods_per_day
    config.blocks = inferred_blocks or default_schedule_blocks()
    config.template_name = 'Imported from existing TimeSlots'
    config.save()
    ensure_explicit_blocks(config)
    return config


def get_or_create_configuration(school):
    config, created = TimetableConfiguration.objects.get_or_create(school=school)
    if created:
        config = _infer_existing_configuration(school, config)
    else:
        ensure_explicit_blocks(config)
    return config


def normalize_blocks(blocks, periods_per_day):
    cleaned = []
    seen = set()
    for block in blocks or []:
        try:
            block_type = str(block.get('type') or '').upper()
            label = str(block.get('label') or '').strip()
            after_period = int(block.get('after_period', 0))
            minutes = int(block.get('minutes', 0))
        except (TypeError, ValueError):
            raise ValueError('Every schedule block must have a valid period and duration.')
        if not block_type or not label:
            continue
        if minutes <= 0:
            raise ValueError(f'{label}: duration must be greater than zero.')
        if after_period < 0 or after_period >= periods_per_day:
            raise ValueError(f'{label}: place it before period 1 or after a period before the final period.')
        if after_period in seen:
            raise ValueError(f'Only one non-teaching block can be placed after period {after_period}.')
        seen.add(after_period)
        cleaned.append({'type': block_type, 'label': label, 'after_period': after_period, 'minutes': minutes})
    return sorted(cleaned, key=lambda item: item['after_period'])


def get_explicit_blocks(config, day=None, include_inactive=False):
    ensure_explicit_blocks(config)
    qs = TimetableScheduleBlock.objects.filter(configuration=config)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    rows = list(qs.order_by('after_period', 'sort_order', 'label'))
    if day is None:
        return rows
    return [row for row in rows if row.day in (None, '', day)]


def _block_dict(row):
    return {
        'type': row.block_type,
        'label': row.label,
        'after_period': row.after_period,
        'minutes': row.minutes,
        'day': row.day,
    }


def build_configured_schedule_preview(config):
    """Return only instructional TimeSlot rows; explicit blocks occupy the gaps."""
    blocks = get_explicit_blocks(config)
    rows = []
    anchor = datetime(2000, 1, 1)

    for day in config.days:
        day_blocks = {b.after_period: b for b in blocks if b.day in (None, '', day)}
        cursor = datetime.combine(anchor, config.start_time)
        if 0 in day_blocks:
            cursor += timedelta(minutes=day_blocks[0].minutes)
        for period in range(1, config.periods_per_day + 1):
            start = cursor
            end = cursor + timedelta(minutes=config.period_length_minutes)
            rows.append({'day': day, 'period_index': period, 'start_time': start.time(), 'end_time': end.time()})
            cursor = end
            block = day_blocks.get(period)
            if block:
                cursor += timedelta(minutes=block.minutes)
    return rows


def build_schedule_preview_with_blocks(config):
    """Return teaching periods and explicit non-teaching blocks for the UI."""
    blocks = get_explicit_blocks(config)
    rows = []
    anchor = datetime(2000, 1, 1)
    for day in config.days:
        day_blocks = {b.after_period: b for b in blocks if b.day in (None, '', day)}
        cursor = datetime.combine(anchor, config.start_time)
        if 0 in day_blocks:
            block = day_blocks[0]
            end = cursor + timedelta(minutes=block.minutes)
            rows.append({'day': day, 'type': 'block', 'period_index': 0, 'start_time': cursor.time(), 'end_time': end.time(), 'block': _block_dict(block)})
            cursor = end
        for period in range(1, config.periods_per_day + 1):
            start = cursor
            end = cursor + timedelta(minutes=config.period_length_minutes)
            rows.append({'day': day, 'type': 'period', 'period_index': period, 'start_time': start.time(), 'end_time': end.time()})
            cursor = end
            if period in day_blocks:
                block = day_blocks[period]
                end_block = cursor + timedelta(minutes=block.minutes)
                rows.append({'day': day, 'type': 'block', 'period_index': period, 'start_time': cursor.time(), 'end_time': end_block.time(), 'block': _block_dict(block)})
                cursor = end_block
    return rows


def get_timeslot_configuration_status(school, config):
    """Compare the saved configuration with the school's current teaching TimeSlots.

    This is intentionally read-only. It does not create, update, or delete any
    TimeSlots and is used to make the configuration/apply safety boundary
    visible to school administrators.
    """
    expected_rows = build_configured_schedule_preview(config)
    expected = {
        (row['day'], row['period_index'], row['start_time'], row['end_time'])
        for row in expected_rows
    }

    actual_slots = list(
        TimeSlot.objects.filter(school=school, is_active=True)
        .order_by('day', 'period_index')
    )
    actual = {
        (slot.day, slot.period_index, slot.start_time, slot.end_time)
        for slot in actual_slots
    }

    missing = expected - actual
    extra = actual - expected

    expected_by_key = {
        (row['day'], row['period_index']): (row['start_time'], row['end_time'])
        for row in expected_rows
    }
    actual_by_key = {
        (slot.day, slot.period_index): (slot.start_time, slot.end_time)
        for slot in actual_slots
    }

    timing_mismatches = []
    for key in sorted(set(expected_by_key) & set(actual_by_key)):
        if expected_by_key[key] != actual_by_key[key]:
            timing_mismatches.append({
                'day': key[0],
                'period': key[1],
                'expected_start': expected_by_key[key][0],
                'expected_end': expected_by_key[key][1],
                'actual_start': actual_by_key[key][0],
                'actual_end': actual_by_key[key][1],
            })

    matches = not missing and not extra and not timing_mismatches

    if matches:
        title = 'Configuration matches current teaching periods'
        message = (
            'The saved schedule structure and active TimeSlots use the same days, '
            'period numbers and teaching times.'
        )
        level = 'success'
    else:
        title = 'Configuration differs from current teaching periods'
        parts = []
        if missing:
            parts.append(f'{len(missing)} configured teaching period(s) are missing')
        if extra:
            parts.append(f'{len(extra)} existing TimeSlot(s) are outside the configuration')
        if timing_mismatches:
            parts.append(f'{len(timing_mismatches)} teaching period time(s) differ')
        message = '; '.join(parts) + '.'
        level = 'warning'

    return {
        'matches': matches,
        'title': title,
        'message': message,
        'level': level,
        'expected_count': len(expected),
        'actual_count': len(actual),
        'missing_count': len(missing),
        'extra_count': len(extra),
        'timing_mismatch_count': len(timing_mismatches),
        'timing_mismatches': timing_mismatches[:10],
    }


@transaction.atomic
def save_explicit_blocks(config, block_forms):
    """Replace only the block definitions for a configuration, not TimeSlots."""
    TimetableScheduleBlock.objects.filter(configuration=config).delete()
    created = []
    for index, form in enumerate(block_forms):
        if form.cleaned_data.get('DELETE') or not form.cleaned_data.get('is_active'):
            continue
        obj = form.save(commit=False)
        obj.configuration = config
        obj.day = obj.day or None
        obj.sort_order = index
        obj.save()
        created.append(obj)
    _sync_legacy_json_from_blocks(config)
    return created


@transaction.atomic
def apply_timetable_configuration(school, config, replace_existing=False):
    existing_entries = TimetableEntry.objects.filter(timetable__school=school).exists()
    if replace_existing and existing_entries:
        raise ValueError('The school already has timetable entries. Delete/archive the existing timetable runs before replacing the period grid, so historical timetables are not broken.')

    rows = build_configured_schedule_preview(config)
    days = list(config.days)
    if replace_existing:
        TimeSlot.objects.filter(school=school, day__in=days).delete()

    created = 0
    skipped = 0
    for row in rows:
        _, was_created = TimeSlot.objects.get_or_create(
            school=school,
            day=row['day'],
            period_index=row['period_index'],
            defaults={'start_time': row['start_time'], 'end_time': row['end_time'], 'is_active': True},
        )
        if was_created:
            created += 1
        else:
            skipped += 1
    return created, skipped
