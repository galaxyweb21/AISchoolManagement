# staff/templatetags/staff_filters.py
from django import template

register = template.Library()


@register.filter
def filter_by_percentage(allowances):
    """Filter allowances that are percentage-based."""
    return [a for a in allowances if a.is_percentage]


@register.filter
def filter_by_taxable(allowances):
    """Filter allowances that are taxable."""
    return [a for a in allowances if a.taxable]


@register.filter
def filter_by_mandatory(deductions):
    """Filter deductions that are mandatory."""
    return [d for d in deductions if d.is_mandatory]


@register.filter
def filter_by_percentage_deduction(deductions):
    """Filter deductions that are percentage-based."""
    return [d for d in deductions if d.is_percentage]