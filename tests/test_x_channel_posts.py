import contextlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'channel_split'))
from bank_compare import BankQuote, TARGETS, build_usd_comparison_post
from gold_prices import GoldQuote, GOLD_ASSETS, build_turkish_gold_post
from hybrid_usdt_compare import HybridUsdtQuote, TARGET_EXCHANGES, build_hybrid_usdt_post
from iran_fx import CURRENCY_ROWS, build_iran_fx_post
from iran_gold import IranGoldMarket, COIN_LABELS, build_iran_gold_post
from kiani_posts import (build_kiani_try_post, build_kiani_toman_receive_post,
                        build_kiani_try_receive_post, build_kiani_remittance_post)
from market_pulse import build_turkey_fx_pulse_post
from daily_market_digest import build_digest_post
from tests import test_channel_split_daily_market_digest as digest_tests
from x_channel_formats import POST_TYPES, GOLD_TYPES, render
from x_channel_daily import collect, deliver
from x_post_policy import WHATSAPP_TEXT, inspect_text, validate_text


def fixtures(multiplier=1):
    m = D(multiplier)
    rates = {k: D(v)*m for k, v in dict(buy_lira='4820', sell_lira='4680',
             buy_usdt='234000', sell_usdt='232000', lira_to_usdt='49', usdt_to_lira='48').items()}
    banks = [BankQuote(name, D('48.69')*m, D('48.71')*m) for name in TARGETS]
    gold = [GoldQuote(key, label, url, D('6717.34')*m, D('6723.63')*m)
            for key, label, url in GOLD_ASSETS]
    quotes = [HybridUsdtQuote(name, D(234349+i)*m,
              None if i in (3,5) else D(234301+i)*m, D('1.85'), 'direct')
              for i, name in enumerate(TARGET_EXCHANGES)]
    iran = IranGoldMarket({key: D('2364900000')*m for key in COIN_LABELS}, {},
                         D('237077000')*m, D('1026960000')*m)
    fx = {row[0]: D(235000)*m for row in CURRENCY_ROWS}
    return {
        'alanchande-usdt-exchanges': build_hybrid_usdt_post(quotes),
        'alanchande-iran-fx': build_iran_fx_post(fx, {key:D('1.51') for key in fx}),
        'kiani-hawala': build_kiani_remittance_post({c:D(229800)*m for c in 'USD EUR GBP CAD AUD SEK TRY'.split()}),
        'kiani-try': build_kiani_try_post(rates),
        'kiani-examples-reverse': build_kiani_toman_receive_post(rates),
        'kiani-examples': build_kiani_try_receive_post(rates),
        'alanchande-fx-pulse': build_turkey_fx_pulse_post(banks, banks),
        'alanchande-turkey-gold': build_turkish_gold_post(gold),
        'alanchande-iran-gold': build_iran_gold_post(iran),
        'bank-comparison': build_usd_comparison_post(banks),
        'alanchande-daily-digest': build_digest_post({k:v*m for k,v in digest_tests.DailyMarketDigestTests()._values().items()}),
    }


