import unittest

import instagram_trial_music as music


class MusicMatchingTests(unittest.TestCase):
    def test_security_and_sanctions_are_not_treated_as_celebrations(self):
        for story in (
            {'title_original': 'Hackers stole funds while Bitcoin price surged'},
            {'title_fa': 'آمریکا تحریم‌های جدید را اعلام کرد'},
            {'title_fa': 'هکرها به صرافی حمله کردند'},
        ):
            with self.subTest(story=story):
                self.assertEqual(music.classify_story(story)['mood'], 'tense')
                self.assertIn('tense', music.select_order(story)[0]['moods'])

    def test_partnership_or_approval_uses_uplifting_mood(self):
        story = {'title_original': 'Bank partnership receives regulatory approval'}
        self.assertEqual(music.classify_story(story)['mood'], 'uplifting')
        self.assertIn('uplifting', music.select_order(story)[0]['moods'])

    def test_headline_is_prioritized_over_old_background_events(self):
        story = {'title_original': 'Bank partnership receives approval',
                 'summary_original': 'A separate hack occurred years ago.'}
        result = music.classify_story(story)
        self.assertEqual(result['mood'], 'uplifting')
        self.assertEqual(result['source'], 'headline')

    def test_rising_and_easing_inflation_are_distinguished(self):
        self.assertEqual(music.classify_story({'title_original': 'Inflation rises as energy costs increase'})['mood'], 'tense')
        self.assertEqual(music.classify_story({'title_fa': 'نرخ تورم کاهش یافت'})['mood'], 'uplifting')

    def test_generic_crypto_terms_and_substrings_do_not_imply_tension(self):
        for headline in ('Bitcoin market price update', 'Market reward program'):
            with self.subTest(headline=headline):
                self.assertIsNone(music.classify_story({'title_original': headline})['mood'])
        generic = music.select_order({'title_original': 'Bitcoin market price update'})
        self.assertNotIn(generic[0]['name'], music._PLAYFUL_TITLES)

    def test_mood_match_is_prioritized_over_unrelated_unplayed_tracks(self):
        recent = [track['title'] for track in music.TRACKS if 'tense' in track['moods']]
        order = music.select_order({'title_original': 'Exchange hack investigation'}, recent)
        self.assertIn('tense', order[0]['moods'])
        self.assertEqual(len(order), 100)

    def test_recent_track_is_avoided_within_matching_mood(self):
        story = {'title_original': 'Exchange hack investigation'}
        first = music.select_order(story)[0]
        second = music.select_order(story, [first['title']])[0]
        self.assertNotEqual(first['title'], second['title'])
        self.assertIn('tense', second['moods'])


if __name__ == '__main__':
    unittest.main()

