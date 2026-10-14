"""Calendar regressions for the approved rates-cover date format."""
from datetime import datetime, timedelta, timezone
import unittest

import jdatetime

from instagram_calendar import calendar_labels, PERSIAN_DIGITS


class CalendarTests(unittest.TestCase):
    def labels(self, instant):
        return calendar_labels(datetime.fromisoformat(instant))

    def test_approved_date_and_digits(self):
        labels = self.labels('2026-10-14T11:30:00+03:00')
        self.assertEqual(labels['persian_line'], 'چهارشنبه · ۲۲ مهر ۱۴۰۵')
        self.assertEqual(labels['english_line'], 'Wed · 14 Oct 2026')
        self.assertEqual(labels['time_persian'], '۱۱:۳۰')
        self.assertEqual(labels['time_english'], '11:30')
        self.assertFalse(any(char.isascii() and char.isdigit() for char in labels['persian_line']))

    def test_istanbul_midnight(self):
        before = self.labels('2026-10-14T20:59:59+00:00')
        after = self.labels('2026-10-14T21:00:00+00:00')
        self.assertEqual(before['persian_line'], 'چهارشنبه · ۲۲ مهر ۱۴۰۵')
        self.assertEqual(after['persian_line'], 'پنجشنبه · ۲۳ مهر ۱۴۰۵')
        self.assertEqual(before['time_english'], '23:59')
        self.assertEqual(after['time_english'], '00:00')
        self.assertEqual(after['english_line'], 'Thu · 15 Oct 2026')

    def test_tehran_timestamp_uses_istanbul_date(self):
        labels = self.labels('2026-10-15T00:15:00+03:30')
        self.assertEqual(labels['gregorian_date'], '2026-10-14')
        self.assertEqual(labels['jalali_date'], '1405-07-22')
        self.assertEqual(labels['time_english'], '23:45')

    def test_jalali_year_and_leap_boundaries(self):
        for gregorian, jalali in (
            ('2024-03-20', '1403-01-01'),
            ('2025-03-20', '1403-12-30'),
            ('2025-03-21', '1404-01-01'),
            ('2026-03-20', '1404-12-29'),
            ('2026-03-21', '1405-01-01'),
            ('2027-03-21', '1406-01-01'),
        ):
            with self.subTest(gregorian=gregorian):
                self.assertEqual(self.labels(gregorian + 'T11:30:00+03:00')['jalali_date'], jalali)

    def test_gregorian_year_boundary(self):
        labels = self.labels('2026-12-31T21:00:00+00:00')
        self.assertEqual(labels['english_line'], 'Fri · 1 Jan 2027')
        self.assertEqual(labels['persian_line'], 'جمعه · ۱۱ دی ۱۴۰۵')

    def test_all_weekdays(self):
        for day, fa, en in ((12, 'دوشنبه', 'Mon'), (13, 'سه‌شنبه', 'Tue'),
                            (14, 'چهارشنبه', 'Wed'), (15, 'پنجشنبه', 'Thu'),
                            (16, 'جمعه', 'Fri'), (17, 'شنبه', 'Sat'), (18, 'یکشنبه', 'Sun')):
            labels = self.labels(f'2026-10-{day}T11:30:00+03:00')
            self.assertTrue(labels['persian_line'].startswith(fa + ' · '))
            self.assertTrue(labels['english_line'].startswith(en + ' · '))

    def test_fifty_years_roundtrip_and_same_day(self):
        instant = datetime(2020, 1, 1, 11, 30, tzinfo=timezone(timedelta(hours=3)))
        end = datetime(2070, 1, 1, 11, 30, tzinfo=instant.tzinfo)
        while instant < end:
            labels = calendar_labels(instant)
            year, month, day = map(int, labels['jalali_date'].split('-'))
            self.assertEqual(jdatetime.date(year, month, day).togregorian(), instant.date())
            self.assertEqual(labels['gregorian_date'], instant.date().isoformat())
            self.assertEqual(labels['time_persian'], labels['time_english'].translate(PERSIAN_DIGITS))
            instant += timedelta(days=1)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            calendar_labels(datetime(2026, 10, 14, 11, 30))


if __name__ == '__main__':
    unittest.main()
