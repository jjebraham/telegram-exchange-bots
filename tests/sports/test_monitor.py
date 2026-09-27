from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock, MagicMock
import requests

from sports_monitor.model import Product, money, canonical, normalize_sizes, qualifies, change_reason
from sports_monitor.parsing import documents, parse_product, discover, ParseError, running_shoe
from sports_monitor.state import State
from sports_monitor.telegram import batches, item, send, DeliveryError
from sports_monitor.network import Client, FetchError
from sports_monitor.runner import fetch_url, lock, scan_store, run
from sports_monitor.stores import STORES

NOW = 1_790_443_000
FIXTURES = Path(__file__).parent / 'fixtures'


def product(**kwargs):
    return replace(Product('yali', 'JQ2941-E', 'adidas Ultraboost', 100000, 50000,
                           'https://www.yalispor.com.tr/urun/test', ('42',), NOW, running_shoe=True), **kwargs)


class PriceTests(unittest.TestCase):
    def test_turkish_price(self):
        self.assertEqual(money('13.799,50 TL', turkish=True), 1379950)
        self.assertEqual(money('6.899,50', turkish=True), 689950)

    def test_json_decimal(self):
        self.assertEqual(money('6899.50'), 689950)

    def test_bad_prices(self):
        for value in ('NaN', 'Infinity', '-5', ''):
            with self.assertRaises(ValueError): money(value)
        with self.assertRaises(ValueError): product(sale=0)
        with self.assertRaises(ValueError): product(sale=100001)

    def test_threshold(self):
        self.assertTrue(qualifies(product(sale=65000)))
        self.assertFalse(qualifies(product(sale=65001)))
        self.assertFalse(qualifies(product(sizes=())))

    def test_strong_moderate_needs_history(self):
        p = product(sale=70000)
        self.assertFalse(qualifies(p))
        self.assertFalse(qualifies(p, 80000, 2))
        self.assertTrue(qualifies(p, 80000, 3))
        self.assertFalse(qualifies(p, 75000, 3))
        self.assertFalse(qualifies(product(sale=76000), 90000, 10))

    def test_url_and_sizes(self):
        self.assertEqual(canonical('https://example.com/p/?utm_source=x#s'), 'https://example.com/p')
        self.assertEqual(normalize_sizes(['42,5', '42.5', '40']), ('40', '42.5'))
        with self.assertRaises(ValueError): canonical('javascript:alert(1)')


