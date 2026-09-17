"""Attach the authenticated request user to audit operations."""

from .audit_context import set_request, clear_request


class ActivityAuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_request(request)
        try:
            return self.get_response(request)
        finally:
            clear_request()
