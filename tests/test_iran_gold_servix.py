"""Offline synthetic Servix/consensus/date-scope checks; no real API credentials."""
from copy import deepcopy
from datetime import datetime, timedelta
from contextlib import nullcontext
from contextlib import redirect_stdout
import io
from decimal import Decimal
import json
from pathlib import Path
import sys
import runpy
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iran_gold_data import GoldError, SPEC, TEHRAN, UTC, validate
from iran_gold_quorum import assess
from iran_gold_servix import CODES, NoRedirect, SOURCE, get_json, parse, validate_quote

NOW = datetime(2026, 10, 23, 17, 0, tzinfo=TEHRAN).astimezone(UTC)
PRICES = dict(zip(SPEC, (274000000, 265000000, 144000000, 77000000, 39000000, 26900000, 116530000)))
DIGEST = 'a' * 64
MESSAGE = 'rateSurf healthStatus=DEGRADED. Excluded stale sources=0, outlier or conflicting sources=1'
ADMIN = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'deploy/instagram-iran-gold/activate_servix.py'))


def fixture():
    rows, metas = [], []
    for asset, code in CODES.items():
        value = PRICES[asset] * 10
        clock = (NOW - timedelta(minutes=2)).isoformat()
        rows.append(dict(code=code, quoteUnit='RLS', value=value, midPrice=value,
                         buyPrice=value, sellPrice=value, businessTime=clock))
        metas.append(dict(code=code, quoteUnit='RLS', providers=['SERVIX'], providerSupported=True,
            latestValueAvailable=True, latestValue=value, businessTime=clock, sourceTime=clock,
            insertTime=clock, qualityStatus='ACCEPTED_WITH_WARNINGS', qualityMessage=MESSAGE,
            availabilityStatus='FRESH', stale=False))
    return {'assets': metas, 'updatedAt': NOW.isoformat()}, rows


def parsed(catalog=None, current=None):
    a, b = fixture()
    return parse(a if catalog is None else catalog, b if current is None else current, NOW, DIGEST, DIGEST)


def providers(servix=None):
    result = dict(tgju={}, alanchand={}, dolarchand={}, servix=parsed()['quotes'] if servix is None else servix)
    for asset, value in PRICES.items():
        result['alanchand'][asset] = dict(price=str(value), original_rial=str(value * 10), unit='toman',
            updated_at=(NOW - timedelta(minutes=1)).isoformat(), source_url='https://alanchand.com/gold-price', page_hash=DIGEST)
        result['dolarchand'][asset] = dict(price=str(value), bid=str(value), ask=str(value), unit='toman',
            updated_at=(NOW - timedelta(minutes=1)).isoformat(), source_url='https://dolarchand.com/en/gold-silver', page_hash=DIGEST)
    return result


def snapshot():
    p = providers()
    return dict(schema_version=2, status='verified', timezone='Asia/Tehran', generated_at=NOW.isoformat(),
                providers=p, rows=assess(p, NOW))


