from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def pagination_url(context, page_number):
    request = context.get("request")
    if request is None:
        return "?page=%s" % page_number
    params = request.GET.copy()
    params["page"] = page_number
    query = params.urlencode()
    return request.path + ("?" + query if query else "")
