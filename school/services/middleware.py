# school/middleware.py
import threading
from django.utils.deprecation import MiddlewareMixin

# Thread-safe container to hold the current school context
_thread_locals = threading.local()

def get_current_school():
    """Retrieves the active school tenant from the current thread."""
    return getattr(_thread_locals, 'school', None)

def set_current_school(school):
    """Binds the active school tenant to the current thread."""
    _thread_locals.school = school

def clear_current_school():
    """Clears the tenant context once the request-response cycle completes."""
    if hasattr(_thread_locals, 'school'):
        del _thread_locals.school


class TenantSecurityMiddleware(MiddlewareMixin):
    """
    Middleware that captures the logged-in user's school
    and registers it to the thread-local context.
    """
    def process_request(self, request):
        if request.user.is_authenticated and hasattr(request.user, 'school'):
            set_current_school(request.user.school)
        else:
            clear_current_school()

    def process_response(self, request, response):
        # Prevent memory leaks across keep-alive connections
        clear_current_school()
        return response

    def process_exception(self, request, exception):
        # Guarantee cleanup even on runtime code crashes
        clear_current_school()