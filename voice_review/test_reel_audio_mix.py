import shutil
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import wave

from reel_audio_mix import mix_filter


class AudioMixTests(unittest.TestCase):
    def test_default_music_is_twenty_percent_of_original_base(self):
        self.assertIn('volume=0.044000', mix_filter(15))
        self.assertIn('volume=0.066000', mix_filter(15, .30))
        self.assertIn('volume=0.110000', mix_filter(15, .50))

    def test_invalid_configuration_fails_closed(self):
        for args in ((0,), (2, -1), (2, float('nan')), (2, .5, 'true')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                mix_filter(*args)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_graph_runs_with_and_without_ducking(self):
        for ducking in (True, False):
            command = ['ffmpeg', '-v', 'error']
            for source in ('anullsrc=r=48000:cl=stereo', 'sine=frequency=400:sample_rate=48000',
                           'anullsrc=r=48000:cl=stereo', 'sine=frequency=900:sample_rate=48000'):
                command += ['-f', 'lavfi', '-t', '2', '-i', source]
            command += ['-filter_complex', mix_filter(2, .5, ducking), '-map', '[a]',
                        '-t', '2', '-f', 'null', '-']
            with self.subTest(ducking=ducking):
                result = subprocess.run(command, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_music_is_quieter_while_voice_is_present(self):
        rate = 48000
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, frequency, amplitude in (('music', 400, .3), ('voice', 1000, .3), ('keys', 0, 0)):
                with wave.open(str(root / (name + '.wav')), 'wb') as stream:
                    stream.setparams((1, 2, rate, 5 * rate, 'NONE', 'not compressed'))
                    frames = bytearray()
                    for i in range(5 * rate):
                        active = name != 'voice' or 1.5 <= i / rate < 3.5
                        value = int(32767 * amplitude * math.sin(2 * math.pi * frequency * i / rate)) if active else 0
                        frames.extend(struct.pack('<h', value))
                    stream.writeframes(frames)
            levels = []
            for ducking in (False, True):
                output = root / ('duck-' + str(ducking) + '.wav')
                command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-t', '5',
                           '-i', 'anullsrc=r=48000:cl=stereo']
                for name in ('music', 'keys', 'voice'):
                    command += ['-i', str(root / (name + '.wav'))]
                command += ['-filter_complex', mix_filter(5, .5, ducking), '-map', '[a]',
                            '-t', '5', '-c:a', 'pcm_s16le', str(output)]
                subprocess.run(command, capture_output=True, timeout=30, check=True)
                with wave.open(str(output), 'rb') as stream:
                    channels = stream.getnchannels()
                    stream.setpos(2 * rate)
                    raw = stream.readframes(rate)
                samples = struct.unpack('<' + 'h' * (len(raw) // 2), raw)[::channels]
                signal = sum(v * math.sin(2 * math.pi * 400 * i / rate) for i, v in enumerate(samples))
                levels.append(abs(signal) / len(samples))
            self.assertLess(levels[1], levels[0] * .7, levels)


if __name__ == '__main__':
    unittest.main()

