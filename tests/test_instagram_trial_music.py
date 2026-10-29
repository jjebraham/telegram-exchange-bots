import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import instagram_trial_music as music


class MusicValidation(unittest.TestCase):
    def setUp(self):
        self.audio = b'OggS' + b'preview audio bytes' * 100
        self.track = dict(title='File:Sample.ogg', name='Sample', mood='tense', sha1=hashlib.sha1(self.audio).hexdigest())
        self.info = dict(sha1=self.track['sha1'], mime='application/ogg', size=len(self.audio), duration=90,
            url='https://upload.wikimedia.org/wikipedia/commons/a/a0/Sample.ogg',
            descriptionurl='https://commons.wikimedia.org/wiki/File:Sample.ogg',
            extmetadata={'LicenseShortName': {'value': 'CC BY 4.0'},
                'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by/4.0'},
                'Artist': {'value': '<a>Rafael Krux</a>'}, 'Restrictions': {'value': ''}})

    def response(self):
        return json.dumps({'query': {'pages': {'1': {'title': self.track['title'], 'imageinfo': [self.info]}}}}).encode()

    def test_verified_track_is_downloaded_and_credited(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(music, '_read', side_effect=[self.response(), self.audio]):
            path = Path(tmp) / 'track.ogg'
            info = music.retrieve_track(self.track, path)
            self.assertEqual(path.read_bytes(), self.audio)
            credit = music.caption_credit(info)
            self.assertIn('Rafael Krux', credit)
            self.assertIn('creativecommons.org/licenses/by/4.0/', credit)
            self.assertIn('shortened and faded', credit)

    def test_bad_license_prevents_audio_download(self):
        self.info['extmetadata']['LicenseShortName']['value'] = 'CC BY-NC 4.0'
        with tempfile.TemporaryDirectory() as tmp, patch.object(music, '_read', return_value=self.response()) as read:
            with self.assertRaises(ValueError):
                music.retrieve_track(self.track, Path(tmp) / 'track.ogg')
            self.assertEqual(read.call_count, 1)

    def test_corrupted_audio_and_untrusted_host_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(music, '_read', side_effect=[self.response(), self.audio + b'x']):
            with self.assertRaises(ValueError):
                music.retrieve_track(self.track, Path(tmp) / 'track.ogg')
        self.info['url'] = 'https://example.com/sample.ogg'
        with tempfile.TemporaryDirectory() as tmp, patch.object(music, '_read', return_value=self.response()) as read:
            with self.assertRaises(ValueError):
                music.retrieve_track(self.track, Path(tmp) / 'track.ogg')
            self.assertEqual(read.call_count, 1)

    def test_story_mood_and_previous_track_affect_choice(self):
        order = music.select_order({'title_original': 'Security breach raises losses'})
        self.assertEqual(order[0]['mood'], 'tense')
        self.assertEqual(music.select_order({'title_original': 'Security breach'}, order[0]['title'])[0]['mood'], 'tense')


if __name__ == '__main__':
    unittest.main()

