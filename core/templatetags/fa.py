import re
from datetime import date, datetime

from django import template
from django.utils import timezone

from core.jalali import PERSIAN_DIGITS, gregorian_to_jalali

register = template.Library()
_digits = PERSIAN_DIGITS
_iso_date = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


@register.filter
def fa(value):
    if value is None:
        return "—"
    return str(value).translate(_digits)


def _date_parts(value):
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.year, value.month, value.day
    if isinstance(value, date):
        return value.year, value.month, value.day
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value[:10])
            return parsed.year, parsed.month, parsed.day
        except ValueError:
            return None
    return None


@register.filter
def jalali_date(value):
    """Render a date as a Persian Solar Hijri date with Persian digits."""
    parts = _date_parts(value)
    if not parts:
        return "—"
    year, month, day = gregorian_to_jalali(*parts)
    return f"{year:04d}/{month:02d}/{day:02d}".translate(_digits)


@register.filter
def jalali_datetime(value):
    """Render a datetime in local time with a Persian Solar Hijri date."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        date_text = jalali_date(value)
        return f"{date_text}، {value:%H:%M}".translate(_digits)
    return jalali_date(value)


@register.filter
def jalali_text_dates(value):
    """Convert ISO Gregorian dates embedded in audit text for display."""
    if value is None:
        return ""

    def replace(match):
        try:
            parsed = date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError:
            return match[0]
        return jalali_date(parsed)

    return _iso_date.sub(replace, str(value))
