from django.http import HttpResponseForbidden
from .permissions import has_permission


def permission_required(permission):

    def decorator(view):

        def wrapper(request, *args, **kwargs):

            if has_permission(request.user, permission):
                return view(request, *args, **kwargs)

            return HttpResponseForbidden(
                "Permission Denied"
            )

        return wrapper

    return decorator