"""Photo/text delivery contracts; no Telegram credentials or network required."""
import io
import json
import os
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_images import IncompleteImagePostError, telegram_send_photo
from test_market_images import SAMPLES
import manual_image_preview as manual


def response(message_id):
    return io.BytesIO(json.dumps({'ok': True, 'result': {'message_id': message_id}}).encode())


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.photo = Path(self.temp.name) / 'fx.png'
        self.photo.write_bytes(b'test-photo-bytes')

    def test_full_bulletin_is_unmodified_linked_text_with_both_receipts(self):
        from iran_fx import CURRENCY_ROWS, build_iran_fx_post
        rates = {code:Decimal(270000+i*137) for i,(code,*_) in enumerate(CURRENCY_ROWS) if code!='QAR'}
        days = {code:Decimal(i)/100 for i,code in enumerate(rates)}
        months = {code:Decimal(10)+Decimal(i)/100 for i,code in enumerate(rates)}
        details = build_iran_fx_post(rates,days,months,unavailable_codes={'QAR'})
        self.assertGreater(len(details), 1024)
        with patch('market_images.urlopen', side_effect=[response(101), response(102)]) as send:
            result = telegram_send_photo('private-token', '@alanchandetest', self.photo, 'Rate board', details_text=details)
        self.assertEqual((result['result']['message_id'], result['details_result']['message_id']), (101, 102))
        self.assertEqual(send.call_count, 2)
        self.assertTrue(send.call_args_list[0].args[0].full_url.endswith('/sendPhoto'))
        request = send.call_args_list[1].args[0]
        self.assertTrue(request.full_url.endswith('/sendMessage'))
        payload = parse_qs(request.data.decode())
        self.assertEqual(payload['text'], [details])
        self.assertEqual(payload['parse_mode'], ['HTML'])
        self.assertEqual(json.loads(payload['reply_parameters'][0]), {'message_id': 101})
        self.assertEqual(payload['chat_id'], ['@alanchandetest'])

    def test_other_photo_posts_remain_one_message(self):
        with patch('market_images.urlopen', return_value=response(201)) as send:
            result = telegram_send_photo('private-token', '@alanchandetest', self.photo, 'Gold')
        self.assertEqual(send.call_count, 1)
        self.assertNotIn('details_result', result)

    def test_oversized_details_fail_before_any_photo_is_sent(self):
        with patch('market_images.urlopen') as send, self.assertRaises(ValueError):
            telegram_send_photo('private-token', '@alanchandetest', self.photo, 'FX', details_text='<pre>'+'😀'*2049+'</pre>')
        send.assert_not_called()

    def test_photo_failure_never_sends_details_or_exposes_credentials(self):
        error = HTTPError('https://api.telegram.org/botprivate-token/sendPhoto', 500, '', {}, None)
        with patch('market_images.urlopen', side_effect=error) as send, self.assertRaises(RuntimeError) as caught:
            telegram_send_photo('private-token', '@alanchandetest', self.photo, 'FX', details_text=SAMPLES['iran-fx'])
        self.assertEqual(send.call_count, 1)
        self.assertNotIn('private-token', str(caught.exception))

    def test_unconfirmed_details_report_partial_photo_without_retry(self):
        for failure in (URLError('private-token'), io.BytesIO(b'{"ok":false}'), io.BytesIO(b'{"ok":true,"result":{}}')):
            with self.subTest(failure=type(failure).__name__), patch('market_images.urlopen', side_effect=[response(301), failure]) as send:
                with self.assertRaises(IncompleteImagePostError) as caught:
                    telegram_send_photo('private-token', '@alanchandetest', self.photo, 'FX', details_text=SAMPLES['iran-fx'])
                self.assertEqual(send.call_count, 2)
                self.assertEqual(caught.exception.photo_response['result']['message_id'], 301)
                self.assertIn('Do not resend the photo', str(caught.exception))
                self.assertNotIn('private-token', str(caught.exception))

    def _manual_preview(self, safety):
        home = Path(self.temp.name)
        live = home/'telegram_bot_repo/channel_split'
        live.mkdir(parents=True)
        (live/'publish_channels.py').write_text('# fixture\n')
        text = SAMPLES['iran-fx'] + '\n🕒 <code>12:00</code> تهران\nOriginal omission note'
        stdout = (f'SAFETY iran-fx: {safety}\n'
                  '===== ALANCHANDE_CHANNEL_ID (bot: ALANCHANDE_TELEGRAM_BOT_TOKEN) =====\n' + text)
        target = home/'preview.png'
        import publish_channels
        def render(kind, approved, path, **kwargs):
            Path(path).write_bytes(b'fixture-png')
            return path
        with patch.object(Path, 'home', return_value=home), patch.object(sys, 'argv', ['preview','--kind','iran-fx','--send-test','--output',str(target)]), \
             patch.dict(os.environ, {'ALANCHANDE_TELEGRAM_BOT_TOKEN':'private-token'}), \
             patch.object(publish_channels, '_load_local_env'), \
             patch.object(manual.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,stdout,'')) as fetch, \
             patch.object(manual, 'render_png', side_effect=render) as renderer, \
             patch.object(manual, 'telegram_send_photo', return_value={'ok':True,'result':{'message_id':401},'details_result':{'message_id':402}}) as send:
            if safety == 'VERIFIED':
                self.assertEqual(manual.main(), 0)
                self.assertEqual(renderer.call_args.args[1], text)
                self.assertEqual(send.call_args.kwargs['details_text'], text)
                self.assertEqual(target.with_suffix('.details.html').read_text(encoding='utf-8'), text)
                self.assertEqual(json.loads(target.with_suffix('.receipt.json').read_text())['details_message_id'], 402)
            else:
                with self.assertRaises(SystemExit):
                    manual.main()
                renderer.assert_not_called()
                send.assert_not_called()
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(fetch.call_args.kwargs['env']['MARKET_SAFETY_MODE'], 'enforce')

    def test_manual_preview_uses_one_verified_snapshot_for_image_and_full_text(self):
        self._manual_preview('VERIFIED')

    def test_blocked_preview_sends_neither_image_nor_details(self):
        self._manual_preview('BLOCKED')


if __name__ == '__main__':
    unittest.main()
