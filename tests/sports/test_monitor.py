from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import requests

from sports_monitor.model import Product, money, canonical, normalize_sizes, qualifies, change_reason
from sports_monitor.parsing import documents, parse_product, discover, ParseError, running_shoe
from sports_monitor.state import State
from sports_monitor.telegram import batches, item, send, DeliveryError
from sports_monitor.network import Client, FetchError
from sports_monitor.runner import fetch_url, lock
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
        return (FIXTURES / (store + '.json')).read_text(encoding='utf-8')

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
