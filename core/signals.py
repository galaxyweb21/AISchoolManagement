# core/signals.py

"""
Global Activity Logging Signals

This module provides safe, defensive audit logging for the application.

Important design rules:

1. ActivityLog itself is never logged.
2. Django/system models are ignored.
3. The signal never prevents the original model operation from succeeding.
4. Models without a school/user field are handled safely.
5. ContentType failures are ignored safely.
6. UUID and integer primary keys are supported.
7. The signal is safe during migrations/test database creation.
8. Activity logging is best-effort and must never break business logic.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import OperationalError, ProgrammingError
from django.db.models.signals import post_delete, post_save
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .audit_context import get_current_user, get_client_ip


logger = logging.getLogger(__name__)


# ============================================================================
# MODELS THAT SHOULD NEVER BE AUDITED
# ============================================================================

EXCLUDED_MODELS = {
    "ActivityLog",

    # Django authentication/admin/session infrastructure
    "LogEntry",
    "Session",

    # ContentType itself must not be logged because ActivityLog depends on it.
    "ContentType",

    # Migration history
    "MigrationRecord",

    # Optional common framework/system models
    "Permission",
    "Group",
}


# ============================================================================
# APPLICATIONS THAT SHOULD NOT BE GLOBALLY AUDITED
# ============================================================================

EXCLUDED_APPS = {
    "contenttypes",
    "sessions",
    "admin",
    "migrations",
}


# ============================================================================
# SAFE HELPERS
# ============================================================================

def _is_excluded_model(sender):
    """
    Determine whether a model should be ignored by the audit system.
    """

    if sender is None:
        return True

    model_name = getattr(
        sender._meta,
        "object_name",
        sender.__name__,
    )

    model_name_lower = model_name.lower()

    if model_name in EXCLUDED_MODELS:
        return True

    if model_name_lower == "activitylog":
        return True

    app_label = getattr(
        sender._meta,
        "app_label",
        "",
    )

    if app_label in EXCLUDED_APPS:
        return True

    return False


def _get_school(instance):
    """
    Safely resolve the school associated with an object.

    Supports:

        instance.school

    and avoids raising exceptions when a model does not have
    a school relationship.
    """

    try:
        school = getattr(
            instance,
            "school",
            None,
        )
    except Exception:
        return None

    return school


def _get_user(instance):
    """
    Safely resolve the user associated with an object.

    Supports:

        instance.user
        instance.created_by
        instance.updated_by
        instance.owner

    The first available authenticated/user-like object is returned.
    """

    candidate_fields = (
        "user",
        "created_by",
        "updated_by",
        "owner",
    )

    for field_name in candidate_fields:

        try:
            value = getattr(
                instance,
                field_name,
                None,
            )
        except Exception:
            value = None

        if value is not None:
            return value

    return None


def _get_object_id(instance):
    """
    Safely obtain the object's primary key.

    Supports UUID, integer, string and other Django-compatible
    primary key types.

    ActivityLog.object_id is expected to be compatible with the
    application's model identifiers.
    """

    try:
        object_id = getattr(
            instance,
            "pk",
            None,
        )
    except Exception:
        return None

    if object_id is None:
        return None

    return object_id


def _get_content_type(instance):
    """
    Safely obtain the ContentType for an object.

    During database creation/migrations the contenttypes table may
    temporarily be unavailable.

    In that situation we simply skip audit logging instead of
    breaking the application.
    """

    try:
        return ContentType.objects.get_for_model(
            instance,
            for_concrete_model=False,
        )

    except (
        OperationalError,
        ProgrammingError,
    ):
        return None

    except Exception:
        logger.debug(
            "Unable to determine ContentType for %s.",
            type(instance).__name__,
            exc_info=True,
        )
        return None


def _build_description(
    action,
    instance,
    sender,
):
    """
    Build a safe human-readable audit description.
    """

    model_name = getattr(
        sender._meta,
        "verbose_name",
        sender.__name__,
    )

    try:
        object_label = str(instance)
    except Exception:
        object_label = f"ID {getattr(instance, 'pk', 'unknown')}"

    # Prevent excessively large audit descriptions.
    object_label = object_label[:250]

    if action == "CREATE":
        verb = "created"

    elif action == "UPDATE":
        verb = "updated"

    elif action == "DELETE":
        verb = "deleted"

    else:
        verb = action.lower()

    return (
        f"{action}: "
        f"{model_name} "
        f"'{object_label}' was {verb}."
    )


def _create_activity_log(
    *,
    sender,
    instance,
    action,
):
    """
    Create an ActivityLog safely.

    This function is intentionally defensive.

    IMPORTANT:

    Activity logging must NEVER break the actual business operation.
    """

    if _is_excluded_model(sender):
        return

    # ------------------------------------------------------------------
    # Resolve primary key
    # ------------------------------------------------------------------

    object_id = _get_object_id(instance)

    if object_id is None:
        return

    # ------------------------------------------------------------------
    # Resolve ContentType
    # ------------------------------------------------------------------

    content_type = _get_content_type(instance)

    if content_type is None:
        return

    # ------------------------------------------------------------------
    # Resolve school/user
    # ------------------------------------------------------------------

    school = _get_school(instance)
    # Web requests have the most accurate actor information.
    user = get_current_user() or _get_user(instance)
    ip_address = get_client_ip()

    # ------------------------------------------------------------------
    # Import lazily.
    #
    # This reduces startup/import-order problems and is particularly
    # useful during Django migrations and test database creation.
    # ------------------------------------------------------------------

    try:
        from .models import ActivityLog
    except Exception:
        logger.debug(
            "ActivityLog model could not be imported.",
            exc_info=True,
        )
        return

    # ------------------------------------------------------------------
    # Create audit record
    # ------------------------------------------------------------------

    try:

        description = _build_description(
            action=action,
            instance=instance,
            sender=sender,
        )

        # Student records get a business-readable message.
        # Example: "Admin created a new student Ama Owusu, class K.G 1
        # (K.G 1), student ID 33442."
        if getattr(sender._meta, "model_name", "") == "student":
            try:
                full_name = instance.user.get_full_name().strip()
            except Exception:
                full_name = str(getattr(instance, "user", "Student"))
            admission = getattr(instance, "admission_number", None) or getattr(instance, "pk", "")
            try:
                grade = str(instance.grade_level) if instance.grade_level else "Unassigned"
            except Exception:
                grade = "Unassigned"
            try:
                school_class = str(instance.school_class) if instance.school_class else "Unassigned"
            except Exception:
                school_class = "Unassigned"

            if action == "CREATE":
                description = (
                    f"created a new student {full_name}, class {school_class} "
                    f"({grade}), student ID {admission}."
                )
            elif action == "UPDATE":
                description = (
                    f"updated student {full_name}, class {school_class} "
                    f"({grade}), student ID {admission}."
                )
            elif action == "DELETE":
                description = (
                    f"deleted student {full_name}, class {school_class} "
                    f"({grade}), student ID {admission}."
                )

        ActivityLog.objects.create(
            school=school,
            user=user,
            content_type=content_type,
            object_id=object_id,
            action=action,
            description=description,
            ip_address=ip_address,
        )

    except (
        OperationalError,
        ProgrammingError,
    ):
        # Database may not yet be ready during migrations/tests.
        #
        # DO NOT re-raise.
        logger.debug(
            "ActivityLog database operation skipped for %s.",
            sender.__name__,
            exc_info=True,
        )

    except Exception:
        # Audit logging is secondary infrastructure.
        #
        # Never allow an audit failure to break:
        #
        #   Student creation
        #   Staff creation
        #   Leave approval
        #   Payroll
        #   Attendance
        #   Finance
        #   etc.
        #
        logger.exception(
            "ActivityLog failed for %s (%s).",
            sender.__name__,
            action,
        )


# ============================================================================
# POST SAVE
# ============================================================================

@receiver(
    post_save,
    dispatch_uid="core_activity_log_post_save",
)
def log_model_save(
    sender,
    instance,
    created,
    raw=False,
    **kwargs,
):
    """
    Audit CREATE and UPDATE operations.

    `raw=True` is used by Django when loading fixture data.
    Those operations should not normally generate audit records.
    """

    # --------------------------------------------------------------
    # Never audit fixture/raw loading.
    # --------------------------------------------------------------

    if raw:
        return

    # --------------------------------------------------------------
    # Never audit excluded models.
    # --------------------------------------------------------------

    if _is_excluded_model(sender):
        return

    action = (
        "CREATE"
        if created
        else "UPDATE"
    )

    _create_activity_log(
        sender=sender,
        instance=instance,
        action=action,
    )


# ============================================================================
# POST DELETE
# ============================================================================

@receiver(
    post_delete,
    dispatch_uid="core_activity_log_post_delete",
)
def log_model_delete(
    sender,
    instance,
    **kwargs,
):
    """
    Audit DELETE operations.
    """

    if _is_excluded_model(sender):
        return

    _create_activity_log(
        sender=sender,
        instance=instance,
        action="DELETE",
    )

# ============================================================================
# AUTHENTICATION EVENTS
# ============================================================================


def _create_auth_activity_log(user, action, request=None):
    """Record login/logout events without affecting authentication itself."""
    if not user or not getattr(user, "pk", None):
        return

    try:
        from .models import ActivityLog
        from django.contrib.contenttypes.models import ContentType

        content_type = ContentType.objects.get_for_model(
            user,
            for_concrete_model=False,
        )

        ip_address = None
        if request is not None:
            try:
                forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
                ip_address = (
                    forwarded.split(",")[0].strip()
                    if forwarded
                    else request.META.get("REMOTE_ADDR")
                )
            except Exception:
                ip_address = None

        ActivityLog.objects.create(
            school=getattr(user, "school", None),
            user=user,
            content_type=content_type,
            object_id=str(user.pk),
            action=action,
            description=(
                f"{action}: user '{getattr(user, 'username', user)}' "
                f"{action.lower()} successfully."
            ),
            ip_address=ip_address,
        )
    except Exception:
        # Authentication must never fail because audit logging failed.
        logger.debug("Authentication audit logging failed for %s.", action, exc_info=True)


@receiver(user_logged_in, dispatch_uid="core_activity_log_user_logged_in")
def log_user_login(sender, request, user, **kwargs):
    _create_auth_activity_log(user, "LOGIN", request=request)


@receiver(user_logged_out, dispatch_uid="core_activity_log_user_logged_out")
def log_user_logout(sender, request, user, **kwargs):
    _create_auth_activity_log(user, "LOGOUT", request=request)
