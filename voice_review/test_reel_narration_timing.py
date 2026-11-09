import unittest

from reel_narration_timing import TimingError, build_script, persian_integer, word_starts


class PronunciationTests(unittest.TestCase):
    def test_examples_and_mapping(self):
        text, tokens = build_script('سال ۲۰۲۶، ۳۱ نفر و ۲۹٪')
        self.assertEqual(text, 'سال دو هزار و بیست و شش، سی و یک نفر و بیست و نه درصد')
        self.assertEqual([t.text for t in tokens], ['سال', '۲۰۲۶،', '۳۱', 'نفر', 'و', '۲۹٪'])
        for token in tokens:
            self.assertEqual(text[token.start:token.end], token.spoken)

    def test_financial_values_and_abbreviations(self):
        text, _ = build_script('$1,234.05 USD BTC -۲٫۵٪')
        self.assertEqual(text, 'یک هزار و دویست و سی و چهار ممیز پنج صدم دلار دلار آمریکا بیت کوین منفی دو ممیز پنج دهم درصد')
        self.assertEqual(persian_integer('1000000000000'), 'یک تریلیون')

    def test_ambiguous_dates_and_malformed_values_fail(self):
        for text in ('08/11/2026', '1,23', '۴–۶', '$29%'):
            with self.subTest(text=text), self.assertRaises(TimingError):
                build_script(text)

    def test_alphanumeric_names_are_not_accidentally_converted(self):
        self.assertEqual(build_script('GPT-4')[0], 'GPT-4')

    def test_iso_dates_keep_one_visible_token(self):
        script, tokens = build_script('تاریخ ۲۰۲۶-۱۱-۰۸')
        self.assertEqual(script, 'تاریخ هشت نوامبر دو هزار و بیست و شش')
        self.assertEqual(tokens[1].text, '۲۰۲۶-۱۱-۰۸')
        self.assertEqual(build_script('2026/11/08')[0], 'هشت نوامبر دو هزار و بیست و شش')
        self.assertEqual(build_script('۱۴۰۵/۰۸/۱۶')[0], 'سال یک هزار و چهارصد و پنج، ماه هشت، روز شانزده')
        for value in ('2026-02-30', '0012'):
            with self.subTest(value=value), self.assertRaises(TimingError):
                build_script(value)


