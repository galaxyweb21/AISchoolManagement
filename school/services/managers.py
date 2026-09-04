# school/managers.py
from django.db import models
from django.db.models import Manager
from django.apps import apps


class TenantQuerySet(models.QuerySet):
    """
    A QuerySet that transparently scopes queries to the active tenant.

    `school_field` is the lookup path to the school on this model —
    "school" for models with a direct FK, or a relation path like
    "timetable__school" for models (e.g. TimetableEntry) that only
    reach School through a related model. Defaults to "school" so
    every existing call site that doesn't pass one keeps working
    exactly as before.
    """

    def __init__(self, *args, school_field="school", **kwargs):
        super().__init__(*args, **kwargs)
        self.school_field = school_field

    def _clone(self):
        # Django's QuerySet._clone() rebuilds a fresh instance via
        # self.__class__(model=..., query=..., using=..., hints=...)
        # without forwarding extra __init__ kwargs, so school_field
        # would silently reset to "school" on every chained call
        # (e.g. .filter().select_related()) unless carried over here.
        clone = super()._clone()
        clone.school_field = self.school_field
        return clone

    def delete(self):
        # Protects bulk deletes from hitting other tenants.
        # Bound to whatever tenant is active on the current thread, same
        # source of truth the manager's get_queryset() uses below.
        from .middleware import get_current_school

        active_school = get_current_school()
        if active_school:
            return super().filter(**{self.school_field: active_school}).delete()
        return super().delete()


class TenantManager(Manager):
    """
    Manager that automatically applies school-level filters to all queries.

    Usage:
        objects = managers.TenantManager()
            -> filters on this model's own `school` FK (the common case)

        objects = managers.TenantManager(school_field="timetable__school")
            -> filters via a related model's `school` FK, for models that
               don't have a direct `school` column themselves

    IMPORTANT for the second form: pass `school_field` via a dedicated
    subclass (see `related_tenant_manager()` below), not directly on a
    `TenantManager()` instance assigned to a reverse-relation's model.
    Django's reverse-FK related-manager machinery (e.g. `parent.children`)
    subclasses this manager's *class* and instantiates it with
    `super().__init__()` -- zero arguments -- so a `school_field` passed
    only to this specific instance is silently dropped and falls back to
    the "school" default the moment the model is reached via a relation
    instead of `Model.objects` directly.
    """

    def __init__(self, school_field="school"):
        super().__init__()
        self.school_field = school_field

    def get_queryset(self):
        from .middleware import get_current_school

        queryset = TenantQuerySet(self.model, using=self._db, school_field=self.school_field)
        active_school = get_current_school()

        # If a school is bound to the thread-local storage, filter by it
        if active_school:
            return queryset.filter(**{self.school_field: active_school})

        return queryset


def related_tenant_manager(school_field):
    """
    Build a TenantManager subclass that hardcodes `school_field` in its
    own zero-argument __init__, instead of relying on a constructor
    kwarg passed to one particular instance.

    Use this (not `TenantManager(school_field=...)`) for any model that
    doesn't have a direct `school` FK and is ever accessed through a
    reverse relation (`parent.children.all()`), e.g.:

        class TimetableEntry(models.Model):
            ...
            objects = managers.related_tenant_manager("timetable__school")()

    Because the hardcoded value lives inside this subclass's own
    __init__ rather than being passed in externally, it survives
    Django's related-manager subclassing -- which calls
    `super().__init__()` with no arguments -- unlike passing
    `school_field=` to a `TenantManager()` instance directly.
    """

    class _RelatedTenantManager(TenantManager):
        def __init__(self):
            super().__init__(school_field=school_field)

    return _RelatedTenantManager
