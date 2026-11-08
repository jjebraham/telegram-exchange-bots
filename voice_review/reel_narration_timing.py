"""Build auditable spoken/display token mappings for a private Reel preview.

No network, production configuration or publishing is performed here.
Unsupported numeric forms are rejected rather than guessed.
"""
from dataclasses import dataclass
from datetime import date
import math
import re


class TimingError(ValueError):
    pass


_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
_ONES = ('صفر', 'یک', 'دو', 'سه', 'چهار', 'پنج', 'شش', 'هفت', 'هشت', 'نه')
_TEENS = ('ده', 'یازده', 'دوازده', 'سیزده', 'چهارده', 'پانزده', 'شانزده', 'هفده', 'هجده', 'نوزده')
_TENS = ('', '', 'بیست', 'سی', 'چهل', 'پنجاه', 'شصت', 'هفتاد', 'هشتاد', 'نود')
_HUNDREDS = ('', 'صد', 'دویست', 'سیصد', 'چهارصد', 'پانصد', 'ششصد', 'هفتصد', 'هشتصد', 'نهصد')
_SCALES = ('', 'هزار', 'میلیون', 'میلیارد', 'تریلیون')
_WORDS = {
    'BTC': 'بیت کوین', 'ETH': 'اتریوم', 'USDT': 'تتر',
    'USDC': 'یو اس دی سی', 'XRP': 'ایکس آر پی', 'BNB': 'بی ان بی',
    'USD': 'دلار آمریکا', 'EUR': 'یورو', 'GBP': 'پوند', 'TRY': 'لیر ترکیه',
}
_TOKEN = re.compile(r'^(?P<left>[\(\[«“"\u200c]*)(?P<body>.*?)(?P<right>[\)\]»”"،,؛;:!?؟.!]*)$')
_NUMBER = re.compile(r'^(?P<sign>[+\-−]?)(?P<num>(?:\d{1,3}(?:[,٬]\d{3})+|\d+)(?:[.٫]\d+)?)(?P<pct>[%٪]?)$')
_ISO_DATE = re.compile(r'^(\d{4})([-/])(\d{2})\2(\d{2})$')
_MONTHS = ('ژانویه', 'فوریه', 'مارس', 'آوریل', 'مه', 'ژوئن',
           'ژوئیه', 'اوت', 'سپتامبر', 'اکتبر', 'نوامبر', 'دسامبر')


def _below_thousand(value):
    parts = []
    hundreds, rest = divmod(value, 100)
    if hundreds:
        parts.append(_HUNDREDS[hundreds])
    if 10 <= rest < 20:
        parts.append(_TEENS[rest - 10])
    else:
        tens, units = divmod(rest, 10)
        if tens:
            parts.append(_TENS[tens])
        if units:
            parts.append(_ONES[units])
    return ' و '.join(parts)


def persian_integer(digits):
    if not digits or not digits.isascii() or not digits.isdigit() or len(digits) > 15:
        raise TimingError('Unsupported integer')
    value = int(digits)
    if value == 0:
        return _ONES[0]
    parts = []
    index = 0
    while value:
        value, group = divmod(value, 1000)
        if group:
            parts.append(' '.join(x for x in (_below_thousand(group), _SCALES[index]) if x))
        index += 1
    return ' و '.join(reversed(parts))


@dataclass(frozen=True)
class DisplayToken:
    text: str
    spoken: str
    start: int
    end: int


