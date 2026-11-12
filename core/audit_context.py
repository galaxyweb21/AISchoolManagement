"""Request-scoped context for the global Activity Log."""

from threading import local

_state = local()


def set_request(request):
    _state.request = request


def clear_request():
    if hasattr(_state, "request"):
        del _state.request


def get_request():
    return getattr(_state, "request", None)


def get_current_user():
    request = get_request()
    if request is None:
        return None
    try:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return user
    except Exception:
        pass
    return None


def get_client_ip():
    request = get_request()
    if request is None:
        return None
    try:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
    except Exception:
        return None
