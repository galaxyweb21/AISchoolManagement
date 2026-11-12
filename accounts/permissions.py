"""Centralized, cache-aware permission checks.

This module is intentionally small and backwards compatible with the
application's existing role/policy system.  It strengthens the database RBAC
path without changing the existing User.role fallback used by the rest of
the application.
"""

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from .models import UserRole


PERMISSION_CACHE_TIMEOUT = 300


def _permission_cache_key(user):
    return f"user_permissions_{user.pk}"


def _load_permissions(user):
    """Return currently active permissions assigned to *user*.

    A UserRole only grants permissions when:
      * the assignment itself is active;
      * the role is active;
      * the assignment has not expired; and
      * the permission is active.

    The existing User.role based ROLE_POLICY remains the backwards-compatible
    fallback in accounts.access.role_allows(). This function only governs
    explicit database RBAC permissions.
    """
    now = timezone.now()

    return set(
        UserRole.objects.filter(
            user=user,
            is_active=True,
            role__is_active=True,
            role__permissions__is_active=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values_list("role__permissions__code", flat=True)
    )


def has_permission(user, permission_code):
    """Check an explicit database permission for an authenticated user.

    Superusers retain unrestricted access.  Permission assignments are
    cached briefly for performance, matching the previous implementation.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    cache_key = _permission_cache_key(user)
    permissions = cache.get(cache_key)

    if permissions is None:
        permissions = _load_permissions(user)
        cache.set(cache_key, permissions, timeout=PERMISSION_CACHE_TIMEOUT)

    return permission_code in permissions


def clear_user_permission_cache(user):
    """Clear cached permissions after an RBAC assignment changes.

    Accepts either a User instance or a user primary-key value.
    """
    if not user:
        return

    user_pk = getattr(user, "pk", user)
    if user_pk:
        cache.delete(f"user_permissions_{user_pk}")
