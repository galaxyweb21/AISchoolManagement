from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from school.models import AcademicTerm
from staff.views import _get_active_teachers_for_school
from .models import (
    ClassSubject,
    ClassSubjectRequirement,
    TeacherAssignment,
    TimeSlot,
    SchoolClass,
)


_ALLOWED_ROLES = {"SUPER_ADMIN", "SCHOOL_ADMIN", "HOD"}


def _active_term(school):
    return AcademicTerm.objects.filter(
        academic_year__school=school,
        academic_year__is_active=True,
        is_active=True,
    ).first()


def _effective_teacher(group, school_class):
    """Return explicit teacher first, otherwise the configured class teacher."""
    if group:
        return next((a for a in group if a.is_primary), group[0]), "subject"
    if (
        school_class.uses_single_class_teacher
        and school_class.homeroom_teacher_id
        and getattr(school_class.homeroom_teacher, "is_active", False)
        and getattr(school_class.homeroom_teacher.user, "is_active", False)
    ):
        return school_class.homeroom_teacher, "class"
    return None, "missing"


@login_required
@require_http_methods(["GET", "POST"])
def timetable_setup_assistant(request):
    """Configure class-teacher/subject-teacher mode and weekly allocations."""
    if request.user.role not in _ALLOWED_ROLES:
        messages.error(request, "You don't have permission to manage timetable setup.")
        return redirect("academics:timetable_workspace")

    school = getattr(request.user, "school", None)
    if not school:
        messages.error(request, "No school is associated with this account.")
        return redirect("dashboard:dashboard")

    active_term = _active_term(school)
    classes = list(
        SchoolClass.objects.filter(school=school, is_active=True)
        .select_related("homeroom_teacher__user", "grade_level")
        .order_by("name")
    )
    slots_count = TimeSlot.objects.filter(school=school, is_active=True).count()
    teachers = list(_get_active_teachers_for_school(school))

    class_subjects = list(
        ClassSubject.objects.filter(
            school=school,
            is_active=True,
            school_class__is_active=True,
            subject__is_active=True,
        )
        .select_related("school_class", "subject")
        .order_by("school_class__name", "subject__name")
    )

    assignments = list(
        TeacherAssignment.objects.filter(
            school=school,
            is_active=True,
            school_class__is_active=True,
            subject__is_active=True,
            teacher__is_active=True,
            teacher__user__is_active=True,
        ).select_related("teacher__user", "school_class", "subject")
    )
    assignments_by_key = defaultdict(list)
    for assignment in assignments:
        assignments_by_key[(assignment.school_class_id, assignment.subject_id)].append(assignment)

    overrides = {
        (r.school_class_id, r.subject_id): r.periods_per_week
        for r in ClassSubjectRequirement.objects.filter(school=school)
    }

    if request.method == "POST":
        saved_periods = 0
        saved_teachers = 0
        rejected = []
        with transaction.atomic():
            for school_class in classes:
                mode = request.POST.get(f"mode_{school_class.id}", "mixed")
                if mode not in {"subject", "mixed", "class"}:
                    mode = "mixed"

                # Mode is an explicit school choice. Never silently reset it.
                school_class.uses_single_class_teacher = mode in {"mixed", "class"}
                school_class.save(update_fields=["uses_single_class_teacher", "updated_at"])

                for cs in [x for x in class_subjects if x.school_class_id == school_class.id]:
                    effective_periods = overrides.get(
                        (cs.school_class_id, cs.subject_id),
                        cs.periods_per_week,
                    )
                    raw_periods = (request.POST.get(f"periods_{cs.id}") or "").strip()
                    if raw_periods:
                        try:
                            periods = int(raw_periods)
                        except (TypeError, ValueError):
                            rejected.append(
                                f"{school_class.name} — {cs.subject.name}: enter a whole number."
                            )
                            periods = None
                        if periods is not None:
                            if periods < 1 or periods > max(1, slots_count):
                                rejected.append(
                                    f"{school_class.name} — {cs.subject.name}: periods must be between 1 and {max(1, slots_count)}."
                                )
                            else:
                                requirement = ClassSubjectRequirement.objects.filter(
                                    school=school,
                                    school_class=school_class,
                                    subject=cs.subject,
                                ).first()
                                if requirement:
                                    requirement.periods_per_week = periods
                                    requirement.save(update_fields=["periods_per_week"])
                                else:
                                    cs.periods_per_week = periods
                                    cs.save(update_fields=["periods_per_week"])
                                effective_periods = periods
                                TeacherAssignment.objects.filter(
                                    school=school,
                                    school_class_id=cs.school_class_id,
                                    subject_id=cs.subject_id,
                                    is_active=True,
                                ).update(periods_per_week=periods)
                                saved_periods += 1

                    raw_teacher = request.POST.get(f"teacher_{cs.id}")
                    if raw_teacher is None:
                        continue

                    if raw_teacher == "__CLASS_TEACHER__":
                        TeacherAssignment.objects.filter(
                            school=school,
                            school_class_id=cs.school_class_id,
                            subject_id=cs.subject_id,
                            is_active=True,
                        ).update(is_active=False, is_primary=False)
                        saved_teachers += 1
                        continue

                    if raw_teacher == "__NONE__":
                        TeacherAssignment.objects.filter(
                            school=school,
                            school_class_id=cs.school_class_id,
                            subject_id=cs.subject_id,
                            is_active=True,
                        ).update(is_active=False, is_primary=False)
                        saved_teachers += 1
                        continue

                    selected = next((t for t in teachers if str(t.id) == str(raw_teacher)), None)
                    if not selected:
                        rejected.append(
                            f"{school_class.name} — {cs.subject.name}: selected teacher is not an active teacher in this school."
                        )
                        continue

                    TeacherAssignment.objects.filter(
                        school=school,
                        school_class_id=cs.school_class_id,
                        subject_id=cs.subject_id,
                        is_active=True,
                    ).update(is_active=False, is_primary=False)
                    assignment, _ = TeacherAssignment.objects.get_or_create(
                        school=school,
                        teacher=selected,
                        school_class=school_class,
                        subject=cs.subject,
                        defaults={
                            "periods_per_week": effective_periods,
                            "is_primary": True,
                            "is_active": True,
                            "assigned_by": request.user,
                        },
                    )
                    assignment.periods_per_week = effective_periods
                    assignment.is_primary = True
                    assignment.is_active = True
                    assignment.assigned_by = request.user
                    assignment.save()
                    selected.subjects.add(cs.subject)
                    saved_teachers += 1

        for message in rejected:
            messages.error(request, message)
        if saved_periods:
            messages.success(request, f"Saved weekly periods for {saved_periods} class-subject allocation(s).")
        if saved_teachers:
            messages.success(request, f"Saved teacher setup for {saved_teachers} class-subject allocation(s).")
        if not saved_periods and not saved_teachers and not rejected:
            messages.info(request, "No timetable setup changes were made.")
        return redirect("academics:timetable_setup_assistant")

    by_class = defaultdict(list)
    for cs in class_subjects:
        group = assignments_by_key.get((cs.school_class_id, cs.subject_id), [])
        teacher_obj, teacher_source = _effective_teacher(group, cs.school_class)
        effective = overrides.get((cs.school_class_id, cs.subject_id), cs.periods_per_week)
        primary_assignment = next((a for a in group if a.is_primary), group[0] if group else None)
        by_class[cs.school_class_id].append({
            "obj": cs,
            "periods": effective,
            "teacher": teacher_obj,
            "assignment": primary_assignment,
            "teacher_source": teacher_source,
            "overridden": (cs.school_class_id, cs.subject_id) in overrides,
        })

    # Capacity is calculated from the same effective periods used by readiness:
    # an explicit ClassSubjectRequirement overrides ClassSubject.periods_per_week.
    teacher_loads = defaultdict(int)
    teacher_subjects = defaultdict(int)
    for card_items in by_class.values():
        for item in card_items:
            if item["teacher"] is not None:
                teacher_id = getattr(item["teacher"], "id", None)
                if teacher_id:
                    teacher_loads[teacher_id] += item["periods"]
                    teacher_subjects[teacher_id] += 1

    class_cards = []
    for school_class in classes:
        items = by_class.get(school_class.id, [])
        total = sum(item["periods"] for item in items)
        missing = sum(1 for item in items if item["teacher_source"] == "missing")
        mode = "mixed" if school_class.uses_single_class_teacher else "subject"
        difference = slots_count - total
        class_cards.append({
            "obj": school_class,
            "items": items,
            "total": total,
            "missing": missing,
            "over_capacity": bool(slots_count and total > slots_count),
            "capacity_difference": difference,
            "capacity_overage": max(total - slots_count, 0),
            "mode": mode,
            "class_teacher": school_class.homeroom_teacher,
            "single_teacher_mode": bool(school_class.uses_single_class_teacher),
        })

    teacher_cards = []
    for teacher in teachers:
        load = teacher_loads.get(teacher.id, 0)
        hard_capacity = slots_count or 0
        reference = getattr(teacher, "max_periods_per_week", 25) or 25
        teacher_cards.append({
            "obj": teacher,
            "load": load,
            "hard_capacity": hard_capacity,
            "reference": reference,
            "difference": hard_capacity - load,
            "reference_difference": reference - load,
            "subjects": teacher_subjects.get(teacher.id, 0),
            "hard_over": bool(hard_capacity and load > hard_capacity),
            "reference_over": load > reference,
            "hard_overage": max(load - hard_capacity, 0),
        })
    teacher_cards.sort(key=lambda x: (-x["load"], x["obj"].user.last_name or "", x["obj"].user.first_name or ""))

    total_required_periods = sum(card["total"] for card in class_cards)
    assigned_teacher_periods = sum(card["load"] for card in teacher_cards)
    class_capacity_issues = sum(1 for card in class_cards if card["over_capacity"])
    teacher_capacity_issues = sum(1 for card in teacher_cards if card["hard_over"])

    context = {
        "active_term": active_term,
        "slots_count": slots_count,
        "teachers": teachers,
        "class_cards": class_cards,
        "class_subject_count": len(class_subjects),
        "missing_teacher_count": sum(card["missing"] for card in class_cards),
        "over_capacity_count": sum(1 for card in class_cards if card["over_capacity"]),
        "class_capacity_issues": class_capacity_issues,
        "teacher_capacity_issues": teacher_capacity_issues,
        "teacher_cards": teacher_cards,
        "total_required_periods": total_required_periods,
        "assigned_teacher_periods": assigned_teacher_periods,
        "total_teacher_capacity": len(teachers) * slots_count,
    }
    return render(request, "academics/timetable_setup_assistant.html", context)