class ParserTests(unittest.TestCase):
    def fixture(self, store):
        path = FIXTURES / store
        if not path.suffix:
            path = path.with_suffix('.json')
        return path.read_text(encoding='utf-8')

    def test_live_akinon_fixtures(self):
        expected = {'barcin': ('40', 479890), 'superstep': ('36', 519900),
                    'sporjinal': ('M', 99900), 'sportive': ('37', 229990)}
        for key, (size, _) in expected.items():
            with self.subTest(key=key):
                text = self.fixture(key)
                data = json.loads(text)
                url = next(s.root for s in STORES if s.key == key) + data['product']['absolute_url']
                p = parse_product(key, url, text, NOW)
                self.assertIn(size, p.sizes)
                self.assertEqual(p.sale, money(data['product']['price']))
                self.assertEqual(p.original, money(data['product']['retail_price']))

    def test_out_of_stock_excluded(self):
        text = self.fixture('barcin'); data = json.loads(text)
        p = parse_product('barcin', 'https://www.barcin.com/item/', text, NOW)
        self.assertNotIn('39', p.sizes)
        for o in data['variants'][0]['options']:
            o['in_stock'] = False
        self.assertEqual(parse_product('barcin', p.url, json.dumps(data), NOW).sizes, ())

    def test_unknown_stock_is_error(self):
        data = json.loads(self.fixture('barcin'))
        del data['variants'][0]['options'][0]['in_stock']
        with self.assertRaises(ParseError): parse_product('barcin', 'https://www.barcin.com/item', json.dumps(data), NOW)

    def test_price_specific_sizes(self):
        data = json.loads(self.fixture('sporjinal'))
        o = next(o for o in data['variants'][0]['options'] if o['in_stock'])
        label = o['label']; o['product']['price'] = '9999'
        p = parse_product('sporjinal', 'https://www.sporjinal.com/item', json.dumps(data), NOW)
        self.assertNotIn(label, p.sizes)

    def test_koray_barcode_stock(self):
        p = parse_product('koray', 'https://www.korayspor.com/merrell-ayakkabi-outdoor-ayakkabilari-moab-speed-2-gtx-j037513-10010', self.fixture('koray'), NOW)
        self.assertIn('41.5', p.sizes)
        self.assertNotIn('50', p.sizes)
        self.assertEqual(p.sale, 769993)

    def test_sneaks_quantity(self):
        p = parse_product('sneaks', 'https://www.sneaksup.com/adidas-samba-og-ig9030-001-sneaker-p-139139', self.fixture('sneaks'), NOW)
        self.assertEqual(p.sizes, ('39.5', '40', '40.5'))

    def test_yali_flags(self):
        p = parse_product('yali', 'https://www.yalispor.com.tr/urun/adidas-ultraboost-5-strung-erkek-spor-ayakkabi-siyah', self.fixture('yali'), NOW)
        self.assertEqual(p.sizes, ('42.5',))
        self.assertEqual(p.discount, 50)
        self.assertTrue(p.running_shoe)

    def test_running_shoe_category_and_models(self):
        self.assertTrue(running_shoe('adidas Supernova Rise Erkek Spor Ayakkabı', ['Koşu Ayakkabısı']))
        self.assertTrue(running_shoe('adidas Ultraboost 5 Erkek Spor Ayakkabı'))
        self.assertTrue(running_shoe('Nike Pegasus 41 Erkek Spor Ayakkabı'))
        self.assertTrue(running_shoe('ASICS Gel Nimbus 27 Kadın Spor Ayakkabı'))
        self.assertFalse(running_shoe('Nike Pegasus Running Ceket', ['Koşu']))
        self.assertFalse(running_shoe('adidas Ultraboost Sweatshirt', ['Running']))
        self.assertFalse(running_shoe('Nike Dunk Low Retro Erkek Spor Ayakkabı', ['Basketbol']))
        self.assertFalse(running_shoe('adidas Samba OG Unisex Sneaker', ['Lifestyle']))

    def test_running_only_applies_to_both_discount_tiers(self):
        non_running = product(running_shoe=False)
        self.assertFalse(qualifies(non_running))
        self.assertFalse(qualifies(product(running_shoe=False, sale=70000), 90000, 10))

    def test_block_page_fails_closed(self):
        for store in STORES:
            with self.assertRaises(ParseError): parse_product(store.key, store.root+'/p', '<html>Access Denied</html>', NOW)

    def test_flight_split_and_length_prefixed_text(self):
        long_text = 'İndirim\nürün'
        raw = '1:T' + format(len(long_text.encode()), 'x') + ',' + long_text + '2:{"product":{"name":"$1","price":5}}\n'
        html = ''.join('<script>self.__next_f.push('+json.dumps([1, part])+')</script>' for part in (raw[:20], raw[20:]))
        _, docs = documents(html)
        self.assertEqual(docs[0]['product']['name'], long_text)

    def test_no_javascript_execution(self):
        _, docs = documents('<script>self.__next_f.push([1,evil()])</script>')
        self.assertEqual(docs, [])

    def test_discovery_pagination_and_host(self):
        data = {'products': [{'name':'x','retail_price':'10','absolute_url':'/p/'},
                              {'name':'bad','retail_price':'10','absolute_url':'https://evil.example/p'}],
                'pagination': {'current_page': 1, 'num_pages': 2}}
        urls, pages = discover('barcin', 'https://www.barcin.com/outlet/?format=json', json.dumps(data))
        self.assertEqual(urls, ['https://www.barcin.com/p'])
        self.assertEqual(pages, ['https://www.barcin.com/outlet/?format=json&page=2'])

    def test_recommendation_is_not_current_product(self):
        data = json.loads(self.fixture('barcin'))
        html = '<script type="application/json">'+json.dumps(data)+'</script>'
        with self.assertRaises(ParseError): parse_product('barcin', 'https://www.barcin.com/unrelated', html, NOW)


