import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runpod_local_readiness as readiness


class LocalReadinessTests(unittest.TestCase):
    def test_benchmark_only_encodes_hash_verified_private_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            folder = home / '.local/state/kiani-instagram-voice-review/previews/example'
            folder.mkdir(parents=True)
            video = folder / 'preview.mp4'
            video.write_bytes(b'preview')
            digest = hashlib.sha256(b'preview').hexdigest()
            (folder / 'preview.json').write_text(json.dumps({'video_sha256': digest}))
            with patch.object(readiness.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                result = readiness.benchmark(home, 'ffmpeg')
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['video_sha256'], digest)
            args = run.call_args.args[0]
            self.assertIn('libx264', args)
            self.assertEqual(args[-2:], ['null', '-'])
            video.write_bytes(b'changed')
            with patch.object(readiness.subprocess, 'run') as run:
                self.assertEqual(readiness.benchmark(home, 'ffmpeg')['status'], 'unavailable')
                run.assert_not_called()

    def test_timeout_does_not_leave_a_result_video(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(readiness, 'managed_previews', return_value=[(0, Path(tmp) / 'a', 'd' * 64)]), \
                patch.object(readiness.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ffmpeg', 90)):
            self.assertEqual(readiness.benchmark(Path(tmp), 'ffmpeg')['status'], 'timeout')
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
