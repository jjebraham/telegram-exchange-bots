"""Exercise the real SDK login redirect loop with an in-memory fake transport."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from telethon import errors
from telethon.sessions import MemorySession
from telethon.tl import functions, types
from kiani_story_worker import new_client
from setup_kiani_stories import SetupError, error_hint, prepare_account_switch, setup, setup_lock, write_private


class Sender:
    def __init__(self, error):
        self.error, self.calls = error, 0

    def send(self, request, ordered=False):
        self.calls += 1
        future = asyncio.get_running_loop().create_future()
        if self.calls == 1:
            future.set_exception(self.error)
        else:
            future.set_result(types.auth.SentCode(types.auth.SentCodeTypeApp(5), 'simulated-code-hash'))
        return future


def client_and_request(interactive, error):
    # MemorySession and a fake sender ensure no files, network or real credentials.
    client = new_client({'session_path': MemorySession(), 'api_id': 1, 'api_hash': '0' * 32},
                        interactive=interactive)
    sender = Sender(error)
    client.is_user_authorized = AsyncMock(return_value=False)
    client._switch_dc = AsyncMock()
    request = functions.auth.SendCodeRequest('10000000000', 1, '0' * 32, types.CodeSettings())
    return client, sender, request


class LoginRedirectTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_login_follows_normal_telegram_dc_redirect(self):
        client, sender, request = client_and_request(True, errors.PhoneMigrateError(None, capture=4))
        result = await client._call(sender, request)
        self.assertIsInstance(result, types.auth.SentCode)
        self.assertEqual(sender.calls, 2)
        client._switch_dc.assert_awaited_once_with(4)

    async def test_publishing_keeps_zero_automatic_request_retries(self):
        client, sender, request = client_and_request(False, errors.PhoneMigrateError(None, capture=4))
        with self.assertRaises(errors.PhoneMigrateError):
            await client._call(sender, request)
        self.assertEqual(sender.calls, 1)

    async def test_login_does_not_retry_a_telegram_flood_wait(self):
        client, sender, request = client_and_request(True, errors.FloodWaitError(None, capture=300))
        with self.assertRaises(errors.FloodWaitError):
            await client._call(sender, request)
        self.assertEqual(sender.calls, 1)

    def test_unknown_exception_details_are_never_printed(self):
        secret = 'simulated-private-session-content'
        self.assertNotIn(secret, error_hint(ValueError(secret)))
        self.assertIn('300 seconds', error_hint(errors.FloodWaitError(None, capture=300)))
        self.assertEqual(error_hint(SetupError('Enter digits only.')), 'Enter digits only.')


class AccountSwitchTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Production uses a Linux worker lock')
    def test_setup_lock_excludes_simultaneous_worker_or_login(self):
        with tempfile.TemporaryDirectory() as directory, patch('setup_kiani_stories.Path.home', return_value=Path(directory)):
            with setup_lock():
                with self.assertRaises(SetupError):
                    with setup_lock():
                        self.fail('A second setup acquired the active worker lock')
            with setup_lock():
                pass

    def test_switch_uses_fresh_login_and_keeps_delivery_history_and_channel_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'private-config/config.json'
            folder = root / 'private-session'
            folder.mkdir()
            session = folder / 'admin.session'
            history = root / 'delivery.sqlite3'
            history.write_bytes(b'simulated-existing-delivery-receipts')
            old = {'api_id': 1, 'api_hash': '0' * 32, 'expected_user_id': 999,
                   'session_path': str(session), 'state_db': str(history),
                   'channel_ids': {'alanchande_com': 111, 'exchangekiani': 222}, 'enabled': True}
            write_private(config, old)
            for suffix in ('', '-journal', '-wal', '-shm'):
                path = folder / ('admin.session' + suffix)
                path.write_bytes(b'simulated-old-login')
                os.chmod(path, 0o600)
            retained = prepare_account_switch(config, old, folder)
            self.assertEqual(retained, {'channel_ids': old['channel_ids'], 'state_db': str(history)})
            self.assertFalse(config.exists())
            self.assertFalse(session.exists())
            backups = list(config.parent.glob('previous-account-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads((backups[0] / 'config.json').read_text()), old)
            self.assertEqual((backups[0] / 'admin.session').read_bytes(), b'simulated-old-login')
            self.assertEqual(history.read_bytes(), b'simulated-existing-delivery-receipts')
            if os.name == 'posix':
                self.assertEqual(backups[0].stat().st_mode & 0o777, 0o700)

    def test_switch_rejects_a_session_outside_the_dedicated_folder_before_moving_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.json'
            old = {'session_path': str(root / 'unrelated.session')}
            write_private(config, old)
            with self.assertRaises(SetupError):
                prepare_account_switch(config, old, root / 'dedicated')
            self.assertTrue(config.exists())
            self.assertEqual(list(root.glob('previous-account-*')), [])

    def test_switch_without_an_old_login_can_start_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(prepare_account_switch(root / 'config.json', {}, root / 'sessions'), {})


class AccountSwitchWizardTests(unittest.IsolatedAsyncioTestCase):
    async def test_wizard_prompts_for_new_api_and_phone_and_pins_replacement_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / '.config/kiani-stories/config.json'
            session = root / '.local/share/kiani-stories/admin.session'
            session.parent.mkdir(parents=True)
            session.write_bytes(b'simulated-old-login')
            os.chmod(session, 0o600)
            old = {'api_id': 1, 'api_hash': '0' * 32, 'expected_user_id': 999,
                   'session_path': str(session), 'channel_ids': {'alanchande_com': 111, 'exchangekiani': 222}}
            write_private(config, old)
            write_private(config.with_name('ready'), {'ready': True})
            client = NS(connect=AsyncMock(), disconnect=AsyncMock(),
                        get_me=AsyncMock(return_value=NS(id=1000, bot=False)),
                        get_entity=AsyncMock(side_effect=[NS(id=111, broadcast=True), NS(id=222, broadcast=True)]))

            async def login(**callbacks):
                self.assertEqual(callbacks['phone'](), '+10000000000')
                self.assertEqual(callbacks['code_callback'](), '12345')
                self.assertEqual(callbacks['password'](), 'simulated-password')

            client.start = login

            def factory(data, *, interactive):
                self.assertTrue(interactive)
                self.assertEqual(data['api_id'], 2)
                self.assertEqual(data['api_hash'], '1' * 32)
                self.assertEqual(data['expected_user_id'], 0)
                self.assertFalse(session.exists())
                self.assertFalse(config.with_name('ready').exists())
                return client

            publisher = NS(_load_local_env=lambda: None, _kiani_forward_db_path=lambda: root / 'source.sqlite3')
            with patch('setup_kiani_stories.CONFIG', config), \
                 patch('setup_kiani_stories.Path.home', return_value=root), \
                 patch('setup_kiani_stories.sys.stdin.isatty', return_value=True), \
                 patch('builtins.input', side_effect=['2', '+10000000000']) as prompt, \
                 patch('setup_kiani_stories.getpass', side_effect=['1' * 32, '12345', 'simulated-password']), \
                 patch('setup_kiani_stories.new_client', side_effect=factory), \
                 patch('setup_kiani_stories.preflight', new=AsyncMock(return_value={name: {'ready': True} for name in old['channel_ids']})), \
                 patch.dict(sys.modules, {'publish_channels': publisher}):
                await setup(NS(check=False, switch_account=True))
            result = json.loads(config.read_text())
            self.assertTrue(result['enabled'])
            self.assertEqual(result['expected_user_id'], 1000)
            self.assertEqual(result['channel_ids'], old['channel_ids'])
            self.assertTrue(config.with_name('ready').exists())
            self.assertEqual(prompt.call_count, 2)


if __name__ == '__main__':
    unittest.main()
