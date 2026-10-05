from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from .models import Subject, SchoolClass, ClassSubject


MANAGER_ROLES = {"SUPER_ADMIN", "SCHOOL_ADMIN"}


def get_curriculum_stage(school_class):
    grade = getattr(school_class, "grade_level", None)
    stage = getattr(grade, "stage", None) or "OTHER"
    if stage != "OTHER":
        return stage

    raw = (getattr(grade, "name", "") or school_class.name or "").strip().upper()
    if raw.startswith(("KG", "KINDERGARTEN", "NURSERY")):
        return "KG"
    if raw.startswith(("JHS", "BASIC 7", "BASIC 8", "BASIC 9", "BASIC 10", "BASIC 11", "BASIC 12")):
        return "JHS"
    if raw.startswith(("SHS", "SENIOR HIGH")):
        return "SHS"
    if any(raw.startswith(f"BASIC {n}") or raw.startswith(f"CLASS {n}") for n in range(1, 7)):
        return "PRIMARY"
    return "OTHER"


def subjects_for_class(school, school_class):
    stage = get_curriculum_stage(school_class)
    levels = ["ALL"] if stage == "OTHER" else ["ALL", stage]
    return Subject.objects.filter(
        school=school, is_active=True, curriculum_level__in=levels
    ).order_by("name")


def ensure_class_subjects(school, school_class, subject_ids=None):
    """Create missing ClassSubject rows for curriculum-eligible subjects."""
    eligible = subjects_for_class(school, school_class)
    if subject_ids:
        eligible = eligible.filter(id__in=subject_ids)

    created = 0
    skipped = 0
    for subject in eligible:
        obj, was_created = ClassSubject.objects.get_or_create(
            school=school, school_class=school_class, subject=subject,
            defaults={"periods_per_week": 4, "is_core": False, "is_active": True},
        )
        if was_created:
            created += 1
        else:
            if not obj.is_active:
                obj.is_active = True
                obj.save(update_fields=["is_active", "updated_at"])
            skipped += 1
    return created, skipped


def _subjects_for_class(school, school_class):
    return subjects_for_class(school, school_class)


def sync_subjects_to_classes(school=None):
    """Synchronize all active curriculum subjects to eligible active classes."""
    if school is None:
        return 0, 0
    created = skipped = 0
    for school_class in SchoolClass.objects.filter(school=school, is_active=True).select_related("grade_level"):
        c, s = ensure_class_subjects(school, school_class)
        created += c
        skipped += s
    return created, skipped


@login_required
@require_http_methods(["GET"])
def curriculum_subject_options(request):
    if request.user.role not in MANAGER_ROLES:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)
    school = getattr(request.user, "school", None)
    if not school:
        return JsonResponse({"success": False, "error": "No school is associated with this account."}, status=400)

    classes = list(SchoolClass.objects.filter(school=school, is_active=True).select_related("grade_level").order_by("grade_level__order", "name"))
    subjects = list(Subject.objects.filter(school=school, is_active=True).order_by("name"))
    existing_pairs = set(ClassSubject.objects.filter(
        school=school, is_active=True, school_class__is_active=True
    ).values_list("school_class_id", "subject_id"))

    return JsonResponse({
        "success": True,
        "subjects": [{
            "id": str(s.id), "name": s.name, "code": s.code,
            "curriculum_level": s.curriculum_level,
            "curriculum_label": s.get_curriculum_level_display(),
        } for s in subjects],
        "classes": [{
            "id": str(c.id), "name": c.name,
            "grade_level": getattr(c.grade_level, "name", "") if c.grade_level else "",
            "stage": get_curriculum_stage(c),
        } for c in classes],
        "existing_pairs": [{"class_id": str(cid), "subject_id": str(sid)} for cid, sid in existing_pairs],
    })


@login_required
@require_http_methods(["POST"])
def apply_curriculum_subjects(request):
    if request.user.role not in MANAGER_ROLES:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)
    school = getattr(request.user, "school", None)
    if not school:
        return JsonResponse({"success": False, "error": "No school is associated with this account."}, status=400)

    class_ids = request.POST.getlist("class_ids[]") or request.POST.getlist("class_ids")
    subject_ids = request.POST.getlist("subject_ids[]") or request.POST.getlist("subject_ids")
    periods_raw = (request.POST.get("periods_per_week") or "4").strip()
    is_core = request.POST.get("is_core") in {"1", "true", "on", "yes"}

    if not class_ids:
        return JsonResponse({"success": False, "error": "Select at least one class."}, status=400)

    try:
        periods = int(periods_raw)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Periods per week must be a whole number."}, status=400)
    if not 1 <= periods <= 20:
        return JsonResponse({"success": False, "error": "Periods per week must be between 1 and 20."}, status=400)

    classes = list(SchoolClass.objects.filter(school=school, is_active=True, id__in=class_ids).select_related("grade_level"))
    if len(classes) != len(set(class_ids)):
        return JsonResponse({"success": False, "error": "One or more selected classes are invalid."}, status=400)

    created = skipped = 0
    invalid = []
    with transaction.atomic():
        for school_class in classes:
            # If subjects were explicitly selected, apply only those; otherwise
            # automatically apply every curriculum-eligible school subject.
            eligible = subjects_for_class(school, school_class)
            if subject_ids:
                eligible = eligible.filter(id__in=subject_ids)
            for subject in eligible:
                obj, was_created = ClassSubject.objects.get_or_create(
                    school=school, school_class=school_class, subject=subject,
                    defaults={"periods_per_week": periods, "is_core": is_core, "is_active": True},
                )
                if was_created:
                    created += 1
                else:
                    if not obj.is_active:
                        obj.is_active = True
                        obj.save(update_fields=["is_active", "updated_at"])
                    skipped += 1

    message = f"{created} class-subject assignment(s) added. {skipped} existing assignment(s) left unchanged."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"success": True, "created": created, "skipped": skipped, "message": message})
    messages.success(request, message)
    return redirect("academics:subject_list")
