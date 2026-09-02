"""Accounting-convention formatting, registered as Jinja filters.

Principle P9: thousands separators, parentheses for negatives, consistent
decimals, unambiguous dates. All amounts are USD — a currency code is never
rendered and there is no currency selector.
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

EM_DASH = "—"  # what a null renders as; never a blank cell, never a zero

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _as_number(value, decimals):
    """Parse and round half-up.

    Decimal rather than float, because float rounding is not what an
    accountant expects: 1,234.55 is a hair under 1234.55 in binary, so
    `f"{1234.55:.1f}"` gives 1,234.5 where the rate card says 1,234.6. On a
    figure that gets multiplied by an hourly rate, that difference propagates.
    """
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite():
        return None
    return number.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def money(value, decimals=2, blank=EM_DASH):
    """$1,234.56 — negatives in parentheses, never a minus sign."""
    number = _as_number(value, decimals)
    if number is None:
        return blank
    formatted = f"${abs(number):,.{decimals}f}"
    return f"({formatted})" if number < 0 else formatted


def num(value, decimals=0, blank=EM_DASH):
    number = _as_number(value, decimals)
    if number is None:
        return blank
    formatted = f"{abs(number):,.{decimals}f}"
    return f"({formatted})" if number < 0 else formatted


def pct(value, decimals=0, blank=EM_DASH):
    """Takes a percentage, not a ratio — pass 62.4, not 0.624."""
    number = _as_number(value, decimals)
    if number is None:
        return blank
    formatted = f"{abs(number):,.{decimals}f}%"
    return f"({formatted})" if number < 0 else formatted


def hours(value, decimals=1, blank=EM_DASH):
    number = _as_number(value, decimals)
    if number is None:
        return blank
    return f"{number:,.{decimals}f} h"


def fte(value, decimals=2, blank=EM_DASH):
    number = _as_number(value, decimals)
    if number is None:
        return blank
    return f"{number:,.{decimals}f} FTE"


def _to_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    return None


def _to_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def date_long(value, blank=EM_DASH):
    """14 Nov 2026 — unambiguous to both US and UK readers."""
    parsed = _to_date(value)
    if parsed is None:
        return blank
    return f"{parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"


def date_short(value, blank=EM_DASH):
    parsed = _to_date(value)
    if parsed is None:
        return blank
    return f"{parsed.day} {_MONTHS[parsed.month - 1]}"


def datetime_long(value, blank=EM_DASH):
    parsed = _to_datetime(value)
    if parsed is None:
        return blank
    return f"{date_long(parsed.date())}, {parsed.strftime('%H:%M')}"


def ago(value, now=None, blank=EM_DASH):
    """Relative age. `now` is a parameter so this is testable and backdatable."""
    parsed = _to_datetime(value)
    if parsed is None:
        return blank
    now = now or datetime.now()
    seconds = (now - parsed).total_seconds()
    if seconds < 0:
        return "in the future"
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours_elapsed = minutes / 60
    if hours_elapsed < 24:
        count = int(hours_elapsed)
        return f"{count} hour{'s' if count != 1 else ''} ago"
    days = hours_elapsed / 24
    if days < 30:
        count = int(days)
        return f"{count} day{'s' if count != 1 else ''} ago"
    return date_long(parsed.date())


def initials(name, blank="?"):
    parts = [p for p in str(name or "").replace(",", " ").split() if p]
    if not parts:
        return blank
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


FILTERS = {
    "money": money,
    "num": num,
    "pct": pct,
    "hours": hours,
    "fte": fte,
    "date_long": date_long,
    "date_short": date_short,
    "datetime_long": datetime_long,
    "ago": ago,
    "initials": initials,
}


def register(app):
    for name, function in FILTERS.items():
        app.jinja_env.filters[name] = function