@login_required
def timetable_setup(request):
    """Single user-facing timetable setup hub.

    The existing setup, allocation and schedule editors remain available as
    implementation routes. This page gives administrators one simple entry
    point and explains which editor is appropriate for each task.
    """
    if request.user.role not in _ALLOWED_ROLES:
        messages.error(request, "You don't have permission to manage timetable setup.")
        return redirect("academics:timetable_workspace")

    school = getattr(request.user, "school", None)
    if not school:
        messages.error(request, "No school is associated with this account.")
        return redirect("dashboard:dashboard")

    active_term = _active_term(school)
    slots_count = TimeSlot.objects.filter(school=school, is_active=True).count()
    classes_count = SchoolClass.objects.filter(school=school, is_active=True).count()
    class_subjects_count = ClassSubject.objects.filter(
        school=school,
        is_active=True,
        school_class__is_active=True,
        subject__is_active=True,
    ).count()
    teachers_count = len(_get_active_teachers_for_school(school))

    from .services.timetable_configuration import get_or_create_configuration
    from .services.timetable_readiness import TimetableReadiness

    config = get_or_create_configuration(school)
    readiness = TimetableReadiness(school, active_term).run()

    return render(request, "academics/timetable_setup.html", {
        "active_term": active_term,
        "slots_count": slots_count,
        "classes_count": classes_count,
        "class_subjects_count": class_subjects_count,
        "teachers_count": teachers_count,
        "config": config,
        "readiness": readiness,
        "can_manage": request.user.role in _ALLOWED_ROLES,
    })
