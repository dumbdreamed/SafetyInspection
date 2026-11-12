"""Helpers for displaying dates in the Persian Solar Hijri calendar."""

from datetime import date, timedelta

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def gregorian_to_jalali(year, month, day):
    """Convert a Gregorian date to its Solar Hijri year, month, and day."""
    year -= 1600
    month -= 1
    day -= 1

    gregorian_month_days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    days = 365 * year + (year + 3) // 4 - (year + 99) // 100 + (year + 399) // 400
    for index in range(month):
        days += gregorian_month_days[index]
    if month > 1 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        days += 1
    days += day - 79

    cycles, days = divmod(days, 12053)
    jalali_year = 979 + 33 * cycles + 4 * (days // 1461)
    days %= 1461
    if days >= 366:
        jalali_year += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jalali_month = 1 + days // 31
        jalali_day = 1 + days % 31
    else:
        jalali_month = 7 + (days - 186) // 30
        jalali_day = 1 + (days - 186) % 30
    return jalali_year, jalali_month, jalali_day


def format_jalali_month(value):
    """Return a Gregorian date's Persian-calendar month as YYYY/MM."""
    year, month, _ = gregorian_to_jalali(value.year, value.month, value.day)
    return format_jalali_month_parts(year, month)


def format_jalali_date(value):
    """Return a date as Persian-digit YYYY/MM/DD."""
    year, month, day = gregorian_to_jalali(value.year, value.month, value.day)
    return f"{year:04d}/{month:02d}/{day:02d}".translate(PERSIAN_DIGITS)


def format_jalali_month_parts(year, month):
    """Return a Persian calendar month and year as YYYY/MM."""
    return f"{year:04d}/{month:02d}".translate(PERSIAN_DIGITS)


def jalali_to_gregorian(year, month, day):
    """Convert a Solar Hijri date to Gregorian using a bounded calendar scan."""
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ValueError("Invalid Solar Hijri date")
    start = date(year + 621, 3, 18)
    for offset in range(371):
        candidate = start + timedelta(days=offset)
        if gregorian_to_jalali(candidate.year, candidate.month, candidate.day) == (year, month, day):
            return candidate
    raise ValueError("Invalid Solar Hijri date")
