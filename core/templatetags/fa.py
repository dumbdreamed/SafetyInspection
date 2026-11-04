from django import template

register = template.Library()
_digits = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@register.filter
def fa(value):
    if value is None:
        return "—"
    return str(value).translate(_digits)
