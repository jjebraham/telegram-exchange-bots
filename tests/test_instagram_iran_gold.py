"""Offline gold publication checks. Synthetic inputs are never production quotes."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iran_gold_data import (ASSETS, SPEC, GoldError, TEHRAN, UTC, assess, coherent,
                           number, parse_tgju, parse_dolar, percent, validate, validate_url)
from instagram_iran_gold import already, check_changes, comparison, next_run, publish

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=TEHRAN).astimezone(UTC)
PRICES = dict(zip(SPEC, map(str, (266130000, 258055000, 140700000, 74140000, 38000000, 26449700, 114585000))))


def feeds():
    primary, secondary = {}, {}
    for key, price in PRICES.items():
        primary[key] = dict(price=price, original_rial=str(Decimal(price) * 10), unit='rial',
                            updated_at=(NOW - timedelta(minutes=2)).isoformat())
        secondary[key] = dict(price=price, bid=price, ask=price, unit='toman',
                              updated_at=(NOW - timedelta(minutes=1)).isoformat())
    return primary, secondary


def snapshot():
    primary, secondary = feeds()
    return dict(status='verified', timezone='Asia/Tehran', generated_at=NOW.isoformat(),
                primary=primary, secondary=secondary, rows=assess(primary, secondary, NOW))


def tgju_fixture():
    price = str(Decimal(PRICES['gold18']) * 10)
    fields = [('نرخ فعلی', price), ('بالاترین قیمت روز', str(Decimal(price) + 1000)),
              ('پایین ترین قیمت روز', str(Decimal(price) - 1000)), ('زمان ثبت آخرین نرخ', '09:58:00')]
    html = '<p>واحد پولی : ریال واحد حجمی : گرم</p><table>' + ''.join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in fields) + '</table>'
    data = {'data': [[price, price, price, price, '0', '0%', '2026/10/21', '1405/07/29']]}
    return html, data


def dolar_fixture():
    rates = {spec[4]: dict(buy=int(PRICES[spec[0]]), sell=int(PRICES[spec[0]])) for spec in ASSETS}
    rows = ''.join(f'<tr><td>{spec[3]}</td><td>{PRICES[spec[0]]}</td><td>{PRICES[spec[0]]}</td></tr>' for spec in ASSETS)
    obj = dict(rates=rates, initialIso='2026-10-21T06:29:00.000Z')
    return '<p>Gold prices in Toman. Last updated Oct 21, 2026, 6:29 AM</p><table>' + rows + '</table><script>self.__next_f.push(' + json.dumps([1, json.dumps(obj)]) + ')</script>'


class GoldChecks(unittest.TestCase):
    def test_complete_seven_price_board(self):
        self.assertEqual([r['id'] for r in assess(*feeds(), NOW)], list(SPEC))

    def test_stale_primary(self):
        a, b = feeds(); a['half']['updated_at'] = (NOW - timedelta(minutes=31)).isoformat()
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_stale_secondary(self):
        a, b = feeds(); b['half']['updated_at'] = (NOW - timedelta(days=1)).isoformat()
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_future_quote(self):
        a, b = feeds(); a['half']['updated_at'] = (NOW + timedelta(minutes=2)).isoformat()
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_missing_instrument_blocks_entire_post(self):
        a, b = feeds(); del a['mesghal']
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_invalid_numbers(self):
        for value in ('NaN', 'Infinity', '-1', '0', '12,34', True):
            with self.subTest(value=value), self.assertRaises(GoldError): number(value)

    def test_rial_toman_factor_ten(self):
        a, b = feeds(); a['gold18']['price'] = str(Decimal(a['gold18']['price']) * 10)
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_both_feeds_factor_ten(self):
        a, b = feeds()
        for rows in (a, b):
            for row in rows.values():
                for key in ('price', 'original_rial', 'bid', 'ask'):
                    if key in row: row[key] = str(Decimal(row[key]) * 10)
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_both_feeds_factor_one_tenth(self):
        a, b = feeds()
        for rows in (a, b):
            for row in rows.values():
                for key in ('price', 'original_rial', 'bid', 'ask'):
                    if key in row: row[key] = str(Decimal(row[key]) / 10)
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_provider_disagreement(self):
        a, b = feeds()
        for key in ('price', 'bid', 'ask'): b['emami'][key] = str(Decimal(b['emami'][key]) * Decimal('1.025'))
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_crossed_secondary(self):
        a, b = feeds(); b['emami']['bid'] = str(Decimal(b['emami']['ask']) + 100)
        with self.assertRaises(GoldError): assess(a, b, NOW)

    def test_incorrect_gram_mesghal_ratio(self):
        prices = dict(PRICES, mesghal='26449700')
        with self.assertRaises(GoldError): coherent(prices)

    def test_incorrect_coin_order(self):
        prices = dict(PRICES, quarter='160000000')
        with self.assertRaises(GoldError): coherent(prices)

    def test_large_move_requires_review(self):
        old = {k: str(Decimal(p) / Decimal('1.08')) for k, p in PRICES.items()}
        with self.assertRaises(GoldError): assess(*feeds(), NOW, old)

    def test_verified_snapshot_cannot_be_modified(self):
        value = snapshot(); value['rows'][0]['price'] = '123456789'
        with self.assertRaises(GoldError): validate(value, now=NOW)

    def test_layout_sample_never_qualifies(self):
        value = snapshot(); value['layout_sample'] = True
        with self.assertRaises(GoldError): validate(value, now=NOW)

    def test_collection_expires_before_meta_publish(self):
        value = snapshot()
        with self.assertRaises(GoldError): validate(value, publishing=True, now=NOW + timedelta(minutes=4))

    def test_time_window_rejects_late_publish(self):
        value = snapshot(); value['generated_at'] = (NOW + timedelta(hours=1)).isoformat()
        for rows in (value['primary'], value['secondary']):
            for row in rows.values(): row['updated_at'] = (NOW + timedelta(hours=1)).isoformat()
        with self.assertRaises(GoldError): validate(value, publishing=True, now=NOW + timedelta(hours=1))

    def test_tgju_quote_uses_original_dated_record_and_clock(self):
        value = parse_tgju(*tgju_fixture(), 'gold18', NOW)
        self.assertEqual(value['price'], PRICES['gold18'])
        self.assertEqual(value['updated_at'], (NOW - timedelta(minutes=2)).isoformat())

    def test_tgju_date_only_is_not_fresh(self):
        html, data = tgju_fixture(); html = html.replace('09:58:00', '۲۹ مهر')
        with self.assertRaises(GoldError) as caught: parse_tgju(html, data, 'gold18', NOW)
        self.assertEqual(caught.exception.code, 'stale')

    def test_tgju_yesterday_quote_rejected(self):
        html, data = tgju_fixture(); data['data'][0][6:] = ['2026/10/20', '1405/07/28']
        with self.assertRaises(GoldError): parse_tgju(html, data, 'gold18', NOW)

    def test_tgju_calendar_mismatch(self):
        html, data = tgju_fixture(); data['data'][0][7] = '1405/07/28'
        with self.assertRaises(GoldError): parse_tgju(html, data, 'gold18', NOW)

    def test_dolar_visible_and_structured_prices_match(self):
        value = parse_dolar(dolar_fixture(), NOW)
        self.assertEqual(set(value), set(SPEC))
        self.assertEqual(value['gold18']['price'], PRICES['gold18'])

    def test_dolar_visible_price_disagrees(self):
        html = dolar_fixture().replace('<td>266130000</td>', '<td>266130001</td>', 1)
        with self.assertRaises(GoldError): parse_dolar(html, NOW)

    def test_dolar_naive_timestamp_rejected(self):
        with self.assertRaises(GoldError): parse_dolar(dolar_fixture().replace('06:29:00.000Z', '06:29:00.000'), NOW)

    def test_no_missing_history_is_invented(self):
        self.assertIsNone(percent(PRICES['emami'], None))
        self.assertEqual(percent('110', '100'), '10.00')

    def test_fabricated_changes_are_rejected(self):
        con = sqlite3.connect(':memory:'); con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE gold_history(day,observed_at,prices_json,media_id)')
        value = snapshot(); value['rows'][0]['month'] = '12.53'
        try:
            with self.assertRaises(GoldError): check_changes(con, value)
        finally: con.close()

    def test_expiry_after_meta_preparation_never_publishes(self):
        con = sqlite3.connect(':memory:'); con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE gold_history(day,observed_at,prices_json,media_id)')
        con.execute('''CREATE TABLE instagram_news_publications(day PRIMARY KEY,status,started_at,
                    finished_at,container_id,media_id,manifest_json,error_type)''')
        value = snapshot()
        try:
            with patch('instagram_iran_gold.validate', side_effect=[None, GoldError('expired', 'stale')]), \
                 patch('instagram_iran_gold.helper') as helper, \
                 patch.dict('os.environ', INSTAGRAM_USER_ID='123', INSTAGRAM_ACCESS_TOKEN='synthetic-test-only'):
                helper.return_value._create_container.return_value = '123'
                with self.assertRaises(GoldError): publish(con, value, {'image_urls':['https://example.invalid/preview.jpg'],'caption':'test'}, Path('.'))
                helper.return_value._publish_container.assert_not_called()
                self.assertEqual(con.execute('SELECT status FROM instagram_news_publications').fetchone()[0], 'failed')
                self.assertEqual(con.execute('SELECT count(*) FROM gold_history').fetchone()[0], 0)
        finally: con.close()

    def test_duplicate_publication_block_and_missing_history(self):
        con = sqlite3.connect(':memory:'); con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE gold_history(day,observed_at,prices_json,media_id)')
        con.execute('CREATE TABLE instagram_news_publications(day,status,media_id)')
        try:
            self.assertEqual(comparison(con, NOW, 24), {})
            con.execute("INSERT INTO instagram_news_publications VALUES ('2026-10-21','published','123')")
            self.assertTrue(already(con, '2026-10-21'))
        finally: con.close()

    def test_uncertain_publication_is_not_retried(self):
        con = sqlite3.connect(':memory:'); con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE instagram_news_publications(day,status,media_id)')
        con.execute("INSERT INTO instagram_news_publications VALUES ('2026-10-21','needs_review',NULL)")
        try:
            with self.assertRaises(GoldError): already(con, '2026-10-21')
        finally: con.close()

    def test_tehran_ten_schedule(self):
        self.assertEqual(next_run(NOW - timedelta(minutes=1)), NOW.astimezone(TEHRAN))
        self.assertEqual(next_run(NOW + timedelta(minutes=1)), (NOW + timedelta(days=1)).astimezone(TEHRAN))

    def test_no_meta_call_for_blocked_board(self):
        con = sqlite3.connect(':memory:')
        with patch('instagram_iran_gold.helper') as graph:
            with self.assertRaises(GoldError): publish(con, {'status': 'blocked'}, {}, Path('.'))
            graph.assert_not_called()
        con.close()

    def test_only_reviewed_https_source_urls(self):
        for url in ('http://www.tgju.org/profile/sekee', 'https://evil.invalid/profile/sekee', 'https://www.tgju.org/profile/unknown'):
            with self.subTest(url=url), self.assertRaises(GoldError): validate_url(url)


if __name__ == '__main__':
    unittest.main(verbosity=1)