class DecimalPronunciationTests(unittest.TestCase):
    def test_requested_examples_are_whole_fractional_numbers(self):
        examples = {
            '1.38': 'یک ممیز سی و هشت صدم',
            '4000.93': 'چهار هزار ممیز نود و سه صدم',
            '4000.9': 'چهار هزار ممیز نه دهم',
            '12.75': 'دوازده ممیز هفتاد و پنج صدم',
        }
        for display, expected in examples.items():
            with self.subTest(display=display):
                self.assertEqual(build_script(display)[0], expected)

    def test_leading_fractional_zeros_keep_their_value(self):
        examples = {
            '0.05': 'صفر ممیز پنج صدم',
            '1.08': 'یک ممیز هشت صدم',
            '0.005': 'صفر ممیز پنج هزارم',
            '0.0001': 'صفر ممیز یک ده هزارم',
            '0.00001': 'صفر ممیز یک صد هزارم',
            '0.000001': 'صفر ممیز یک میلیونم',
            '0.00000001': 'صفر ممیز یک صد میلیونم',
            '0.000000001': 'صفر ممیز یک میلیاردم',
            '0.000000000001': 'صفر ممیز یک تریلیونم',
            '0.000000000000001': 'صفر ممیز یک هزار تریلیونم',
        }
        for display, expected in examples.items():
            with self.subTest(display=display):
                self.assertEqual(build_script(display)[0], expected)

    def test_persian_arabic_and_grouped_digits_use_the_same_rule(self):
        for display in ('4000.93', '4,000.93', '۴٬۰۰۰٫۹۳', '٤٠٠٠٫٩٣'):
            with self.subTest(display=display):
                self.assertEqual(build_script(display)[0], 'چهار هزار ممیز نود و سه صدم')

    def test_signs_currency_percentage_and_punctuation_stay_attached(self):
        examples = {
            '-۱٫۳۸٪': 'منفی یک ممیز سی و هشت صدم درصد',
            '+4000.9': 'مثبت چهار هزار ممیز نه دهم',
            '$4,000.93': 'چهار هزار ممیز نود و سه صدم دلار',
            '€0.05': 'صفر ممیز پنج صدم یورو',
            '۱٫۳۸،': 'یک ممیز سی و هشت صدم،',
        }
        for display, expected in examples.items():
            with self.subTest(display=display):
                self.assertEqual(build_script(display)[0], expected)

    def test_trailing_zeros_are_simplified_without_rounding(self):
        examples = {
            '4000.90': 'چهار هزار ممیز نه دهم',
            '1.3800': 'یک ممیز سی و هشت صدم',
            '0.0500': 'صفر ممیز پنج صدم',
            '4000.000': 'چهار هزار',
            '0.00': 'صفر',
            '0.000000000000123': 'صفر ممیز صد و بیست و سه هزار تریلیونم',
        }
        for display, expected in examples.items():
            with self.subTest(display=display):
                self.assertEqual(build_script(display)[0], expected)

    def test_unsupported_precision_fails_instead_of_guessing_or_rounding(self):
        with self.assertRaises(TimingError):
            build_script('0.0000000000000001')

    def test_display_and_caption_numbers_are_not_rewritten(self):
        display = 'رشد ۱٫۳۸٪ و قیمت ۴٬۰۰۰٫۹۳ دلار'
        script, tokens = build_script(display)
        self.assertEqual([t.text for t in tokens], display.split())
        self.assertEqual(len(tokens), len(display.split()))
        for token in tokens:
            self.assertEqual(script[token.start:token.end], token.spoken)

    def test_decimal_phrase_keeps_one_visible_timing_token_at_1_5_speed(self):
        script, tokens = build_script('قیمت ۴٬۰۰۰٫۹۳ دلار')
        starts = [i * .03 for i in range(len(script))]
        alignment = {'characters': list(script), 'character_start_times_seconds': starts,
                     'character_end_times_seconds': [x + .02 for x in starts]}
        timings = word_starts(script, tokens, alignment, starts[-1] + .1, speed=1.5)
        self.assertEqual(len(timings), 3)
        self.assertEqual(tokens[1].text, '۴٬۰۰۰٫۹۳')
        self.assertEqual(tokens[1].spoken, 'چهار هزار ممیز نود و سه صدم')
        for token, timing in zip(tokens, timings):
            self.assertAlmostEqual(timing, starts[token.start] / 1.5)

    def test_old_digit_by_digit_alignment_cannot_be_reused(self):
        script, tokens = build_script('قیمت 1.38 دلار')
        old = 'قیمت یک ممیز سه هشت دلار'
        alignment = {'characters': list(old), 'character_start_times_seconds': [0.] * len(old),
                     'character_end_times_seconds': [.1] * len(old)}
        with self.assertRaises(TimingError):
            word_starts(script, tokens, alignment, 1)


class AlignmentTests(unittest.TestCase):
    def test_character_alignment_maps_full_numeric_phrase_to_one_word(self):
        script, tokens = build_script('قیمت ۲۹٪ رشد')
        starts = [i * .1 for i in range(len(script))]
        alignment = {'characters': list(script), 'character_start_times_seconds': starts,
                     'character_end_times_seconds': [x + .05 for x in starts]}
        timings = word_starts(script, tokens, alignment, 20, speed=1.5)
        self.assertEqual(len(timings), 3)
        self.assertAlmostEqual(timings[1], starts[tokens[1].start] / 1.5)
        self.assertAlmostEqual(timings[2], starts[tokens[2].start] / 1.5)

    def test_invalid_alignments_fail_closed(self):
        script, tokens = build_script('عدد ۳۱')
        valid = {'characters': list(script), 'character_start_times_seconds': [0.0] * len(script),
                 'character_end_times_seconds': [0.1] * len(script)}
        for change in (
            {'characters': list(script + '!')},
            {'character_start_times_seconds': [0.0]},
            {'character_end_times_seconds': [float('nan')] * len(script)},
            {'character_end_times_seconds': [100] * len(script)},
        ):
            with self.subTest(change=change), self.assertRaises(TimingError):
                word_starts(script, tokens, dict(valid, **change), 1)


if __name__ == '__main__':
    unittest.main()


