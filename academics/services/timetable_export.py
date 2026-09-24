from datetime import datetime, timedelta
import re

from academics.models import TimetableEntry, TimeSlot, SchoolClass
from academics.services.timetable_configuration import (
    get_or_create_configuration,
    build_configured_schedule_preview,
    get_explicit_blocks,
)


def _safe_filename(value):
    value = re.sub(r'[^A-Za-z0-9._-]+', '_', str(value or '').strip())
    return value.strip('_') or 'timetable'


def build_timetable_export_context(timetable, class_id=None):
    """Build one shared, block-aware data structure for PDF and Word exports."""
    school = timetable.school
    days = ['MON', 'TUE', 'WED', 'THU', 'FRI']
    day_labels = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

    timeslots = list(
        TimeSlot.objects.filter(school=school, is_active=True)
        .order_by('period_index', 'day')
    )
    period_indexes = sorted(set(slot.period_index for slot in timeslots))

    selected_class = None
    if class_id:
        selected_class = SchoolClass.objects.filter(
            id=class_id,
            school=school,
        ).first()

    entries = TimetableEntry.objects.filter(
        timetable=timetable,
    ).select_related(
        'school_class', 'subject', 'teacher__user', 'room', 'timeslot'
    )
    if selected_class:
        entries = entries.filter(school_class=selected_class)

    slot_lookup = {
        (entry.timeslot.period_index, entry.timeslot.day): entry
        for entry in entries
    }
    slot_by_period_day = {
        (slot.period_index, slot.day): slot
        for slot in timeslots
    }

    config = get_or_create_configuration(school)
    explicit_blocks = get_explicit_blocks(config)
    try:
        expected_slots = build_configured_schedule_preview(config)
        actual = {
            (s.day, s.period_index, s.start_time, s.end_time)
            for s in timeslots
        }
        expected = {
            (r['day'], r['period_index'], r['start_time'], r['end_time'])
            for r in expected_slots
        }
        if actual != expected:
            explicit_blocks = []
    except Exception:
        explicit_blocks = []

    blocks_by_period = {}
    for block in explicit_blocks:
        blocks_by_period.setdefault(block.after_period, []).append(block)

    def block_for_day(after_period, day):
        matches = [
            b for b in blocks_by_period.get(after_period, [])
            if b.day in (None, '', day)
        ]
        return matches[0] if matches else None

    def block_cells(after_period):
        cells = []
        for day in days:
            block = block_for_day(after_period, day)
            if not block:
                cells.append(None)
                continue

            if after_period == 0:
                first_slot = slot_by_period_day.get(
                    (period_indexes[0], day)
                ) if period_indexes else None
                if not first_slot:
                    cells.append(None)
                    continue
                end = first_slot.start_time
                anchor = datetime.combine(datetime.today(), end) - timedelta(minutes=block.minutes)
                cells.append({
                    'block': block,
                    'start': anchor.time(),
                    'end': end,
                })
            else:
                current_slot = slot_by_period_day.get((after_period, day))
                next_slot = slot_by_period_day.get((after_period + 1, day))
                if current_slot and next_slot:
                    cells.append({
                        'block': block,
                        'start': current_slot.end_time,
                        'end': next_slot.start_time,
                    })
                elif current_slot:
                    anchor = datetime.combine(
                        datetime.today(), current_slot.end_time
                    ) + timedelta(minutes=block.minutes)
                    cells.append({
                        'block': block,
                        'start': current_slot.end_time,
                        'end': anchor.time(),
                    })
                else:
                    cells.append(None)
        return cells

    rows = []
    if 0 in blocks_by_period:
        rows.append({
            'type': 'block',
            'block_cells': block_cells(0),
        })

    for period in period_indexes:
        period_slots = [slot_by_period_day.get((period, d)) for d in days]
        first_slot = next((slot for slot in period_slots if slot), None)
        time_label = ''
        if first_slot:
            time_label = f'{first_slot.start_time.strftime("%H:%M")} – {first_slot.end_time.strftime("%H:%M")}'

        cells = []
        for day in days:
            entry = slot_lookup.get((period, day))
            if not entry:
                cells.append(None)
                continue
            teacher_name = ''
            if entry.teacher:
                teacher_name = entry.teacher.user.get_full_name() or entry.teacher.user.username
            cells.append({
                'subject': entry.subject.name,
                'class': entry.school_class.name,
                'teacher': teacher_name,
                'room': entry.room.name if entry.room else '',
                'is_lab': bool(entry.is_lab),
            })

        rows.append({
            'type': 'period',
            'period': period,
            'period_label': f'P{period}  {time_label}',
            'cells': cells,
        })

        if period in blocks_by_period:
            rows.append({
                'type': 'block',
                'block_cells': block_cells(period),
            })

    for row in rows:
        if row['type'] == 'block':
            populated = next((c for c in row['block_cells'] if c), None)
            if populated:
                block = populated['block']
                row['block'] = {
                    'label': block.label,
                    'type': block.get_block_type_display(),
                    'start': populated['start'].strftime('%H:%M'),
                    'end': populated['end'].strftime('%H:%M'),
                }
            else:
                row['block'] = {'label': '', 'type': '', 'start': '', 'end': ''}

    term_name = timetable.academic_term.name if timetable.academic_term else 'Academic Term'
    title = 'Timetable'
    if selected_class:
        title = f'{selected_class.name} Timetable'

    status_label = timetable.get_status_display() if hasattr(timetable, 'get_status_display') else str(timetable.status)
    filename_base = _safe_filename(f'{school.name}_{title}_{term_name}')

    return {
        'timetable': timetable,
        'school_name': school.name,
        'timetable_title': title,
        'term_name': term_name,
        'status_label': status_label,
        'fitness': f'{timetable.fitness_score:.3f}' if timetable.fitness_score is not None else '—',
        'hard_conflicts': timetable.hard_conflicts,
        'soft_conflicts': timetable.soft_conflicts,
        'generations': timetable.generations_run,
        'entries_count': len(entries),
        'days': days,
        'days_display': day_labels,
        'rows': rows,
        'selected_class': selected_class,
        'schedule_config': config,
        'export_filename_base': filename_base,
    }
