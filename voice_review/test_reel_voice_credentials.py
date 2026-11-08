import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import reel_voice_credentials as credentials


class CredentialTests(unittest.TestCase):
    def test_private_file_roundtrip_and_partial_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private' / 'credentials.env'
            credentials.write({'ELEVENLABS_API_KEY': 'sk_test_123'}, path)
            credentials.write({'KIANI_VOICE_TEST_BOT_TOKEN': '123456789:abcdefghijklmnopqrstuvwx'}, path)
            values = credentials.read(path)
            self.assertEqual(values['ELEVENLABS_API_KEY'], 'sk_test_123')
            self.assertEqual(values['KIANI_VOICE_TEST_BOT_TOKEN'], '123456789:abcdefghijklmnopqrstuvwx')
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(credentials.get_secret('ELEVENLABS_API_KEY', path), 'sk_test_123')
            with patch.dict(os.environ, {'ELEVENLABS_API_KEY': 'sk_override'}, clear=True):
                self.assertEqual(credentials.get_secret('ELEVENLABS_API_KEY', path), 'sk_override')

    def test_shell_injection_or_unknown_fields_are_never_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private' / 'credentials.env'
            for updates in ({'ELEVENLABS_API_KEY': '$(touch /tmp/unsafe)'}, {'OTHER': 'x'}):
                with self.subTest(updates=updates), self.assertRaises(credentials.CredentialError):
                    credentials.write(updates, path)

    def test_preview_and_tool_read_private_file_without_prompting(self):
        from preview_voice_reel import secret as preview_secret
        from reel_voice_tool import secret as tool_secret
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(Path, 'home', return_value=Path(tmp)), \
                patch.dict(os.environ, {}, clear=True), \
                patch('getpass.getpass', side_effect=AssertionError('Unexpected secret prompt')):
            credentials.write({'ELEVENLABS_API_KEY': 'sk_test',
                               'KIANI_VOICE_TEST_BOT_TOKEN': '123456789:abcdefghijklmnopqrstuvwx'})
            self.assertEqual(preview_secret('ELEVENLABS_API_KEY', 'hidden'), 'sk_test')
            self.assertEqual(tool_secret('KIANI_VOICE_TEST_BOT_TOKEN', 'hidden'),
                             '123456789:abcdefghijklmnopqrstuvwx')

    @unittest.skipUnless(os.name == 'posix', 'POSIX file permissions required')
    def test_insecure_file_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private' / 'credentials.env'
            credentials.write({'ELEVENLABS_API_KEY': 'sk_test'}, path)
            path.chmod(0o644)
            with self.assertRaises(credentials.CredentialError):
                credentials.read(path)


if __name__ == '__main__':
    unittest.main()

