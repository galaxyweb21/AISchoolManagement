"""Enterprise pagination helpers shared across school modules."""
from django.core.paginator import Paginator

DEFAULT_PAGE_SIZE = 25
MIN_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


def get_page_size(request, default=DEFAULT_PAGE_SIZE):
    """Return a safe per-page size from ?per_page=, clamped to 10..100."""
    try:
        value = int(request.GET.get("per_page", default))
    except (TypeError, ValueError):
        value = default
    return max(MIN_PAGE_SIZE, min(MAX_PAGE_SIZE, value))


def paginate_queryset(queryset, request, default=DEFAULT_PAGE_SIZE):
    """Paginate a QuerySet/list without evaluating the full result set."""
    paginator = Paginator(queryset, get_page_size(request, default))
    return paginator.get_page(request.GET.get("page", 1))
