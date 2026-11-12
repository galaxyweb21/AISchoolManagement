"""Reusable server-side permission decorators."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden

from .permissions import has_permission


def permission_required(permission):
    """Require an explicit database permission for a view.

    Anonymous users are sent through Django's normal login flow. Authenticated
    users without the requested permission receive HTTP 403. `wraps` keeps
    the wrapped view metadata intact for URL reversing, debugging and tests.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not getattr(request.user, "is_authenticated", False):
                return redirect_to_login(request.get_full_path())

            if has_permission(request.user, permission):
                return view(request, *args, **kwargs)

            return HttpResponseForbidden("Permission Denied")

        return wrapper

    return decorator
