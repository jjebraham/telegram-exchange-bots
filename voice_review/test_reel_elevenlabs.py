from io import BytesIO
from pathlib import Path
import math
import shutil
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import wave

from reel_elevenlabs import VoiceError, _generate, synthesize_segment


def sample(script, *args):
    output = BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setparams((1, 2, 24000, 48000, 'NONE', 'not compressed'))
        stream.writeframes(b''.join(struct.pack('<h', int(3000 * math.sin(i / 12))) for i in range(48000)))
    starts = [i * 1.7 / max(len(script), 1) for i in range(len(script))]
    return output.getvalue(), {
        'characters': list(script), 'character_start_times_seconds': starts,
        'character_end_times_seconds': [x + .01 for x in starts],
    }


class RequestTests(unittest.TestCase):
    def test_request_uses_timestamp_endpoint_and_never_prints_key(self):
        class Opener:
            def open(self, request, timeout):
                self.request = request
                raise HTTPError(request.full_url, 401, 'private response', {}, None)
        opener = Opener()
        with patch('reel_elevenlabs.build_opener', return_value=opener):
            with self.assertRaises(VoiceError) as raised:
                _generate('متن آزمایشی', 'secret-test-key', 'Voice123', 'eleven_v3', 10)
        self.assertNotIn('secret-test-key', str(raised.exception))
        self.assertTrue(opener.request.full_url.endswith('/Voice123/with-timestamps'))
        self.assertIn(b'"language_code": "fa"', opener.request.data)
        self.assertIn(b'"model_id": "eleven_v3"', opener.request.data)


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class VoiceTests(unittest.TestCase):
    def test_synthesized_audio_is_accelerated_cached_and_not_requested_twice(self):
        with tempfile.TemporaryDirectory() as tmp, patch('reel_elevenlabs._generate', side_effect=sample) as request:
            path = Path(tmp) / 'private' / 'cache.sqlite3'
            first = synthesize_segment('سال ۲۰۲۶', path, 'test-key')
            second = synthesize_segment('سال ۲۰۲۶', path, 'test-key')
            self.assertFalse(first['cached'])
            self.assertTrue(second['cached'])
            self.assertEqual(first['audio'], second['audio'])
            self.assertEqual(request.call_count, 1)
            with wave.open(BytesIO(first['audio']), 'rb') as audio:
                self.assertEqual(audio.getnchannels(), 1)
                self.assertEqual(audio.getframerate(), 24000)
                self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 2 / 1.5, delta=.15)

    def test_changed_display_tokens_cannot_reuse_incompatible_mapping(self):
        with tempfile.TemporaryDirectory() as tmp, patch('reel_elevenlabs._generate', side_effect=sample) as request:
            path = Path(tmp) / 'cache.sqlite3'
            a = synthesize_segment('BTC', path, 'test-key')
            b = synthesize_segment('بیت کوین', path, 'test-key')
            self.assertEqual(a['script'], b['script'])
            self.assertEqual(len(a['starts']), 1)
            self.assertEqual(len(b['starts']), 2)
            self.assertEqual(request.call_count, 2)

    def test_corrupt_cached_audio_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch('reel_elevenlabs._generate', side_effect=sample) as request:
            path = Path(tmp) / 'cache.sqlite3'
            synthesize_segment('سلام', path, 'test-key')
            con = sqlite3.connect(path)
            try:
                con.execute("UPDATE narration SET audio=X'1234'")
                con.commit()
            finally:
                con.close()
            with self.assertRaises(VoiceError):
                synthesize_segment('سلام', path, 'test-key')
            self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()

