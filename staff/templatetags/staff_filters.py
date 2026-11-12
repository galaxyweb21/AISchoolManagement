# staff/templatetags/staff_filters.py
from django import template

register = template.Library()


# ============================================================
# DICTIONARY LOOKUP
# ============================================================

@register.filter
def get_item(dictionary, key):
    """
    Safely look up a value in a dictionary by key.

    Usage in templates:
        {{ some_dict|get_item:some_key }}

    Handles:
        - None dictionary
        - Non-dict values (falls back to indexing)
        - Missing keys (returns None)
        - UUID / string / int keys
    """
    if dictionary is None:
        return None

    try:
        # Prefer dict-style lookup
        if hasattr(dictionary, "get"):
            return dictionary.get(key)

        # Fallback: try indexing
        return dictionary[key]
    except (KeyError, TypeError, AttributeError):
        return None


# ============================================================
# ALLOWANCE FILTERS
# ============================================================

@register.filter
def filter_by_percentage(allowances):
    """Filter allowances that are percentage-based."""
    return [a for a in allowances if a.is_percentage]


@register.filter
def filter_by_taxable(allowances):
    """Filter allowances that are taxable."""
    return [a for a in allowances if a.taxable]


# ============================================================
# DEDUCTION FILTERS
# ============================================================

@register.filter
def filter_by_mandatory(deductions):
    """Filter deductions that are mandatory."""
    return [d for d in deductions if d.is_mandatory]


@register.filter
def filter_by_percentage_deduction(deductions):
    """Filter deductions that are percentage-based."""
    return [d for d in deductions if d.is_percentage]