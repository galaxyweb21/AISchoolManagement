# staff/templatetags/staff_extras.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using a key.
    Usage: {{ dictionary|get_item:key }}
    """
    if dictionary is None:
        return None
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

@register.filter
def multiply(a, b):
    """
    Multiply two numbers.
    Usage: {{ a|multiply:b }}
    """
    try:
        return int(a) * int(b)
    except (ValueError, TypeError):
        return 0