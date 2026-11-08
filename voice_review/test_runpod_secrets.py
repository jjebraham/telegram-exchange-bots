import os
from pathlib import Path
import tempfile
import unittest

import runpod_secrets as secrets


class SecretTests(unittest.TestCase):
    def test_round_trip_and_refuse_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private' / 'credentials.env'
            secrets.write(path, 'sample-key-123')
            self.assertEqual(secrets.read(path), 'sample-key-123')
            secrets.write(path, 'sample-key-123')
            with self.assertRaises(secrets.SecretError): secrets.write(path, 'other-key-456')
            self.assertEqual(secrets.read(path), 'sample-key-123')
    def test_reject_newline_and_never_echo_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private' / 'credentials.env'
            with self.assertRaises(secrets.SecretError) as exc: secrets.write(path, 'secret\ninjection')
            self.assertNotIn('secret', str(exc.exception))
    @unittest.skipUnless(hasattr(os, 'getuid'), 'POSIX permissions unavailable')
    def test_refuse_insecure_file_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'private' / 'credentials.env'
            secrets.write(path, 'sample-key-123')
            os.chmod(path, 0o644)
            with self.assertRaises(secrets.SecretError): secrets.read(path)


if __name__ == '__main__': unittest.main()
