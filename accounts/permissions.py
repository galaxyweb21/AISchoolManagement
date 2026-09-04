from django.core.cache import cache

from .models import UserRole


def has_permission(user, permission_code):

    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    cache_key = f"user_permissions_{user.id}"

    permissions = cache.get(cache_key)

    if permissions is None:

        permissions = set(

            UserRole.objects.filter(
                user=user,
                role__is_active=True,
            ).values_list(
                "role__permissions__code",
                flat=True,
            )

        )

        cache.set(
            cache_key,
            permissions,
            timeout=300,
        )

    return permission_code in permissions