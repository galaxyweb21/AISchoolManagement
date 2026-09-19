"""Signals that keep the explicit RBAC permission cache fresh.

This module only invalidates the short-lived permission cache when an RBAC
assignment, role, or permission changes. It does not change the existing
User.role/ROLE_POLICY access path.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Permission, Role, RolePermission, UserRole
from .permissions import clear_user_permission_cache


@receiver(post_save, sender=UserRole, dispatch_uid="accounts_rbac_userrole_save")
def clear_userrole_cache_on_save(sender, instance, **kwargs):
    clear_user_permission_cache(instance.user)


@receiver(post_delete, sender=UserRole, dispatch_uid="accounts_rbac_userrole_delete")
def clear_userrole_cache_on_delete(sender, instance, **kwargs):
    clear_user_permission_cache(instance.user)


@receiver(post_save, sender=RolePermission, dispatch_uid="accounts_rbac_rolepermission_save")
def clear_rolepermission_cache_on_save(sender, instance, **kwargs):
    for user_role in UserRole.objects.filter(role=instance.role).only("user_id"):
        clear_user_permission_cache(user_role.user_id)


@receiver(post_delete, sender=RolePermission, dispatch_uid="accounts_rbac_rolepermission_delete")
def clear_rolepermission_cache_on_delete(sender, instance, **kwargs):
    # The role-permission row still carries its role after delete, so we can
    # invalidate all users who were assigned that role.
    for user_role in UserRole.objects.filter(role_id=instance.role_id).only("user_id"):
        clear_user_permission_cache(user_role.user_id)


@receiver(post_save, sender=Role, dispatch_uid="accounts_rbac_role_save")
def clear_role_cache_on_save(sender, instance, **kwargs):
    user_ids = UserRole.objects.filter(role=instance).values_list("user_id", flat=True)
    for user_id in user_ids:
        clear_user_permission_cache(user_id)


@receiver(post_delete, sender=Role, dispatch_uid="accounts_rbac_role_delete")
def clear_role_cache_on_delete(sender, instance, **kwargs):
    # UserRole rows cascade when a Role is deleted, so there may be no rows
    # left to inspect here. Existing cached entries naturally expire within
    # the configured five-minute window; no business flow is changed.
    return


@receiver(post_save, sender=Permission, dispatch_uid="accounts_rbac_permission_save")
def clear_permission_cache_on_save(sender, instance, **kwargs):
    user_ids = UserRole.objects.filter(role__permissions=instance).values_list("user_id", flat=True)
    for user_id in user_ids:
        clear_user_permission_cache(user_id)


@receiver(post_delete, sender=Permission, dispatch_uid="accounts_rbac_permission_delete")
def clear_permission_cache_on_delete(sender, instance, **kwargs):
    # Permission deletion cascades RolePermission rows. Existing cache entries
    # expire shortly and no authorization decision is broadened by this signal.
    return
