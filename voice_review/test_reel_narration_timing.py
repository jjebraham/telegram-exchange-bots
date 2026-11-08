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
        self.assertEqual(text, 'یک هزار و دویست و سی و چهار ممیز صفر پنج دلار دلار آمریکا بیت کوین منفی دو ممیز پنج درصد')
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

