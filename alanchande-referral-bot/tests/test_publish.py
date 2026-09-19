import unittest

from telegram_bot.publish import parse_publish_args


class PublishPromoTests(unittest.TestCase):
    def test_publish_args_default_to_variant_a_and_normalize_source(self):
        source, variant = parse_publish_args(["Main Channel!!"])
        self.assertEqual(source, "main_channel")
        self.assertEqual(variant, "a")

    def test_publish_args_accept_variant_b(self):
        source, variant = parse_publish_args(["instagram", "B"])
        self.assertEqual(source, "instagram")
        self.assertEqual(variant, "b")

    def test_publish_args_reject_missing_or_invalid_variant(self):
        with self.assertRaises(ValueError):
            parse_publish_args([])
        with self.assertRaises(ValueError):
            parse_publish_args(["mainchannel", "c"])


if __name__ == "__main__":
    unittest.main()
