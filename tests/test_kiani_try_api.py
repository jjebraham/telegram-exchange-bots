import unittest
from decimal import Decimal

from kiani_try_api import merge_canonical_try_rates, parse_canonical_try_rates


def payload(**overrides):
    rates = {
        "buy_lira": 5460,
        "sell_lira": 5340,
        "buy_adjustment_pct": "0.2",
        "sell_adjustment_pct": "-2",
        "source_count": 6,
        "market_age_seconds": 12.5,
        "market_stale": False,
        "source": "channel-hybrid-usdt+btcturk",
    }
    rates.update(overrides)
    return {"rates": rates}


class CanonicalTryApiTests(unittest.TestCase):
    def test_reads_admin_adjusted_pair_from_canonical_response(self):
        self.assertEqual(
            parse_canonical_try_rates(payload()),
            {"buy_lira": Decimal("5460"), "sell_lira": Decimal("5340")},
        )

    def test_rejects_stale_or_invalid_canonical_response(self):
        for fields in (
            {"market_stale": True},
            {"market_age_seconds": 91},
            {"buy_lira": 5330},
            {"buy_lira": "NaN"},
            {"source_count": 0},
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    parse_canonical_try_rates(payload(**fields))

    def test_merge_replaces_only_try_pair_and_requires_both_canonical_values(self):
        current = {
            "buy_lira": Decimal("5510"),
            "sell_lira": Decimal("5340"),
            "buy_usdt": Decimal("230000"),
            "sell_usdt": Decimal("225000"),
        }
        canonical = parse_canonical_try_rates(payload())
        merged = merge_canonical_try_rates(current, canonical)

        self.assertEqual(merged["buy_lira"], Decimal("5460"))
        self.assertEqual(merged["sell_lira"], Decimal("5340"))
        self.assertEqual(merged["buy_usdt"], Decimal("230000"))
        self.assertEqual(merged["sell_usdt"], Decimal("225000"))
        with self.assertRaisesRegex(ValueError, "missing: sell_lira"):
            merge_canonical_try_rates(current, {"buy_lira": Decimal("5460")})


if __name__ == "__main__":
    unittest.main()