class StateTests(unittest.TestCase):
    def setUp(self): self.state = State(':memory:')
    def tearDown(self): self.state.close()
    def posted(self, p=None):
        p = p or product()
        batch = self.state.reserve('@test', 'text', [p])
        self.state.delivered(batch, 123, NOW)
        return p

    def test_duplicate_after_success(self):
        p = product()
        self.assertEqual(self.state.reason(p, '@test', NOW), 'new')
        self.posted(p)
        self.assertIsNone(self.state.reason(p, '@test', NOW + 100000))

    def test_destinations_independent(self):
        self.posted()
        self.assertEqual(self.state.reason(product(), '@other', NOW), 'new')

    def test_meaningful_price_drop(self):
        self.posted(product(sale=60000))
        self.assertIsNone(self.state.reason(product(sale=57500), '@test', NOW+1))
        self.assertEqual(self.state.reason(product(sale=50000), '@test', NOW+1), 'price_drop')

    def test_cumulative_drop_uses_posted_baseline(self):
        self.posted(product(sale=60000))
        self.state.observe(product(sale=55000))
        self.assertEqual(self.state.reason(product(sale=50000), '@test', NOW+100), 'price_drop')

    def test_size_change_cooldown(self):
        self.posted()
        current = product(sizes=('42','43'))
        self.assertIsNone(self.state.reason(current, '@test', NOW+100))
        self.assertEqual(self.state.reason(current, '@test', NOW+86401), 'sizes')

    def test_size_removal_no_repost(self):
        self.posted(product(sizes=('42','43','44')))
        self.assertIsNone(self.state.reason(product(sizes=('42','43')), '@test', NOW+86401))

    def test_restock_retained_across_cooldown(self):
        self.posted()
        self.state.observe(product(sizes=(), observed_at=NOW+100))
        self.state.observe(product(observed_at=NOW+200))
        self.assertEqual(self.state.reason(product(), '@test', NOW+86401), 'restock')

    def test_ambiguous_delivery_not_retried(self):
        batch = self.state.reserve('@test', 'text', [product()])
        self.state.failed(batch, True)
        self.assertIsNone(self.state.reason(product(), '@test', NOW))
        self.state.resolve(batch)
        self.assertEqual(self.state.reason(product(), '@test', NOW), 'new')

    def test_crash_after_send_is_quarantined(self):
        batch = self.state.reserve('@test', 'text', [product()])
        self.assertIsNone(self.state.reason(product(), '@test', NOW))
        self.state.resolve(batch, 456)
        self.assertIsNone(self.state.reason(product(), '@test', NOW+90000))

    def test_definite_rejection_can_retry(self):
        batch = self.state.reserve('@test', 'text', [product()])
        self.state.failed(batch, False)
        self.assertEqual(self.state.reason(product(), '@test', NOW), 'new')

    def test_history_excludes_current_and_old(self):
        self.state.observe(product(observed_at=NOW-31*86400))
        self.state.observe(product(observed_at=NOW-1))
        self.state.observe(product(observed_at=NOW))
        self.assertEqual(self.state.history(product(), NOW), (50000, 1))

    def test_legacy_ayakapp_rows_do_not_qualify_or_drive_repost_history(self):
        legacy = product(store='barcin', url='https://www.barcin.com/shoe',
                         original=100000, sale=80000, source='ayakapp',
                         verify_url='https://ayakapp.com/urunler/shoe')
        for offset, sale in enumerate((80000, 85000, 90000), start=1):
            self.state.observe(replace(legacy, sale=sale, observed_at=NOW-offset))
        current = replace(legacy, sale=70000, observed_at=NOW, source='retailer',
                          verify_url=None)
        self.assertEqual(self.state.history(current, NOW), (None, 0))
        self.assertIsNone(self.state.previous(current.key))
        self.assertIsNone(self.state.reason(current, '@test', NOW))
        # Retain legacy URLs for discovery/deduplication so migration does not
        # discard product identity history.
        self.assertIn(legacy.url, self.state.known_urls('barcin'))

    def test_legacy_ayakapp_stock_does_not_trigger_restock_repost(self):
        legacy = product(source='ayakapp', verify_url='https://ayakapp.com/urunler/shoe',
                         sizes=('40', '41'))
        self.posted(legacy)
        self.state.observe(replace(legacy, sizes=(), observed_at=NOW+1))
        current = replace(legacy, source='retailer', verify_url=None,
                          sizes=('40', '41', '42'), observed_at=NOW+86401)
        self.assertIsNone(self.state.reason(current, '@test', NOW+86401))

    def test_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d)/'state.db')
            s = State(path); b=s.reserve('@test','text',[product()]);s.delivered(b,1,NOW);s.close()
            s=State(path)
            self.assertIsNone(s.reason(product(),'@test',NOW+1));s.close()


