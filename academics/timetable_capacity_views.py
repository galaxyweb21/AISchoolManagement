from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from school.models import AcademicTerm
from staff.models import Teacher
from .models import ClassSubject, ClassSubjectRequirement, TeacherAssignment, TimeSlot, SchoolClass

_ALLOWED_ROLES = {"SUPER_ADMIN", "SCHOOL_ADMIN", "HOD"}


def _active_term(school):
    return AcademicTerm.objects.filter(
        academic_year__school=school,
        academic_year__is_active=True,
        is_active=True,
    ).first()


def _effective_teacher(school_class, assignments):
    if assignments:
        primary = next((a for a in assignments if a.is_primary), assignments[0])
        return primary.teacher, "Subject Teacher"
    teacher = getattr(school_class, "homeroom_teacher", None)
    if (
        school_class.uses_single_class_teacher
        and teacher
        and teacher.is_active
        and getattr(teacher.user, "is_active", False)
    ):
        return teacher, "Class Teacher fallback"
    return None, "Unassigned"


@login_required
@require_http_methods(["GET", "POST"])
def timetable_capacity_manager(request):
    """Controlled timetable allocation editor.

    This screen changes only ClassSubject/override periods and the explicit
    teacher for a specific class+subject. It never randomly reallocates staff,
    changes the scheduler, or deletes school data.
    """
    if request.user.role not in _ALLOWED_ROLES:
        messages.error(request, "You don't have permission to manage timetable allocations.")
        return redirect("academics:timetable_workspace")

    school = getattr(request.user, "school", None)
    if not school:
        messages.error(request, "No school is associated with this account.")
        return redirect("dashboard:dashboard")

    active_term = _active_term(school)
    slots_count = TimeSlot.objects.filter(school=school, is_active=True).count()
    classes = list(
        SchoolClass.objects.filter(school=school, is_active=True)
        .select_related("homeroom_teacher__user", "grade_level")
        .order_by("name")
    )
    class_subjects = list(
        ClassSubject.objects.filter(
            school=school,
            is_active=True,
            school_class__is_active=True,
            subject__is_active=True,
        ).select_related("school_class", "subject")
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
    assignment_by_key = defaultdict(list)
    for assignment in assignments:
        assignment_by_key[(assignment.school_class_id, assignment.subject_id)].append(assignment)

    teachers = list(
        Teacher.objects.filter(school=school, is_active=True, user__is_active=True)
        .select_related("user")
        .order_by("user__last_name", "user__first_name")
    )
    teacher_map = {str(t.id): t for t in teachers}
    overrides = {
        (r.school_class_id, r.subject_id): r
        for r in ClassSubjectRequirement.objects.filter(school=school)
    }

    if request.method == "POST":
        saved = 0
        errors = []
        with transaction.atomic():
            for cs in class_subjects:
                key = (cs.school_class_id, cs.subject_id)
                raw_periods = (request.POST.get(f"periods_{cs.id}") or "").strip()
                if raw_periods:
                    try:
                        periods = int(raw_periods)
                    except ValueError:
                        errors.append(f"{cs.school_class.name} — {cs.subject.name}: periods must be a whole number.")
                        continue
                    if periods < 1 or periods > max(1, slots_count):
                        errors.append(
                            f"{cs.school_class.name} — {cs.subject.name}: periods must be between 1 and {max(1, slots_count)}."
                        )
                        continue
                    override = overrides.get(key)
                    if override:
                        if override.periods_per_week != periods:
                            override.periods_per_week = periods
                            override.save(update_fields=["periods_per_week"])
                            saved += 1
                    elif cs.periods_per_week != periods:
                        cs.periods_per_week = periods
                        cs.save(update_fields=["periods_per_week", "updated_at"])
                        saved += 1
                    TeacherAssignment.objects.filter(
                        school=school,
                        school_class_id=cs.school_class_id,
                        subject_id=cs.subject_id,
                        is_active=True,
                    ).update(periods_per_week=periods)

                raw_teacher = (request.POST.get(f"teacher_{cs.id}") or "").strip()
                current = assignment_by_key.get(key, [])
                current_teacher = next((a.teacher for a in current if a.is_primary), current[0].teacher if current else None)
                if raw_teacher == "__KEEP__":
                    continue

                if raw_teacher in ("", "__CLASS_TEACHER__", "__NONE__"):
                    TeacherAssignment.objects.filter(
                        school=school,
                        school_class_id=cs.school_class_id,
                        subject_id=cs.subject_id,
                        is_active=True,
                    ).update(is_active=False, is_primary=False)
                    if current_teacher:
                        saved += 1
                    continue

                teacher = teacher_map.get(raw_teacher)
                if not teacher:
                    errors.append(f"{cs.school_class.name} — {cs.subject.name}: selected teacher is not active or does not belong to this school.")
                    continue

                periods = overrides.get(key).periods_per_week if key in overrides else cs.periods_per_week
                TeacherAssignment.objects.filter(
                    school=school,
                    school_class_id=cs.school_class_id,
                    subject_id=cs.subject_id,
                    is_active=True,
                ).update(is_active=False, is_primary=False)
                assignment, _ = TeacherAssignment.objects.get_or_create(
                    school=school,
                    teacher=teacher,
                    school_class=cs.school_class,
                    subject=cs.subject,
                    defaults={
                        "periods_per_week": periods,
                        "is_primary": True,
                        "is_active": True,
                        "assigned_by": request.user,
                    },
                )
                assignment.periods_per_week = periods
                assignment.is_primary = True
                assignment.is_active = True
                assignment.assigned_by = request.user
                assignment.save(update_fields=["periods_per_week", "is_primary", "is_active", "assigned_by", "updated_at"])
                teacher.subjects.add(cs.subject)
                saved += 1

        if errors:
            for error in errors:
                messages.error(request, error)
        if saved:
            messages.success(request, f"Saved {saved} timetable allocation change(s).")
        elif not errors:
            messages.info(request, "No allocation changes were made.")
        return redirect("academics:timetable_capacity_manager")

    by_class = defaultdict(list)
    class_totals = defaultdict(int)
    for cs in class_subjects:
        key = (cs.school_class_id, cs.subject_id)
        assignment_group = assignment_by_key.get(key, [])
        teacher, source = _effective_teacher(cs.school_class, assignment_group)
        override = overrides.get(key)
        periods = override.periods_per_week if override else cs.periods_per_week
        class_totals[cs.school_class_id] += periods
        by_class[cs.school_class_id].append({
            "obj": cs,
            "periods": periods,
            "teacher": teacher,
            "source": source,
            "overridden": bool(override),
        })

    class_cards = []
    for school_class in classes:
        total = class_totals.get(school_class.id, 0)
        class_cards.append({
            "obj": school_class,
            "items": by_class.get(school_class.id, []),
            "total": total,
            "available": slots_count,
            "difference": slots_count - total,
            "over_capacity": total > slots_count,
        })

    teacher_totals = defaultdict(int)
    teacher_items = defaultdict(list)
    for card in class_cards:
        for item in card["items"]:
            teacher = item["teacher"]
            if not teacher:
                continue
            teacher_totals[teacher.id] += item["periods"]
            teacher_items[teacher.id].append({
                "class_name": card["obj"].name,
                "subject_name": item["obj"].subject.name,
                "periods": item["periods"],
                "source": item["source"],
            })

    teacher_cards = []
    for teacher in teachers:
        total = teacher_totals.get(teacher.id, 0)
        teacher_cards.append({
            "obj": teacher,
            "total": total,
            "capacity": slots_count,
            "difference": slots_count - total,
            "over_capacity": total > slots_count,
            "reference": teacher.max_periods_per_week or 25,
            "items": sorted(teacher_items.get(teacher.id, []), key=lambda x: (x["class_name"].lower(), x["subject_name"].lower())),
        })
    teacher_cards.sort(key=lambda x: (-x["total"], x["obj"].user.last_name.lower(), x["obj"].user.first_name.lower()))

    context = {
        "active_term": active_term,
        "slots_count": slots_count,
        "class_cards": class_cards,
        "teacher_cards": teacher_cards,
        "class_count": len(classes),
        "over_capacity_classes": sum(1 for x in class_cards if x["over_capacity"]),
        "over_capacity_teachers": sum(1 for x in teacher_cards if x["over_capacity"]),
        "total_required": sum(x["total"] for x in class_cards),
    }
    return render(request, "academics/timetable_capacity_manager.html", context)
