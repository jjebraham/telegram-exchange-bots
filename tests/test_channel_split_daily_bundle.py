import io
import sys
import unittest
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "channel_split"))

import publish_channels  # noqa: E402
from market_safety import PostSafetyAssessment, VERIFIED  # noqa: E402


class DailyBundleCommandTests(unittest.TestCase):
    def test_daily_dry_run_builds_five_independent_posts(self):
        argv = [
            "publish_channels.py",
            "--post",
            "alanchande-daily",
            "--dry-run",
        ]

        verified = PostSafetyAssessment(
            post_type="fixture",
            decision=VERIFIED,
            reason="fixture verified",
            checks=(),
        )

        usd = [
            SimpleNamespace(
                name="Kapalıçarşı",
                buy=Decimal("48.69"),
                sell=Decimal("48.71"),
            )
        ]
        eur = [
            SimpleNamespace(
                name="Kapalıçarşı",
                buy=Decimal("55.80"),
                sell=Decimal("55.85"),
            )
        ]

        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "fetch_usd_comparison",
                    return_value=usd,
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "fetch_eur_comparison",
                    return_value=eur,
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "fetch_turkish_gold_quotes",
                    return_value=["TGOLD"],
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "fetch_iran_gold_market",
                    return_value="IGOLD",
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "collect_hybrid_usdt_quotes",
                    return_value=["USDT"],
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "fetch_altinkaynak_currency_quotes",
                    return_value={},
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "fetch_altinkaynak_gold_quotes",
                    return_value={},
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "load_bank_fx_near_24h",
                    return_value={},
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "load_turkey_gold_near_24h",
                    return_value={},
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "load_iran_gold_near_24h",
                    return_value={},
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "build_usd_comparison_post",
                    return_value="BANK",
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "build_turkey_fx_pulse_post",
                    return_value="PULSE",
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "build_turkish_gold_post",
                    return_value="TURKEY-GOLD",
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "build_iran_gold_post",
                    return_value="IRAN-GOLD",
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "build_hybrid_usdt_post",
                    return_value="USDT",
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "bank_fx_observations",
                    return_value=[],
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "fx_pulse_observations",
                    return_value=[],
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "turkey_gold_observations",
                    return_value=[],
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "iran_gold_observations",
                    return_value=[],
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "usdt_observations",
                    return_value=[],
                )
            )
            stack.enter_context(
                patch.object(
                    publish_channels,
                    "assess_post",
                    return_value=verified,
                )
            )
            stdout = stack.enter_context(
                patch("sys.stdout", new_callable=io.StringIO)
            )

            result = publish_channels.main()

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("BANK", output)
        self.assertIn("PULSE", output)
        self.assertIn("TURKEY-GOLD", output)
        self.assertIn("IRAN-GOLD", output)
        self.assertIn("USDT", output)


if __name__ == "__main__":
    unittest.main()
