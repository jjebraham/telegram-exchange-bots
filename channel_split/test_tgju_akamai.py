"""Pinned TGJU relay, freshness, failure isolation and unchanged quote parsing."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tgju_akamai as relay
import tgju_public_api as api

NOW = datetime(2026, 10, 27, 10, 30, tzinfo=timezone.utc)


def envelope():
    return {'ok': True, 'protocol': 1, 'selector': relay.SELECTOR, 'http_status': 200,
            'observed_at_utc': (NOW - timedelta(seconds=1)).isoformat(),
            'response_headers': {'Date': format_datetime(NOW - timedelta(seconds=2)), 'Age': '0'},
            'data': {'current': {'sekee': {'p': '2,700,000,000', 'ts': '2026-10-26 12:00:00'}}}}


class RelayTests(unittest.TestCase):
    def test_fresh_response_preserves_native_prices_and_last_change_times(self):
        data = envelope()
        result = relay.validate_envelope(data, now=NOW)
        self.assertIs(result, data['data'])
        self.assertEqual(result['current']['sekee']['ts'], '2026-10-26 12:00:00')
        self.assertEqual(api.parse_public_prices(result, ('sekee',))['sekee'], 2700000000)

    def test_wrong_identity_status_or_missing_payload_is_rejected(self):
        for key, value in [('ok', False), ('protocol', True), ('protocol', 2),
                           ('selector', 'unapproved'), ('http_status', 503), ('data', {})]:
            with self.subTest(key=key, value=value):
                data = envelope()
                data[key] = value
                with self.assertRaises(ValueError):
                    relay.validate_envelope(data, now=NOW)

    def test_expired_future_or_cached_responses_are_rejected(self):
        for seconds in (-31, 6):
            data = envelope()
            data['observed_at_utc'] = (NOW + timedelta(seconds=seconds)).isoformat()
            with self.subTest(observed=seconds), self.assertRaises(ValueError):
                relay.validate_envelope(data, now=NOW)
        for age in ('31', '-1', 'NaN', 'Infinity', True):
            data = envelope()
            data['response_headers']['Age'] = age
            with self.subTest(age=age), self.assertRaises(ValueError):
                relay.validate_envelope(data, now=NOW)
        data = envelope()
        data['response_headers']['Date'] = format_datetime(NOW - timedelta(seconds=91))
        with self.assertRaises(ValueError):
            relay.validate_envelope(data, now=NOW)
        data = envelope()
        del data['response_headers']['Date']
        with self.assertRaises(ValueError):
            relay.validate_envelope(data, now=NOW)

    def test_transport_failures_do_not_expose_output_or_fall_back_to_another_route(self):
        secret = b'simulated-private-error-output'
        with patch.object(relay, 'ssh_command', return_value=['fake-ssh']), \
             patch.object(relay.subprocess, 'run', return_value=NS(returncode=1, stdout=secret, stderr=secret)):
            with self.assertRaises(RuntimeError) as caught:
                relay.fetch_current_payload()
            self.assertNotIn(secret.decode(), str(caught.exception))
        with patch.object(relay, 'ssh_command', return_value=['fake-ssh']), \
             patch.object(relay.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fake', 1)):
            with self.assertRaises(RuntimeError):
                relay.fetch_current_payload()
        with patch.dict(os.environ, {'ALANCHANDE_TGJU_TRANSPORT': 'akamai_api'}), \
             patch.object(relay, 'fetch_current_payload', side_effect=RuntimeError('unavailable')), \
             patch.object(api, 'urlopen') as direct:
            with self.assertRaises(RuntimeError):
                api.fetch_public_prices(('sekee',))
            direct.assert_not_called()

    def test_malformed_or_oversized_relay_json_is_rejected(self):
        for raw in (b'', b'not-json', b' ' * (relay.MAX_BYTES + 1)):
            with self.subTest(size=len(raw)), \
                 patch.object(relay, 'ssh_command', return_value=['fake-ssh']), \
                 patch.object(relay.subprocess, 'run', return_value=NS(returncode=0, stdout=raw)):
                with self.assertRaises(ValueError):
                    relay.fetch_current_payload()

    def test_relay_mode_retains_rial_conversion_and_one_missing_noncore_policy(self):
        from iran_fx import CURRENCY_ROWS
        data = {'current': {('price_dollar_rl' if code == 'USD' else 'price_' + code.lower()):
                            {'p': '2,700,000'} for code, *_ in CURRENCY_ROWS}}
        data['current'].pop('price_hkd')
        with patch.dict(os.environ, {'ALANCHANDE_TGJU_TRANSPORT': 'akamai_api'}), \
             patch.object(relay, 'fetch_current_payload', return_value=data) as fetch:
            rates = api.fetch_iran_fx_public()
            self.assertEqual(rates['USD'], 270000)
            self.assertEqual(len(rates), 24)
            self.assertNotIn('HKD', rates)
            fetch.assert_called_once()
            broken = deepcopy(data)
            broken['current'].pop('price_qar')
            fetch.return_value = broken
            with self.assertRaises(ValueError):
                api.fetch_iran_fx_public()

    @unittest.skipUnless(os.name == 'posix', 'Production uses Linux SSH file permissions')
    def test_command_has_one_fixed_selector_and_rejects_other_pins_or_open_key_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / 'identity'
            known = Path(directory) / 'known_hosts'
            key.write_text('simulated-private-key')
            known.write_text(relay.HOST_LINE + '\n')
            key.chmod(0o600)
            known.chmod(0o600)
            command = relay.ssh_command(key, known)
            self.assertEqual(command[-2:], ['root@' + relay.HOST, 'tgju_current'])
            self.assertIn('StrictHostKeyChecking=yes', command)
            self.assertIn('ForwardAgent=no', command)
            known.write_text('different host pin')
            with self.assertRaises(ValueError):
                relay.ssh_command(key, known)
            known.write_text(relay.HOST_LINE + '\n')
            key.chmod(0o644)
            with self.assertRaises(ValueError):
                relay.ssh_command(key, known)


if __name__ == '__main__':
    unittest.main()