def _spoken(token):
    match = _TOKEN.fullmatch(token)
    body = match.group('body')
    ascii_body = body.translate(_DIGITS)
    iso_date = _ISO_DATE.fullmatch(ascii_body)
    if iso_date:
        year, month, day = (int(iso_date.group(i)) for i in (1, 3, 4))
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            raise TimingError('Invalid numeric date')
        if not 1900 <= year <= 2100:
            # The calendar is not identified by the numeric date alone.
            return ('سال ' + persian_integer(str(year)) + '، ماه ' +
                    persian_integer(str(month)) + '، روز ' + persian_integer(str(day)) +
                    match.group('right'))
        try:
            date(year, month, day)
        except ValueError:
            raise TimingError('Invalid ISO date') from None
        return (persian_integer(str(day)) + ' ' + _MONTHS[month - 1] + ' ' +
                persian_integer(str(year)) + match.group('right'))
    currency = ''
    if ascii_body[:1] in ('$', '€', '£', '₺'):
        currency = {'$': 'دلار', '€': 'یورو', '£': 'پوند', '₺': 'لیر'}[ascii_body[0]]
        ascii_body = ascii_body[1:]
    number = _NUMBER.fullmatch(ascii_body)
    if number:
        if currency and number.group('pct'):
            raise TimingError('Ambiguous currency percentage')
        value = number.group('num').replace(',', '').replace('٬', '')
        value = value.replace('٫', '.')
        integer, separator, fraction = value.partition('.')
        if len(integer) > 1 and integer.startswith('0'):
            raise TimingError('A leading-zero number needs pronunciation review')
        result = persian_integer(integer)
        if separator:
            result += ' ممیز ' + ' '.join(_ONES[int(d)] for d in fraction)
        if number.group('sign') in ('-', '−'):
            result = 'منفی ' + result
        elif number.group('sign') == '+':
            result = 'مثبت ' + result
        if number.group('pct'):
            result += ' درصد'
        if currency:
            result += ' ' + currency
        return result + match.group('right')
    if any(c.isdigit() for c in ascii_body):
        # Tickers/version names such as GPT-4 may be passed through; numeric
        # dates, ranges and malformed values require a reviewed pronunciation.
        if re.search(r'[A-Za-z]', ascii_body):
            return token
        raise TimingError('A numeric expression needs pronunciation review')
    return match.group('left') + _WORDS.get(body.upper(), body) + match.group('right')


def build_script(display_text):
    if not isinstance(display_text, str) or not display_text.split():
        raise TimingError('Display text is empty')
    tokens = []
    pieces = []
    position = 0
    for word in display_text.split():
        spoken = _spoken(word)
        if not spoken.strip():
            raise TimingError('Empty spoken token')
        if pieces:
            position += 1
        start = position
        position += len(spoken)
        pieces.append(spoken)
        tokens.append(DisplayToken(word, spoken, start, position))
    return ' '.join(pieces), tokens


def word_starts(script, tokens, alignment, source_duration, speed=1.5):
    if not isinstance(alignment, dict) or not math.isfinite(source_duration) or source_duration <= 0:
        raise TimingError('Invalid audio or alignment')
    if not math.isfinite(speed) or not 0.5 <= speed <= 2:
        raise TimingError('Unsupported narration speed')
    chars = alignment.get('characters')
    starts = alignment.get('character_start_times_seconds')
    ends = alignment.get('character_end_times_seconds')
    if not isinstance(chars, list) or any(not isinstance(c, str) or len(c) != 1 for c in chars) or ''.join(chars) != script:
        raise TimingError('Alignment does not match the spoken script')
    if not isinstance(starts, list) or not isinstance(ends, list) or len(starts) != len(chars) or len(ends) != len(chars):
        raise TimingError('Alignment arrays are incomplete')
    previous = 0.0
    for start, end in zip(starts, ends):
        if (isinstance(start, bool) or isinstance(end, bool) or
                not isinstance(start, (float, int)) or not isinstance(end, (float, int)) or
                not math.isfinite(start) or not math.isfinite(end) or
                start < previous or end < start or end > source_duration + 0.15):
            raise TimingError('Alignment timestamps are invalid')
        previous = start
    result = []
    last_end = 0
    for token in tokens:
        if token.start < last_end or token.end > len(chars) or token.start >= token.end or script[token.start:token.end] != token.spoken:
            raise TimingError('Display token mapping is invalid')
        result.append(starts[token.start] / speed)
        last_end = token.end
    return result

