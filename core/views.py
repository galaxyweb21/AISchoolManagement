from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from core.pagination import paginate_queryset

from .models import ActivityLog


AUDIT_ROLES = {"SUPER_ADMIN", "SCHOOL_ADMIN"}


@login_required
def activity_log(request):
    """Display the school's complete human-readable activity history."""
    if getattr(request.user, "role", None) not in AUDIT_ROLES:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("You do not have permission to view the Activity Log.")

    school = getattr(request.user, "school", None)

    # True, always-unfiltered total -- feeds the "Total Activities" KPI and
    # the hero card, so those keep showing the real total regardless of
    # filters. Previously this was set from the *filtered* paginator.count,
    # so it silently matched "Filtered Results" instead of the real total
    # the moment any filter was applied.
    total_activity_count = ActivityLog.objects.filter(school=school).count()

    logs = ActivityLog.objects.filter(school=school).select_related("user", "content_type")

    query = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip().upper()
    model_name = request.GET.get("model", "").strip()
    user_id = request.GET.get("user", "").strip()

    if query:
        logs = logs.filter(
            Q(description__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(object_id__icontains=query)
        )
    if action in {choice[0] for choice in ActivityLog.ACTION_CHOICES}:
        logs = logs.filter(action=action)
    if model_name:
        logs = logs.filter(content_type__model__icontains=model_name)
    if user_id:
        logs = logs.filter(user_id=user_id)

    logs = logs.order_by("-created_at")

    # Shared pagination helper, same as every other list view in the app --
    # this is what makes the "Records per page" control in
    # partials/pagination.html (?per_page=25/50/100) actually work here.
    # The previous django.core.paginator.Paginator(logs, 25) call ignored
    # ?per_page= entirely, so that dropdown silently did nothing on this page.
    page_obj = paginate_queryset(logs, request)

    users = (
        ActivityLog.objects.filter(school=school, user__isnull=False)
        .values("user_id", "user__first_name", "user__last_name", "user__username")
        .distinct()
        .order_by("user__first_name", "user__last_name", "user__username")
    )

    context = {
        "page_obj": page_obj,
        "activity_logs": page_obj.object_list,
        "activity_count": total_activity_count,
        "users": users,
        "action_choices": ActivityLog.ACTION_CHOICES,
        "query": query,
        "selected_action": action,
        "selected_model": model_name,
        "selected_user": user_id,
    }
    return render(request, "core/activity_log.html", context)
