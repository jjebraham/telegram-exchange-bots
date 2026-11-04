"""Offline music licensing, rotation, and file verification checks."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import instagram_trial_music as music


class MusicPoolTest(unittest.TestCase):
    def test_pool_has_one_hundred_distinct_reviewed_entries(self):
        self.assertEqual(len(music.TRACKS), 100)
        self.assertEqual(len({track['title'] for track in music.TRACKS}), 100)
        self.assertEqual(len({track['sha1'] for track in music.TRACKS}), 100)
        self.assertTrue(all(track.get('license', 'CC BY 4.0') in music.LICENSE_URLS for track in music.TRACKS))

    def test_rotation_avoids_last_fifty_and_prioritizes_relevant_mood(self):
        previous = [track['title'] for track in music.TRACKS[:50]]
        order = music.select_order({'title_original': 'Bitcoin hack under investigation'}, previous)
        self.assertNotIn(order[0]['title'], previous)
        self.assertIn('tense', order[0]['moods'])
        self.assertEqual({item['title'] for item in order}, {item['title'] for item in music.TRACKS})

    def test_mp3_license_and_required_credit(self):
        track = next(item for item in music.TRACKS if item.get('mime') == 'audio/mpeg'
                     and item.get('license') == 'CC BY 3.0' and 'audionautix.com' in item.get('credit', ''))
        sample = b'ID3' + b'a' * 1100
        track = dict(track, sha1=hashlib.sha1(sample).hexdigest())
        info = {'sha1':track['sha1'], 'mime':'audio/mpeg', 'size':len(sample), 'duration':90,
                'url':'https://upload.wikimedia.org/fake.mp3',
                'descriptionurl':'https://commons.wikimedia.org/wiki/'+track['title'].replace(' ','_'),
                'extmetadata':{'LicenseShortName':{'value':'CC BY 3.0'},
                    'LicenseUrl':{'value':music.LICENSE_URLS['CC BY 3.0']},
                    'Artist':{'value':track['artist']}}}
        page = {'title':track['title'], 'categories':[{'title':'Category:CC-BY-3.0'}], 'imageinfo':[info]}
        api = json.dumps({'query':{'pages':{'1':page}}}).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(music, '_read', side_effect=[api, sample]):
            result = music.retrieve_track(track, Path(directory)/'audio')
        credit = music.caption_credit(result)
        self.assertIn('music by audionautix.com', credit)
        self.assertIn('CC BY 3.0', credit)

    def test_rejects_flagged_or_wrong_license(self):
        track = music.TRACKS[0]
        page = {'title':track['title'], 'categories':[{'title':'Category:License review needed (audio)'}]}
        api = json.dumps({'query':{'pages':{'1':page}}}).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(music, '_read', return_value=api):
            with self.assertRaises(ValueError):
                music.retrieve_track(track, Path(directory)/'audio')


if __name__ == '__main__':
    unittest.main()

