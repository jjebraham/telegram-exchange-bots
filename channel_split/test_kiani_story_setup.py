"""Exercise the real SDK login redirect loop with an in-memory fake transport."""
import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from telethon import errors
from telethon.sessions import MemorySession
from telethon.tl import functions, types
from kiani_story_worker import new_client
from setup_kiani_stories import SetupError, error_hint


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


if __name__ == '__main__':
    unittest.main()