class ServixChecks(unittest.TestCase):
    def test_complete_explicit_rial_board(self):
        q = parsed()['quotes']
        self.assertEqual(set(q), set(SPEC))
        self.assertEqual(q['gold18']['price'], str(PRICES['gold18']))
        json.dumps(q)  # Audits remain serializable even with exact numeric parsing.

    def test_midpoint_never_replaced_with_ask(self):
        a, b = fixture(); row = b[0]; value = Decimal(row['value'])
        row.update(buyPrice=str(value * Decimal('.998')), sellPrice=str(value * Decimal('1.002')))
        q = parsed(a, b)['quotes']['emami']
        self.assertEqual(q['price'], str(PRICES['emami']))
        self.assertNotEqual(q['price'], q['ask'])

    def test_gram_wide_spread_is_isolated(self):
        a, b = fixture(); row = next(r for r in b if r['code'] == CODES['gram_coin'])
        row.update(buyPrice=380000000, midPrice=385000000, value=385000000, sellPrice=390000000)
        next(m for m in a['assets'] if m['code'] == row['code'])['latestValue'] = row['value']
        result = parsed(a, b)
        self.assertEqual(len(result['quotes']), 6)
        self.assertEqual(result['rejected']['gram_coin']['code'], 'spread')
        rows = assess(providers(result['quotes']), NOW)
        gram = next(r for r in rows if r['id'] == 'gram_coin')
        self.assertEqual(gram['sources'], ['alanchand', 'dolarchand'])

    def test_missing_side_is_not_filled(self):
        a, b = fixture(); b[0]['buyPrice'] = None
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_crossed_sides(self):
        a, b = fixture(); b[0]['buyPrice'] += 1
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_incorrect_midpoint(self):
        a, b = fixture(); b[0]['midPrice'] += 1
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_non_rial_unit_not_guessed(self):
        a, b = fixture(); b[0]['quoteUnit'] = 'TOMAN'
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_fresh_catalog_generation_does_not_refresh_quote(self):
        a, b = fixture(); old = (NOW - timedelta(minutes=31)).isoformat()
        a['assets'][0]['businessTime'] = b[0]['businessTime'] = old
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_previous_tehran_day_rejected(self):
        a, b = fixture(); old = (NOW - timedelta(days=1)).isoformat()
        a['assets'][0]['businessTime'] = b[0]['businessTime'] = old
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_future_clock_rejected(self):
        a, b = fixture(); clock = (NOW + timedelta(minutes=2)).isoformat()
        a['assets'][0]['businessTime'] = b[0]['businessTime'] = clock
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_naive_clock_rejected(self):
        a, b = fixture(); clock = NOW.replace(tzinfo=None).isoformat()
        a['assets'][0]['businessTime'] = b[0]['businessTime'] = clock
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_catalog_and_quote_must_share_observation(self):
        a, b = fixture(); b[0]['businessTime'] = (NOW - timedelta(seconds=30)).isoformat()
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_catalog_value_cannot_be_from_other_observation(self):
        a, b = fixture(); a['assets'][0]['latestValue'] += 10
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_hard_quality_failure_rejected(self):
        a, b = fixture(); a['assets'][0]['qualityStatus'] = 'REJECTED'
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_unknown_warning_not_accepted(self):
        a, b = fixture(); a['assets'][0]['qualityMessage'] = 'Unreviewed provider warning'
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_healthy_quote_accepted(self):
        a, b = fixture(); a['assets'][0].update(qualityStatus='ACCEPTED', qualityMessage=None)
        self.assertIn('emami', parsed(a, b)['quotes'])

    def test_provider_stale_flag_rejected(self):
        a, b = fixture(); a['assets'][0]['stale'] = True
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_provider_coverage_and_availability_required(self):
        for key in ('providerSupported', 'latestValueAvailable'):
            a, b = fixture(); a['assets'][0][key] = False
            self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_duplicate_code_rejected(self):
        a, b = fixture(); b.append(deepcopy(b[0]))
        with self.assertRaises(GoldError): parsed(a, b)

    def test_unknown_provider_identity_rejected(self):
        a, b = fixture(); a['assets'][0]['providers'] = ['UNREVIEWED']
        self.assertNotIn('emami', parsed(a, b)['quotes'])

    def test_modified_audit_conversion_rejected(self):
        q = parsed()['quotes']['emami']; q['price'] = str(PRICES['emami'] * 10)
        with self.assertRaises(GoldError): validate_quote('emami', q, NOW)

    def test_source_url_evidence_required(self):
        q = parsed()['quotes']['emami']; q['source_url'] = 'https://example.invalid'
        with self.assertRaises(GoldError): validate_quote('emami', q, NOW)

    def test_servix_cannot_form_quorum_alone(self):
        with self.assertRaises(GoldError): assess({'servix': parsed()['quotes']}, NOW)

    def test_servix_is_never_displayed_source(self):
        rows = assess(providers(), NOW)
        self.assertTrue(all('servix' in r['sources'] for r in rows))
        self.assertTrue(all(r['selected_source'] != 'servix' for r in rows))

    def test_primary_plus_servix_can_corroborate(self):
        p = providers(); p['dolarchand'] = {}
        rows = assess(p, NOW)
        self.assertTrue(all(r['selected_source'] == 'alanchand' for r in rows))

    def test_servix_outage_preserves_primary_consensus(self):
        rows = assess(providers({}), NOW)
        self.assertTrue(all('servix' not in r['sources'] for r in rows))

    def test_servix_cannot_veto_unique_primary_consensus(self):
        p = providers()
        q = p['dolarchand']['emami']; q.update(price='275500000', bid='275500000', ask='275500000')
        s = p['servix']['emami']; s.update(price='277300000', bid='277300000', ask='277300000',
            original_rial='2773000000', mid_rial='2773000000', bid_rial='2773000000', ask_rial='2773000000')
        s['catalog_record']['latestValue'] = '2773000000'
        row = assess(p, NOW)[0]
        self.assertEqual(row['sources'], ['alanchand', 'dolarchand'])
        self.assertIn('servix', row['rejected_sources'])

    def test_servix_can_resolve_previously_ambiguous_primary_clusters(self):
        p = providers()
        for asset, value in PRICES.items():
            p['tgju'][asset] = dict(p['alanchand'][asset], unit='rial',
                source_url='https://www.tgju.org/profile/' + SPEC[asset][2])
        p['dolarchand']['emami'].update(price='276500000', bid='276500000', ask='276500000')
        p['tgju']['emami'].update(price='279000000', original_rial='2790000000')
        s = p['servix']['emami']; s.update(price='275000000', bid='275000000', ask='275000000',
            original_rial='2750000000', mid_rial='2750000000', bid_rial='2750000000', ask_rial='2750000000')
        s['catalog_record']['latestValue'] = '2750000000'
        self.assertEqual(assess(p, NOW)[0]['sources'], ['alanchand', 'dolarchand', 'servix'])

    def test_one_missing_consensus_still_blocks_whole_post(self):
        p = providers(); p['alanchand'].pop('gram_coin'); p['dolarchand'].pop('gram_coin')
        with self.assertRaises(GoldError): assess(p, NOW)

    def test_existing_disagreement_limit_not_relaxed(self):
        p = providers(); p['alanchand']['gold18']['price'] = '27500000'
        p['alanchand']['gold18']['original_rial'] = '275000000'; p['dolarchand'] = {}
        with self.assertRaises(GoldError): assess(p, NOW)

    def test_http_key_not_in_error_text(self):
        error = HTTPError('https://servix.cc/api/v1/assets/supported', 401, 'PRIVATE_FIXTURE_KEY', {}, None)
        with patch('iran_gold_servix.build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(GoldError) as caught: get_json('assets/supported', 'PRIVATE_FIXTURE_KEY')
            self.assertNotIn('PRIVATE_FIXTURE_KEY', str(caught.exception))

    def test_key_never_forwarded_to_redirect(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.invalid'))

    def test_unreviewed_endpoint_rejected(self):
        with self.assertRaises(GoldError): get_json('https://example.invalid', 'PRIVATE_FIXTURE_KEY')

    def test_normal_late_publication_remains_blocked(self):
        with self.assertRaises(GoldError): validate(snapshot(), publishing=True, now=NOW)

    def test_explicit_today_one_off_allowed(self):
        validate(snapshot(), publishing=True, now=NOW, authorized_day='2026-10-23')

    def test_one_off_other_day_rejected(self):
        with self.assertRaises(GoldError): validate(snapshot(), publishing=True, now=NOW, authorized_day='2026-10-24')

    def test_one_off_does_not_bypass_collection_expiry(self):
        with self.assertRaises(GoldError):
            validate(snapshot(), publishing=True, now=NOW + timedelta(minutes=4), authorized_day='2026-10-23')

    def test_one_off_does_not_bypass_source_tampering(self):
        s = snapshot(); s['rows'][0]['price'] = '1'
        with self.assertRaises(GoldError): validate(s, publishing=True, now=NOW, authorized_day='2026-10-23')

    def test_activation_requires_real_servix_contributions(self):
        with self.assertRaises(RuntimeError): ADMIN['require_servix']({'rows': []})
        with self.assertRaises(RuntimeError):
            ADMIN['require_servix']({'rows': [{'id': 'gold18', 'sources': ['servix']}] * 2})
        self.assertEqual(ADMIN['require_servix']({'rows': [
            {'id': 'gold18', 'sources': ['servix', 'alanchand']},
            {'id': 'mesghal', 'sources': ['servix', 'dolarchand']}]}), ['gold18', 'mesghal'])

    def test_invalid_key_preflight_does_not_save_secret(self):
        fn = ADMIN['configure_key']; path = MagicMock()
        path.exists.return_value = path.is_symlink.return_value = False
        with patch('iran_gold_servix.KEY_FILE', path), patch('getpass.getpass', return_value='SYNTHETIC_TEST_KEY'), \
             patch('iran_gold_servix.collect', return_value={'quotes': {}, 'rejected': {}}), \
             patch.dict(fn.__globals__, {'atomic': MagicMock()}) as _:
            writer = fn.__globals__['atomic']
            with self.assertRaises(RuntimeError): fn(Path('/fixture'))
            writer.assert_not_called()

    def test_verified_key_saved_private_only(self):
        fn = ADMIN['configure_key']; path = MagicMock(); writer = MagicMock()
        path.exists.return_value = path.is_symlink.return_value = False
        with patch('iran_gold_servix.KEY_FILE', path), patch('getpass.getpass', return_value='SYNTHETIC_TEST_KEY'), \
             patch('iran_gold_servix.collect', return_value={'quotes': {'gold18': {}, 'mesghal': {}}, 'rejected': {}}), \
             patch('instagram_iran_gold.locked', return_value=nullcontext()), \
             patch.dict(fn.__globals__, {'atomic': writer}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(fn(Path('/fixture')), 0)
            writer.assert_called_once_with(path, b'SYNTHETIC_TEST_KEY\n', 0o600)
            self.assertNotIn('SYNTHETIC_TEST_KEY', output.getvalue())

    def test_existing_key_reused_without_prompt_or_rewrite(self):
        fn = ADMIN['configure_key']; path = MagicMock(); writer = MagicMock()
        path.exists.return_value = True
        with patch('iran_gold_servix.KEY_FILE', path), patch('getpass.getpass') as prompt, \
             patch('iran_gold_servix.load_key', return_value='SYNTHETIC_TEST_KEY'), \
             patch('iran_gold_servix.collect', return_value={'quotes': {'gold18': {}, 'mesghal': {}}, 'rejected': {}}), \
             patch('instagram_iran_gold.locked', return_value=nullcontext()), \
             patch.dict(fn.__globals__, {'atomic': writer, 'owned': lambda _: b'SYNTHETIC_TEST_KEY\n'}), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(fn(Path('/fixture')), 0)
            prompt.assert_not_called(); writer.assert_not_called()

    def test_post_driver_rejects_other_day_without_launch(self):
        fn = ADMIN['post_today']; clock = SimpleNamespace(now=lambda tz: NOW.astimezone(tz))
        with patch.dict(fn.__globals__, {'datetime': clock}), patch('subprocess.run') as launch:
            with self.assertRaises(RuntimeError): fn(Path('/fixture'), Path('/runtime'), 'a'*40, '2026-10-24')
            launch.assert_not_called()

    def test_post_driver_requires_reviewed_active_revision(self):
        fn = ADMIN['post_today']; clock = SimpleNamespace(now=lambda tz: NOW.astimezone(tz))
        with patch.dict(fn.__globals__, {'datetime': clock, 'owned': lambda _: b'{"revision":"wrong"}'}), \
             patch('subprocess.run') as launch:
            with self.assertRaises(RuntimeError): fn(Path('/fixture'), Path('/runtime'), 'a'*40, '2026-10-23')
            launch.assert_not_called()

    def test_duplicate_one_off_never_contacts_meta(self):
        from instagram_iran_gold import publish
        con = sqlite3.connect(':memory:'); con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE instagram_news_publications(day,status,media_id)')
        con.execute("INSERT INTO instagram_news_publications VALUES ('2026-10-23','published','123')")
        con.execute('CREATE TABLE gold_history(day,prices_json)')
        try:
            with patch('instagram_iran_gold.validate'), patch('instagram_iran_gold.check_changes'), \
                 patch('instagram_iran_gold.helper') as graph:
                publish(con, snapshot(), {}, Path('/fixture'), authorized_day='2026-10-23')
                graph.assert_not_called()
        finally:
            con.close()


if __name__ == '__main__':
    unittest.main(verbosity=1)
