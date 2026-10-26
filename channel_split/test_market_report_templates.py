"""Contract, asset, timezone, and browser checks for the four reference boards."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import hashlib
import os
import re
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_images import html_for_post, render_png, _fa_num
from market_report_templates import (CURRENCY_FLAG_CODES, CURRENCY_ORDER, ARTBOARDS,
    GOLD_COINS, GOLD_BARS, flag_emoji, parse_iran_fx, parse_iran_gold,
    parse_turkey_gold, parse_pulse)
from test_market_images import SAMPLES, SAMPLE_TIMES, FX_SAMPLE_ROWS


def extended_period_samples():
    gold=SAMPLES['iran-gold'].replace('\n','\n💰 <b>Δ24H / Δ1M</b>\n',1)
    gold=re.sub(r'(<code>[^<]+</code>\s*)([^\n]+)',lambda m:m.group(1)+'— / '+m.group(2),gold)
    turkey=SAMPLES['turkey-gold'].replace('BUY     Δ24H','BUY     Δ24H Δ1M')
    turkey=re.sub(r'(?m)^(🌕(?:GRAM|CEYREK|YARIM|TAM)[^\n<]+)',lambda m:m.group(1)+' +5.67%',turkey)
    pulse=SAMPLES['fx-pulse'].replace('RATE Δ24H','RATE Δ24H Δ1M').replace('49.7900 0.00%','49.7900 — +2.12%').replace('55.5750 -0.26%','55.5750 -0.26% +0.19%')
    return {'iran-gold':gold,'turkey-gold':turkey,'fx-pulse':pulse}


class ReportTests(unittest.TestCase):
    def test_iran_fx_image_keeps_all_rates_and_moves_periods_to_text(self):
        html=html_for_post('iran-fx',SAMPLES['iran-fx'],now=SAMPLE_TIMES['iran-fx'])
        self.assertNotIn('data-period=',html)
        rendered=re.findall(r'<tr data-code="([A-Z]+)">(.*?)</tr>',html)
        self.assertEqual(len(rendered),25)
        for (code,body),expected in zip(rendered,FX_SAMPLE_ROWS):
            self.assertEqual(code,expected[0])
            self.assertEqual(body.count('<td>'),2)
            self.assertIn(f'data-value="{expected[1]}"',body)
            self.assertIn(_fa_num(expected[1]),body)

    def test_extended_gold_periods_keep_monthly_values_out_of_daily_column(self):
        sample=extended_period_samples()['iran-gold']
        rows=parse_iran_gold(sample)
        self.assertEqual((rows[0].day,rows[0].month),('—','+10.19%'))
        self.assertEqual((rows[-1].day,rows[-1].month),('—','+8.17%'))
        html=html_for_post('iran-gold',sample,now=SAMPLE_TIMES['iran-gold'])
        self.assertEqual(html.count('data-period="24h" data-value="—"'),7)
        self.assertIn('data-period="1m" data-value="+10.19%"',html)

    def test_extended_turkish_gold_and_pulse_fields_are_preserved(self):
        samples=extended_period_samples()
        gold=parse_turkey_gold(samples['turkey-gold'])
        self.assertEqual((gold[1].sell,gold[1].buy,gold[1].day,gold[1].month),('10,560.44','10,322.22','-3.49%','+5.67%'))
        pulse=parse_pulse(samples['fx-pulse'])
        self.assertEqual((pulse[0].rate,pulse[0].day,pulse[0].month),('49.7900','—','+2.12%'))
        self.assertEqual((pulse[1].day,pulse[1].month),('-0.26%','+0.19%'))
        for kind in ('turkey-gold','fx-pulse'):
            html=html_for_post(kind,samples[kind],now=SAMPLE_TIMES[kind])
            expected='+5.67%' if kind=='turkey-gold' else '+2.12%'
            self.assertIn(f'data-period="1m" data-value="{expected}"',html)

    def test_period_header_and_field_count_must_agree(self):
        for kind,sample in extended_period_samples().items():
            for corrupt in (sample.replace('Δ1M','Δ7D'),sample.replace('Δ24H','Δ1M').replace('Δ1M / Δ1M','Δ1M / Δ24H'),
                            sample.replace('Δ1M','').replace('Δ24H /','Δ24H')):
                with self.subTest(kind=kind),self.assertRaises(ValueError):
                    html_for_post(kind,corrupt,now=SAMPLE_TIMES[kind])

    def test_extended_period_browser_outputs(self):
        if os.environ.get('RENDER_PNG_TESTS')!='1':
            self.skipTest('Enable RENDER_PNG_TESTS=1 for extended-schema screenshots')
        with tempfile.TemporaryDirectory() as directory:
            for kind,sample in extended_period_samples().items():
                with self.subTest(kind=kind):
                    target=render_png(kind,sample,Path(directory)/(kind+'.png'),now=SAMPLE_TIMES[kind])
                    self.assertEqual(struct.unpack('>II',target.read_bytes()[16:24]),(2400,2400))

    def test_usdt_html_is_unchanged_from_the_approved_implementation(self):
        # Golden HTML from d9e4894, including its embedded artwork and OFL font.
        from test_market_images import SAMPLE_TIME
        digest=hashlib.sha256(html_for_post('usdt',SAMPLES['usdt'],now=SAMPLE_TIME).encode()).hexdigest()
        self.assertEqual(digest,'88837d898b9f6c9fcc74714b3ba297701493c3f4ef0b97d3d15cff4ce4e62a1e')

    def test_all_25_canonical_flags_match_the_producer_and_fixture(self):
        from iran_fx import CURRENCY_ROWS
        self.assertEqual(len(CURRENCY_FLAG_CODES),25)
        self.assertEqual(set(country for country in CURRENCY_FLAG_CODES.values()),
                         set('us eu gb ch ca au se no ru th sg hk az dk ae tr cn sa in my af kw bh om qa'.split()))
        for code, flag, *_ in CURRENCY_ROWS:
            self.assertEqual(flag_emoji(code),flag)
            self.assertIn(flag+' '+code,SAMPLES['iran-fx'])
        self.assertEqual(len({row[1] for row in FX_SAMPLE_ROWS}),25)

    def test_wrong_incoming_flags_never_override_code_mapping(self):
        corrupt=SAMPLES['iran-fx']
        for code in CURRENCY_ORDER:
            corrupt=corrupt.replace(flag_emoji(code),'🇺🇸')
        html=html_for_post('iran-fx',corrupt,now=SAMPLE_TIMES['iran-fx'])
        flags=re.findall(r'data-flag="([a-z]+)"',html)
        self.assertEqual(flags,[CURRENCY_FLAG_CODES[code] for code in CURRENCY_ORDER])

    def test_canonical_columns_keep_all_values_when_input_is_reversed(self):
        sample=SAMPLES['iran-fx']
        match=re.search(r'(<pre>[^\n]+\n)(.*?)(</pre>)',sample,re.S)
        reverse=sample[:match.start(2)]+'\n'.join(reversed(match.group(2).splitlines()))+sample[match.end(2):]
        rows=parse_iran_fx(reverse)
        self.assertEqual([row.code for row in rows],list(CURRENCY_ORDER))
        self.assertEqual([(r.code,r.price,r.day,r.month) for r in rows],list(FX_SAMPLE_ROWS))
        self.assertEqual([row.code for row in rows[:13]],'USD EUR GBP CHF CAD AUD SEK NOK RUB THB SGD HKD AZN'.split())
        self.assertEqual([row.code for row in rows[13:]],'DKK AED TRY CNY SAR INR MYR AFN KWD BHD OMR QAR'.split())

    def test_actual_iran_fx_producer_keeps_daily_monthly_and_unavailable(self):
        from iran_fx import build_iran_fx_post
        rates={code:Decimal(1000+i*137) for i,code in enumerate(CURRENCY_ORDER) if code!='QAR'}
        text=build_iran_fx_post(rates,{'USD':Decimal('-1.23')},{'USD':Decimal('4.56')},unavailable_codes={'QAR'})
        rows={row.code:row for row in parse_iran_fx(text)}
        self.assertEqual((rows['USD'].price,rows['USD'].day,rows['USD'].month),('1,000','-1.23%','+4.56%'))
        self.assertEqual((rows['QAR'].price,rows['QAR'].day,rows['QAR'].month),('—','—','—'))

    def test_legacy_iran_gold_history_is_daily_and_monthly_is_missing(self):
        from iran_gold import IranGoldMarket, build_iran_gold_post
        prices={name:Decimal(10000+i*1000) for i,name in enumerate(GOLD_COINS)}
        market=IranGoldMarket(prices,{},Decimal('5000'),Decimal('20000'))
        previous={name:value/Decimal('1.10') for name,value in prices.items()}
        rows=parse_iran_gold(build_iran_gold_post(market,previous))
        self.assertEqual([r.name for r in rows],list(GOLD_COINS+GOLD_BARS))
        self.assertEqual(rows[0].price,'1,000')
        self.assertEqual(rows[0].day,'+10.00%')
        html=html_for_post('iran-gold',build_iran_gold_post(market,previous),now=SAMPLE_TIMES['iran-gold'])
        self.assertEqual(html.count('data-period="1m" data-value="—"'),7)
        self.assertIn('data-period="24h" data-value="+10.00%"',html)
        self.assertIn('section-heading',html)
        self.assertNotIn('>●<',html)

    def test_legacy_turkish_gold_sell_buy_and_period_contract(self):
        from gold_prices import GoldQuote,build_turkish_gold_post
        quotes=[GoldQuote(code,'','',Decimal(100+i*10),Decimal(104+i*10))
                for i,code in enumerate(('gram','quarter','half','tam'))]
        rows=parse_turkey_gold(build_turkish_gold_post(quotes,{'gram':(Decimal('98'),Decimal('102'))}))
        self.assertEqual((rows[0].sell,rows[0].buy,rows[0].day),('104','100','+2.00%'))
        html=html_for_post('turkey-gold',build_turkish_gold_post(quotes),now=SAMPLE_TIMES['turkey-gold'])
        self.assertIn('class="num sell" dir="ltr" data-value="104"',html)
        self.assertIn('class="num buy" dir="ltr" data-value="100"',html)
        self.assertEqual(html.count('data-period="1m" data-value="—"'),4)
        for label in ('Gram Altın','Çeyrek Altın','Yarım Altın','Tam Altın'):
            self.assertIn('<small>'+label+'</small>',html)

    def test_legacy_pulse_midpoints_remain_four_decimals_and_daily(self):
        from market_pulse import build_turkey_fx_pulse_post
        usd=[SimpleNamespace(name='Kapalıçarşı',buy=Decimal('49.7800'),sell=Decimal('49.8000'))]
        eur=[SimpleNamespace(name='Kapalıçarşı',buy=Decimal('55.5700'),sell=Decimal('55.5800'))]
        text=build_turkey_fx_pulse_post(usd,eur,{'Kapalıçarşı':(Decimal('49'),Decimal('49'))})
        rows=parse_pulse(text)
        self.assertEqual([(r.pair,r.rate) for r in rows],[('USD/TL','49.7900'),('EUR/TL','55.5750')])
        self.assertEqual(rows[0].day,'+1.61%')
        html=html_for_post('fx-pulse',text,now=SAMPLE_TIMES['fx-pulse'])
        self.assertIn('۴۹٫۷۹۰۰',html)
        self.assertEqual(html.count('data-period="1m" data-value="—"'),2)

    def test_timezones_cross_local_midnight_correctly(self):
        now=datetime(2026,10,25,20,45,tzinfo=timezone.utc)
        iran=html_for_post('iran-gold',SAMPLES['iran-gold'],now=now)
        turkey=html_for_post('turkey-gold',SAMPLES['turkey-gold'],now=now)
        self.assertIn('دوشنبه ۴ آبان ۱۴۰۵',iran)
        self.assertIn('۰۰:۱۵',iran)
        self.assertIn('یکشنبه ۳ آبان ۱۴۰۵',turkey)
        self.assertIn('۲۳:۴۵',turkey)

    def test_source_clock_and_missing_clock(self):
        for kind in ARTBOARDS:
            city='تهران' if kind.startswith('iran-') else 'استانبول'
            text=SAMPLES[kind]+'\n🕒 <code>07:08</code> '+city
            self.assertIn('dir="ltr">۰۷:۰۸',html_for_post(kind,text))
            self.assertIn('dir="ltr">—',html_for_post(kind,SAMPLES[kind]))
            with self.assertRaises(ValueError):
                html_for_post(kind,text,now=datetime(2026,10,25))

    def test_rejects_duplicate_missing_unknown_and_injected_rows(self):
        invalid=(('iran-fx',SAMPLES['iran-fx'].replace('🇪🇺 EUR','🇪🇺 USD')),
                 ('iran-fx',SAMPLES['iran-fx'].replace('USD 269,600','AAA 269,600')),
                 ('iran-gold',SAMPLES['iran-gold'].replace('سکه امامی','<script>x</script>')),
                 ('iran-gold',SAMPLES['iran-gold'].replace('سکه امامی','سکه نامشخص')),
                 ('turkey-gold',SAMPLES['turkey-gold'].replace('CEYREK','GRAM')),
                 ('fx-pulse',SAMPLES['fx-pulse'].replace('EUR/TL','USD/TL')),
                 ('fx-pulse',SAMPLES['fx-pulse'].replace('49.7900','49.79<script>x</script>')))
        for kind,text in invalid:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                html_for_post(kind,text,now=SAMPLE_TIMES[kind])

    def test_all_embedded_flags_have_a_license_and_valid_svg(self):
        import xml.etree.ElementTree as ET
        assets=Path(__file__).with_name('market_image_assets')/'flags'
        self.assertIn('MIT License',(assets/'LICENSE.txt').read_text())
        for country in CURRENCY_FLAG_CODES.values():
            self.assertTrue(ET.parse(assets/(country+'.svg')).getroot().tag.endswith('svg'))

    def test_browser_outputs_and_long_unavailable_fields(self):
        if os.environ.get('RENDER_PNG_TESTS')!='1':
            self.skipTest('Enable RENDER_PNG_TESTS=1 for browser checks')
        from playwright.sync_api import sync_playwright
        from market_report_templates import validate_report_layout
        import shutil
        executable=os.environ.get('ALANCHANDE_CHROMIUM_PATH') or shutil.which('chromium') or shutil.which('google-chrome')
        samples={kind:SAMPLES[kind] for kind in ARTBOARDS}
        samples['iran-fx']=samples['iran-fx'].replace('USD 269,600','USD 999,999,999').replace('QAR 74,125 — +15.53%','QAR — — —')
        with tempfile.TemporaryDirectory() as directory:
            for kind,(width,height) in ARTBOARDS.items():
                with self.subTest(render=kind):
                    target=render_png(kind,samples[kind],Path(directory)/(kind+'.png'),demo=True,now=SAMPLE_TIMES[kind])
                    self.assertEqual(struct.unpack('>II',target.read_bytes()[16:24]),(width*2,(height+40)*2))
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=executable,args=['--no-sandbox'])
                try:
                    for kind in ARTBOARDS:
                        page=browser.new_page(viewport={'width':1200,'height':1700})
                        page.route('**/*',lambda route:route.abort())
                        page.set_content(html_for_post(kind,samples[kind],now=SAMPLE_TIMES[kind]))
                        page.evaluate('document.fonts.ready')
                        page.evaluate('() => Promise.all([...document.images].map(i=>i.decode()))')
                        validate_report_layout(page)
                        self.assertTrue(page.evaluate('() => [...document.images].every(i=>i.naturalWidth>0)'))
                        if kind=='iran-fx':
                            self.assertEqual(page.locator('tbody tr').count(),25)
                            self.assertEqual(page.locator('.currency-flag').count(),25)
                            self.assertEqual(page.locator('.period').count(),0)
                            # Ordinary rates render at about 20 CSS px when the
                            # complete image is viewed at a 390 px phone width.
                            normal=page.locator('tr[data-code="EUR"] .price')
                            font_size=normal.evaluate('e => parseFloat(getComputedStyle(e).fontSize)')
                            self.assertGreaterEqual(font_size*390/1200,19.5)
                        page.close()
                finally:
                    browser.close()


if __name__=='__main__':
    unittest.main()
