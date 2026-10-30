import sys
import unittest
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import instagram_reel_motion as motion
import instagram_trial_music as music

class MotionMusicChecks(unittest.TestCase):
    def test_photo_moves_and_diagram_remains_visible(self):
        image=Image.new('RGB',(1000,600),'white')
        draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,200,600),fill='red')
        a=motion.moving_image(image,0,1,(888,500),'black')
        b=motion.moving_image(image,1,1,(888,500),'black')
        self.assertIsNotNone(ImageChops.difference(a,b).getbbox())
        diagram=Image.new('RGB',(300,1000),'white')
        ImageDraw.Draw(diagram).rectangle((0,0,299,50),fill='red')
        panel=motion.moving_image(diagram,.5,0,(888,500),'black')
        self.assertGreater(sum(1 for pixel in panel.getdata() if pixel==(255,0,0)),100)

    def test_avoids_recent_tracks_before_reusing_them(self):
        recent=[track['title'] for track in music.TRACKS[:10]]
        ordered=music.select_order({'title_original':'Bitcoin breach'},recent)
        self.assertTrue(all(track['title'] not in recent for track in ordered[:10]))
        self.assertEqual(len(ordered),len(music.TRACKS))
        self.assertNotEqual(music.select_order({}, music.TRACKS[0]['title'])[0]['title'],music.TRACKS[0]['title'])

if __name__=='__main__': unittest.main()