class XChannelTests(unittest.TestCase):
    def test_all_real_telegram_builders_have_valid_compact_views(self):
        sources = fixtures()
        self.assertEqual(set(sources), set(POST_TYPES))
        for post, source in sources.items():
            with self.subTest(post=post):
                text = render(post, source)
                result = inspect_text(text)
                self.assertLessEqual(result['weightedLength'], 280)
                self.assertTrue(result['valid'])
                self.assertFalse(result['urls'])
                self.assertEqual(text.count(WHATSAPP_TEXT), 0 if post in GOLD_TYPES else 1)
                self.assertNotIn('تومان مگر موارد دلاری', text)
                self.assertNotIn('<', text)

    def test_iran_fx_compact_view_keeps_currency_flags(self):
        source = fixtures()["alanchande-iran-fx"]
        text = render("alanchande-iran-fx", source)

        for expected in (
            "🇺🇸 USD",
            "🇪🇺 EUR",
            "🇬🇧 GBP",
            "🇹🇷 TRY",
            "🇰🇼 KWD",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_missing_rows_and_malformed_prices_fail_closed(self):
        sources = fixtures()
        with self.assertRaises(ValueError):
            render('alanchande-usdt-exchanges', sources['alanchande-usdt-exchanges'].replace('Wallex', 'Unknown'))
        with self.assertRaises(ValueError):
            render('bank-comparison', sources['bank-comparison'].replace('48.7100', 'oops'))

    def test_calculators_use_explicit_persian_payment_direction(self):
        sources = fixtures()
        forward = render('kiani-examples', sources['kiani-examples'])
        reverse = render('kiani-examples-reverse', sources['kiani-examples-reverse'])
        self.assertIn('دریافت ده هزار لیر 🔄 واریز 48.2 میلیون تومان', forward)
        self.assertIn('دریافت پنجاه هزار لیر 🔄 واریز 241 میلیون تومان', forward)
        self.assertIn('دریافت صد هزار لیر 🔄 واریز 482 میلیون تومان', forward)
        self.assertIn('دریافت پنجاه میلیون تومان 🔄 واریز 10,684 لیر', reverse)
        for text in (forward, reverse):
            self.assertNotIn('TL', text)
            self.assertNotIn('M', text)
            self.assertNotIn('←', text)
            self.assertEqual(text.count('دریافت'), 4)
            self.assertEqual(text.count('واریز'), 3)

    def test_larger_prices_never_escape_length_guard(self):
        for source_multiplier in (10, 1000000):
            for post, source in fixtures(source_multiplier).items():
                with self.subTest(post=post, multiplier=source_multiplier):
                    try:
                        text = render(post, source)
                    except ValueError as exc:
                        self.assertTrue(str(exc).startswith(('Invalid X post', 'Invalid price field')))
                    else:
                        self.assertLessEqual(inspect_text(text)['weightedLength'], 280)

    def test_exact_unicode_and_link_validation(self):
        self.assertEqual(inspect_text('🇹🇷')['weightedLength'], 2)
        self.assertEqual(inspect_text('👨‍👩‍👧‍👦')['weightedLength'], 2)
        self.assertEqual(inspect_text('e\u0301')['weightedLength'], 1)
        self.assertEqual(inspect_text('漢')['weightedLength'], 2)
        validate_text('a'*280)
        for text in ('a'*281, 'https://example.com', 'wa.me/905411603664', 'example.com', '\ufffe'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_text(text)

    def test_once_per_day_and_uncertain_send_is_not_retried(self):
        now = datetime(2026,9,25,12,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp)/'state.sqlite3')
            with patch('x_channel_daily.publish_to_x') as unused:
                calls = []
                def sender(text):
                    calls.append(text)
                    return {'data': {'id': '123'}}
                deliver('kiani-try', 'test', db, now=now, sender=sender)
                deliver('kiani-try', 'test', db, now=now, sender=sender)
                self.assertEqual(len(calls), 1)
                deliver('kiani-try', 'test', db, now=now+timedelta(days=1), sender=sender)
                self.assertEqual(len(calls), 2)
                def fail(text):
                    raise TimeoutError('ambiguous')
                with self.assertRaises(TimeoutError):
                    deliver('bank-comparison', 'test', db, now=now, sender=fail)
                deliver('bank-comparison', 'test', db, now=now, sender=sender)
                self.assertEqual(len(calls), 2)

    def test_dry_run_has_no_delivery_state_or_send(self):
        from x_channel_daily import main
        with tempfile.TemporaryDirectory() as tmp, patch('x_channel_daily.collect', return_value=fixtures()['kiani-try']), patch('x_channel_daily.deliver') as send:
            db = str(Path(tmp)/'state.sqlite3')
            with patch.object(sys, 'argv', ['x_channel_daily.py', '--post', 'kiani-try', '--dry-run', '--state-file', db]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            send.assert_not_called()
            self.assertFalse(Path(db).exists())

    def test_unverified_export_is_blocked(self):
        import subprocess
        result = subprocess.CompletedProcess([], 0, json.dumps({'post':'bank-comparison','verified':False,'text':'bad'}), '')
        with patch('x_channel_daily.subprocess.run', return_value=result), self.assertRaises(ValueError):
            collect('bank-comparison')

    def test_stale_hawala_snapshot_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'rates.json'
            path.write_text(json.dumps({'source':'kiani-hawala', 'generated_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(), 'rates':{}}))
            with self.assertRaises(ValueError):
                collect('kiani-hawala', path)


if __name__ == '__main__':
    unittest.main()
