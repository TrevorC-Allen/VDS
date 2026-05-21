"""Date helpers for data-agent analysis plans."""

from __future__ import annotations

import datetime as dt


MONTH_NAME_TO_NUMBER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def month_from_day_of_year(year: int, day_of_year: int) -> int:
    """Return the month number for a 1-based day of year."""

    return (dt.date(year, 1, 1) + dt.timedelta(days=day_of_year - 1)).month
