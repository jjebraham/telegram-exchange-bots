import io,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0,str(Path(__file__).resolve().parent))
import tgju_public_api as api
from prepare_tgju_api_transport import add_hook

class ApiTests(unittest.TestCase):
    def _fx_payload(self):
        from iran_fx import CURRENCY_ROWS
        return {'current':{
            ('price_dollar_rl' if code=='USD' else 'price_'+code.lower()):
                {'p':str(2000000+i*1000),'ts':'2020-01-01 00:00:00'}
            for i,(code,*_) in enumerate(CURRENCY_ROWS)
        }}

    def _fx_from_payload(self,payload):
        with patch.object(api,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            return api.fetch_iran_fx_public()

    def test_required_prices_and_invalid_values_fail_closed(self):
        self.assertEqual(api.parse_public_prices({'current':{'sekee':{'p':'2,700,000,000'}}},('sekee',)),{'sekee':Decimal('2700000000')})
        for raw in (None,True,'NaN','0','-1','1,23'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                api.parse_public_prices({'current':{'sekee':{'p':raw}}},('sekee',))
        with self.assertRaises(ValueError):
            api.parse_public_prices({'current':{}},('sekee',))

    def test_transport_fallback_uses_only_official_hosts(self):
        payload=io.BytesIO(b'{"current":{"sekee":{"p":"2700000000"}}}')
        with patch.object(api,'urlopen',side_effect=[URLError('timeout'),payload]) as fetch:
            self.assertEqual(api.fetch_public_prices(('sekee',))['sekee'],Decimal('2700000000'))
        urls=[call.args[0].full_url for call in fetch.call_args_list]
        self.assertTrue(urls[0].startswith('https://call4.tgju.org/ajax.json?rev='))
        self.assertTrue(urls[1].startswith('https://call2.tgju.org/ajax.json?rev='))
        with patch.object(api,'urlopen',return_value=io.BytesIO(b'{"current":{}}')) as fetch:
            with self.assertRaises(ValueError):
                api.fetch_public_prices(('sekee',))
        self.assertEqual(fetch.call_count,1)

    def test_units_match_existing_fx_and_gold_types(self):
        from iran_fx import CURRENCY_ROWS
        from iran_gold import PROFILE_SLUGS,COIN_LABELS
        fx={('price_dollar_rl' if code=='USD' else 'price_'+code.lower()):Decimal(2000000+i*1000)
            for i,(code,*_) in enumerate(CURRENCY_ROWS)}
        with patch.object(api,'fetch_public_prices',return_value=fx):
            prices=api.fetch_iran_fx_public()
        self.assertEqual(prices['USD'],Decimal('200000'))
        gold={slug:Decimal(300000000+i*1000) for i,slug in enumerate(PROFILE_SLUGS.values())}
        with patch.object(api,'fetch_public_prices',return_value=gold):
            market=api.fetch_iran_gold_public()
        self.assertEqual(market.coin_prices_rial[COIN_LABELS[0]],gold[PROFILE_SLUGS[COIN_LABELS[0]]])
        self.assertEqual(market.gold18_rial,gold[PROFILE_SLUGS['طلای ۱۸ عیار']])
        self.assertEqual(market.bubble_values_rial,{})

    def test_one_absent_noncore_fx_price_is_partial_not_stale_substitution(self):
        payload=self._fx_payload()
        payload['current'].pop('price_hkd')
        rates=self._fx_from_payload(payload)
        self.assertEqual(len(rates),24)
        self.assertNotIn('HKD',rates)
        self.assertEqual(rates['USD'],Decimal('200000'))
        # TGJU `ts` is the last change, not a new-tick guarantee; all old
        # fixture timestamps intentionally remain irrelevant to price parsing.
        self.assertIn('TRY',rates)

    def test_null_noncore_fx_price_is_unavailable(self):
        payload=self._fx_payload()
        payload['current']['price_hkd']['p']=None
        self.assertNotIn('HKD',self._fx_from_payload(payload))

    def test_missing_core_multiple_missing_or_malformed_fx_fails_closed(self):
        for omitted in (('price_dollar_rl',),('price_hkd','price_qar')):
            with self.subTest(omitted=omitted):
                payload=self._fx_payload()
                for symbol in omitted:
                    payload['current'].pop(symbol)
                with self.assertRaises(ValueError):
                    self._fx_from_payload(payload)
        for bad in ('0','garbled',-1):
            with self.subTest(bad=bad):
                payload=self._fx_payload()
                payload['current']['price_hkd']['p']=bad
                with self.assertRaises(ValueError):
                    self._fx_from_payload(payload)
        with self.assertRaises(ValueError):
            self._fx_from_payload({'current':{}})
        with self.assertRaises(ValueError):
            self._fx_from_payload([])

    def test_gold_public_transport_stays_strict_when_symbol_is_missing(self):
        from iran_gold import PROFILE_SLUGS
        payload={'current':{slug:{'p':'300000000'} for slug in PROFILE_SLUGS.values()}}
        payload['current'].pop(next(iter(PROFILE_SLUGS.values())))
        with patch.object(api,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaises(ValueError):
                api.fetch_iran_gold_public()

    def test_hook_is_opt_in_and_preserves_original_bytes(self):
        source=b'def fetch(url="original", timeout=25):\r\n    """Existing documentation."""\r\n    return "original result"\r\n\r\n# unrelated local customization\r\n'
        changed=add_hook(source,'fetch','DEFAULT_URL','fetch_iran_fx_public')
        self.assertIn(b'# unrelated local customization\r\n',changed)
        self.assertIn(b'    return "original result"\r\n',changed)
        namespace={'DEFAULT_URL':'original'}
        exec(compile(changed,'fixture.py','exec'),namespace)
        with patch.dict(os.environ,{'ALANCHANDE_TGJU_TRANSPORT':'html'}):
            self.assertEqual(namespace['fetch'](),'original result')
        with patch.dict(os.environ,{'ALANCHANDE_TGJU_TRANSPORT':'public_api'}),patch.object(api,'fetch_iran_fx_public',return_value={'USD':Decimal('1')}) as fetch:
            self.assertEqual(namespace['fetch'](),{'USD':Decimal('1')})
            self.assertEqual(namespace['fetch'](url='custom'),'original result')
        fetch.assert_called_once_with(timeout=25)
        self.assertEqual(add_hook(changed,'fetch','DEFAULT_URL','fetch_iran_fx_public'),changed)
        legacy=changed.replace(b'in {"public_api", "akamai_api"}',b'== "public_api"')
        self.assertEqual(add_hook(legacy,'fetch','DEFAULT_URL','fetch_iran_fx_public'),changed)
        with patch.dict(os.environ,{'ALANCHANDE_TGJU_TRANSPORT':'akamai_api'}),patch.object(api,'fetch_iran_fx_public',return_value={'USD':Decimal('2')}) as fetch:
            self.assertEqual(namespace['fetch'](),{'USD':Decimal('2')})
            self.assertEqual(namespace['fetch'](url='custom'),'original result')

    def test_prepare_dry_run_backup_and_idempotency(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/'repo'; folder=repo/'channel_split'; folder.mkdir(parents=True)
            before={}
            for name in ('iran_fx.py','iran_gold.py'):
                before[name]=(root/name).read_bytes()+b'\n# unrelated local customization\n'
                (folder/name).write_bytes(before[name])
            backup=Path(tmp)/'backups'
            def run(*flags):
                return subprocess.run([sys.executable,str(root/'prepare_tgju_api_transport.py'),'--repo',str(repo),'--backup-dir',str(backup),*flags],capture_output=True,text=True,timeout=20)
            dry=run(); self.assertEqual(dry.returncode,0,dry.stderr)
            self.assertFalse(backup.exists())
            self.assertEqual((folder/'iran_gold.py').read_bytes(),before['iran_gold.py'])
            applied=run('--apply'); self.assertEqual(applied.returncode,0,applied.stderr)
            self.assertIn(b'# unrelated local customization',(folder/'iran_gold.py').read_bytes())
            self.assertEqual((folder/'tgju_public_api.py').read_bytes(),(root/'tgju_public_api.py').read_bytes())
            backups=list(backup.iterdir()); self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'iran_gold.py').read_bytes(),before['iran_gold.py'])
            self.assertEqual(run('--apply').returncode,0)
            self.assertEqual(len(list(backup.iterdir())),1)
            (folder/'tgju_public_api.py').write_bytes(b'# unrelated custom client\n')
            rejected=run('--apply')
            self.assertNotEqual(rejected.returncode,0)
            self.assertEqual((folder/'tgju_public_api.py').read_bytes(),b'# unrelated custom client\n')

if __name__=='__main__':
    unittest.main()
