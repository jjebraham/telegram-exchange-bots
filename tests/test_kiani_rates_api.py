import io
import json
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from channel_split.kiani_rates_api import fetch_kiani_rates


SAMPLE_RATES = {
    "buy_lira": 5480,
    "sell_lira": 5310,
    "buy_usdt": 269570,
    "sell_usdt": 264230,
    "lira_to_usdt": 50.21,
    "usdt_to_lira": 48.24,
}


class KianiRatesApiTests(unittest.TestCase):
    def test_fetches_six_customer_rates_from_one_snapshot(self):
        body = json.dumps({"rates": SAMPLE_RATES}).encode()
        with patch(
            "channel_split.kiani_rates_api.urlopen",
            return_value=io.BytesIO(body),
        ) as request:
            result = fetch_kiani_rates(url="https://rates.test/current")

        self.assertEqual(request.call_count, 1)
        self.assertEqual(
            result,
            {key: Decimal(str(value)) for key, value in SAMPLE_RATES.items()},
        )

    def test_uses_server_environment_override(self):
        body = json.dumps({"rates": SAMPLE_RATES}).encode()
        with (
            patch.dict(os.environ, {"KIANI_RATES_URL": "https://rates.test/env"}),
            patch(
                "channel_split.kiani_rates_api.urlopen",
                return_value=io.BytesIO(body),
            ) as request,
        ):
            fetch_kiani_rates()

        self.assertEqual(request.call_args.args[0].full_url, "https://rates.test/env")

    def test_rejects_incomplete_or_invalid_rates(self):
        with patch(
            "channel_split.kiani_rates_api.urlopen",
            return_value=io.BytesIO(json.dumps({"rates": {"buy_lira": 5480}}).encode()),
        ):
            with self.assertRaisesRegex(ValueError, "Missing Kiani rates"):
                fetch_kiani_rates(retries=1)

        invalid = {**SAMPLE_RATES, "buy_lira": 0}
        with patch(
            "channel_split.kiani_rates_api.urlopen",
            return_value=io.BytesIO(json.dumps({"rates": invalid}).encode()),
        ):
            with self.assertRaisesRegex(ValueError, "must be positive"):
                fetch_kiani_rates(retries=1)


if __name__ == "__main__":
    unittest.main()
