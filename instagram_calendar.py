"""Persian and Gregorian display labels from one timezone-aware Istanbul instant."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

# The installer keeps the pinned calendar dependencies separate from the shared
# publisher venv. Local development may instead supply them on PYTHONPATH.
library_root = Path(__file__).resolve().parent / 'instagram_calendar_libs'
if library_root.is_dir():
    sys.path.insert(0, str(library_root))
import jdatetime

ISTANBUL = ZoneInfo('Europe/Istanbul')
PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
MONTHS_FA = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
             'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
WEEKDAYS_FA = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')
WEEKDAYS_EN = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
MONTHS_EN = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def calendar_labels(moment: datetime) -> dict[str, str]:
    """Never use the host date, a global locale, or a separate calendar clock."""
    if not isinstance(moment, datetime):
        raise TypeError('A datetime is required for the rates calendar')
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError('The rates calendar requires a timezone-aware timestamp')
    local = moment.astimezone(ISTANBUL)
    jalali = jdatetime.date.fromgregorian(date=local.date())
    persian = f'{WEEKDAYS_FA[local.weekday()]} · {jalali.day} {MONTHS_FA[jalali.month - 1]} {jalali.year}'
    english = f'{WEEKDAYS_EN[local.weekday()]} · {local.day} {MONTHS_EN[local.month - 1]} {local.year}'
    clock = f'{local.hour:02}:{local.minute:02}'
    return {
        'timezone': 'Europe/Istanbul', 'local_iso': local.isoformat(),
        'gregorian_date': local.date().isoformat(),
        'jalali_date': f'{jalali.year:04}-{jalali.month:02}-{jalali.day:02}',
        'persian_line': persian.translate(PERSIAN_DIGITS),
        'english_line': english,
        'time_persian': clock.translate(PERSIAN_DIGITS), 'time_english': clock,
    }