class TelegramTests(unittest.TestCase):
    def test_persian_links_sizes_no_promo(self):
        text = item(product(name='A & <B>'), 'new')
        self.assertIn('A &amp; &lt;B&gt;', text)
        self.assertIn('سایزهای موجود: 42', text)
        self.assertIn('href="https://www.yalispor.com.tr/urun/test"', text)
        self.assertIn('۵۰٪', text)
        self.assertNotIn('rundiscountbot', text)
        self.assertLess(text.index('سایزهای'), text.index('🏪'))

    def test_legacy_third_party_rows_load_but_are_never_formatted(self):
        legacy = product(source='ayakapp', verify_url='https://ayakapp.com/urunler/x')
        self.assertEqual(Product.loads(legacy.dumps()).source, 'ayakapp')
        with self.assertRaises(ValueError):
            item(legacy, 'new')
        self.assertNotIn('Ayakapp', item(product(), 'new'))

    def test_discount_percentage_is_rounded_to_match_store_badge(self):
        text = item(product(original=849900, sale=399900), 'new')
        self.assertIn('۵۳٪', text)

    def test_group_and_length(self):
        deals = [(product(sku=str(i),name='x'*180), 'new') for i in range(20)]
        groups=list(batches(deals,7))
        self.assertEqual(sum(len(ps) for _,ps in groups),20)
        for text,ps in groups:
            self.assertLessEqual(len(ps),7)
            self.assertLessEqual(len(text.encode('utf-16-le'))//2,3900)

    def test_empty_no_message(self): self.assertEqual(list(batches([])),[])

    @patch('sports_monitor.telegram.requests.post')
    def test_success_id_and_html(self, post):
        post.return_value=Mock(status_code=200,json=lambda:{'ok':True,'result':{'message_id':55}})
        self.assertEqual(send('secret','@test','text'),55)
        self.assertEqual(post.call_args.kwargs['json']['parse_mode'],'HTML')

    @patch('sports_monitor.telegram.requests.post',side_effect=requests.Timeout('contains-secret'))
    def test_timeout_no_retry_no_secret(self, post):
        with self.assertRaises(DeliveryError) as caught: send('secret','@test','x')
        self.assertTrue(caught.exception.ambiguous)
        self.assertNotIn('contains-secret',str(caught.exception))
        self.assertEqual(post.call_count,1)

    @patch('sports_monitor.telegram.requests.post')
    def test_rejected_delivery(self, post):
        post.return_value=Mock(status_code=429,json=lambda:{'ok':False})
        with self.assertRaises(DeliveryError) as caught: send('secret','@test','x')
        self.assertFalse(caught.exception.ambiguous)


class RuntimeTests(unittest.TestCase):
    def test_all_eight_stores(self): self.assertEqual(len(STORES),8)

    def test_format_keeps_page(self):
        self.assertEqual(fetch_url(STORES[0], 'https://www.barcin.com/outlet/?page=2'), 'https://www.barcin.com/outlet/?page=2&format=json')

    def store(self, key):
        return next(s for s in STORES if s.key == key)

    def test_403_challenge_is_blocked_with_no_fallback(self):
        primary = Mock()
        primary.get.side_effect = FetchError('HTTP 403 (Cloudflare challenge)', 403, True)
        with patch('sports_monitor.runner.Client', return_value=primary) as client:
            products, report = scan_store(self.store('sneaks'), [], 2, 10)
        self.assertEqual(products, [])
        self.assertEqual(client.call_count, 1)  # no second client, no other host
        self.assertEqual(primary.get.call_count, 1)
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(report['errors'][0]['access_blocked'])
        self.assertTrue(report['errors'][0]['challenge'])
        self.assertNotIn('data_source', report)

    def test_non_403_listing_error_is_degraded_not_blocked(self):
        primary = Mock()
        primary.get.side_effect = FetchError('HTTP 503', 503)
        with patch('sports_monitor.runner.Client', return_value=primary) as client:
            products, report = scan_store(self.store('adidas'), [], 2, 10)
        self.assertEqual(products, [])
        self.assertEqual(client.call_count, 1)
        self.assertEqual(report['status'], 'degraded')

    def test_block_during_product_fetch_stops_the_store(self):
        primary = Mock()
        primary.get.side_effect = [('https://www.sneaksup.com/sezon-sonu-indirimi', ''),
                                   FetchError('HTTP 403', 403)]
        links = ['https://www.sneaksup.com/a-p-1', 'https://www.sneaksup.com/b-p-2',
                 'https://www.sneaksup.com/c-p-3']
        with patch('sports_monitor.runner.Client', return_value=primary), \
             patch('sports_monitor.runner.discover', return_value=(links, [])):
            products, report = scan_store(self.store('sneaks'), [], 2, 10)
        self.assertEqual(primary.get.call_count, 2)  # listing + first product only
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(report['limited'])

    def test_yali_is_disabled_and_never_fetched(self):
        yali = self.store('yali')
        self.assertFalse(yali.enabled)
        self.assertTrue(yali.disabled_reason)
        with patch('sports_monitor.runner.Client') as client:
            products, report = scan_store(yali, [], 2, 10)
        client.assert_not_called()
        self.assertEqual((products, report['status']), ([], 'disabled'))

    def test_only_yali_is_disabled(self):
        self.assertEqual([s.key for s in STORES if not s.enabled], ['yali'])

    def test_run_reports_disabled_store_without_fetching_or_degrading(self):
        with tempfile.TemporaryDirectory() as d, patch('sports_monitor.runner.Client') as client:
            args = SimpleNamespace(publish=False, db=str(Path(d) / 'db.sqlite3'),
                                   report=str(Path(d) / 'report.json'), stores=['yali'],
                                   max_pages=2, max_products=10, top=10, group_size=7)
            self.assertEqual(run(args), 0)
            report = json.loads(Path(args.report).read_text(encoding='utf-8'))
        client.assert_not_called()
        self.assertEqual(report['stores'][0]['status'], 'disabled')
        self.assertEqual(report['messages'], [])

    def test_client_detects_cloudflare_challenge_without_retry(self):
        for status in (200, 403):
            with self.subTest(status=status):
                c = Client('https://www.sneaksup.com', delay=0)
                response = MagicMock(status_code=status, headers={'cf-mitigated': 'challenge', 'server': 'cloudflare'})
                response.__enter__.return_value = response
                with patch.object(c.session, 'get', return_value=response) as get:
                    with self.assertRaises(FetchError) as caught:
                        c.get('https://www.sneaksup.com/sezon-sonu-indirimi')
                self.assertEqual(get.call_count, 1)
                self.assertEqual(caught.exception.status, status)
                self.assertTrue(caught.exception.challenge)
                self.assertTrue(caught.exception.access_blocked)
                c.session.close()

    def test_scan_blocked_mid_product_fetch_has_no_finalist_rechecks(self):
        first = product(store='sneaks', sku='one', url='https://www.sneaksup.com/one')
        state = Mock()
        state.known_urls.return_value = []
        state.reason.return_value = 'new'
        blocked_report = {'store': 'sneaks', 'status': 'blocked', 'errors': [],
                          'limited': True, 'listing_pages': 1, 'discovered': 3, 'parsed': 1}
        with tempfile.TemporaryDirectory() as d, \
                patch('sports_monitor.runner.State', return_value=state), \
                patch('sports_monitor.runner.scan_store', return_value=([first], blocked_report)), \
                patch('sports_monitor.runner.Client') as client:
            args = SimpleNamespace(publish=False, db=str(Path(d) / 'db.sqlite3'),
                                   report=str(Path(d) / 'report.json'), stores=['sneaks'],
                                   max_pages=2, max_products=10, top=10, group_size=7)
            self.assertEqual(run(args), 2)
            report = json.loads(Path(args.report).read_text(encoding='utf-8'))
        client.assert_not_called()
        state.reason.assert_not_called()
        state.observe.assert_not_called()
        self.assertEqual(report['eligible'], 0)
        self.assertEqual(report['selected'], 0)
        self.assertEqual(report['stores'][0]['status'], 'blocked')

    def test_recheck_block_stops_later_requests_and_discards_store_finalists(self):
        products = [product(store='sneaks', sku=str(n),
                            url=f'https://www.sneaksup.com/product-{n}') for n in range(3)]
        state = Mock()
        state.known_urls.return_value = []
        state.reason.return_value = 'new'
        first_client = Mock()
        first_client.get.return_value = (products[0].url, '<html/>')
        second_client = Mock()
        second_client.get.side_effect = FetchError('HTTP 403', 403)
        clients = [first_client, second_client]
        store_report = {'store': 'sneaks', 'status': 'ok', 'errors': [], 'limited': False,
                        'listing_pages': 1, 'discovered': 3, 'parsed': 3}
        with tempfile.TemporaryDirectory() as d, \
                patch('sports_monitor.runner.State', return_value=state), \
                patch('sports_monitor.runner.scan_store', return_value=(products, store_report)), \
                patch('sports_monitor.runner.Client', side_effect=clients) as client, \
                patch('sports_monitor.runner.parse_product', return_value=products[0]):
            args = SimpleNamespace(publish=False, db=str(Path(d) / 'db.sqlite3'),
                                   report=str(Path(d) / 'report.json'), stores=['sneaks'],
                                   max_pages=2, max_products=10, top=10, group_size=7)
            self.assertEqual(run(args), 2)
            report = json.loads(Path(args.report).read_text(encoding='utf-8'))
        self.assertEqual(client.call_count, 2)
        self.assertEqual(first_client.get.call_count, 1)
        self.assertEqual(second_client.get.call_count, 1)
        self.assertEqual(report['stores'][0]['status'], 'blocked')
        self.assertEqual(report['selected'], 0)
        self.assertTrue(report['recheck_errors'][0]['access_blocked'])

    def test_cross_host_not_fetched(self):
        c=Client('https://www.barcin.com',delay=0)
        with patch.object(c.session,'get') as get:
            with self.assertRaises(FetchError):c.get('https://evil.example/')
            get.assert_not_called()
        c.session.close()

    def test_lock_release(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'lock')
            with lock(path): pass
            with lock(path): pass


if __name__ == '__main__': unittest.main()
