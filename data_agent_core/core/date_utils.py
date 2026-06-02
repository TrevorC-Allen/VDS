"""Date helpers for data-agent analysis plans."""

from __future__ import annotations

import datetime as dt


MONTH_NAME_TO_NUMBER = {
    "january": 1,
    "jan": 1,
    "一月": 1,
    "1月": 1,
    "01月": 1,
    "february": 2,
    "feb": 2,
    "二月": 2,
    "2月": 2,
    "02月": 2,
    "march": 3,
    "mar": 3,
    "三月": 3,
    "3月": 3,
    "03月": 3,
    "april": 4,
    "apr": 4,
    "四月": 4,
    "4月": 4,
    "04月": 4,
    "may": 5,
    "五月": 5,
    "5月": 5,
    "05月": 5,
    "june": 6,
    "jun": 6,
    "六月": 6,
    "6月": 6,
    "06月": 6,
    "july": 7,
    "jul": 7,
    "七月": 7,
    "7月": 7,
    "07月": 7,
    "august": 8,
    "aug": 8,
    "八月": 8,
    "8月": 8,
    "08月": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "九月": 9,
    "9月": 9,
    "09月": 9,
    "october": 10,
    "oct": 10,
    "十月": 10,
    "10月": 10,
    "november": 11,
    "nov": 11,
    "十一月": 11,
    "11月": 11,
    "december": 12,
    "dec": 12,
    "十二月": 12,
    "12月": 12,
}


def month_from_day_of_year(year: int, day_of_year: int) -> int:
    """Return the month number for a 1-based day of year."""

    return (dt.date(year, 1, 1) + dt.timedelta(days=day_of_year - 1)).month
