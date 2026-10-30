import sys
import unittest
import tempfile
import types
import wave
from unittest.mock import patch
from pathlib import Path
from PIL import Image, ImageDraw, ImageChops

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import instagram_reel_motion as motion
import instagram_trial_music as music
import importlib.util
try:
    import fcntl
except ImportError:
    sys.modules['fcntl']=types.ModuleType('fcntl')
spec=importlib.util.spec_from_file_location('voice_test_reel',ROOT/'instagram_trial_reels.py')
reel=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=reel
spec.loader.exec_module(reel)

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

    def test_voice_timeline_is_mixed_with_music_and_typing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            reel.STATE=root
            segments=[]
            for i in range(3):
                p=root/('voice'+str(i)+'.wav')
                with wave.open(str(p),'wb') as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                    w.writeframes(b'\x10\x10'*24000)
                segments.append({'path':p,'duration':1.0})
            media=[]
            for i,color in enumerate(('red','blue')):
                p=root/('image'+str(i)+'.jpg')
                Image.new('RGB',(888,500),color).save(p)
                media.append({'path':p,'kind':'illustrative'})
            assets=Path(__import__('os').environ.get('KIANI_TEST_ASSETS',str(ROOT)))
            seen=[]
            def run(cmd,**kwargs):
                self.assertIn('amix=inputs=3',cmd[cmd.index('-filter_complex')+1])
                p=Path(cmd[cmd.index('-filter_complex')-1])
                with wave.open(str(p),'rb') as sound:
                    self.assertGreater(sound.getnframes(),24000*10)
                    self.assertNotEqual(sound.readframes(100),b'\x00'*200)
                seen.append(True)
            with patch.object(motion.subprocess,'run',side_effect=run):
                motion.render(reel,'عنوان خبر آزمایشی','منبع','crypto','hard_news',
                  ['متن اول این آزمایش برای خواندن خبر است.','متن دوم آزمایش برای ادامه است.'],
                  root/'out.mp4',assets,media,None,'ffmpeg',narration=segments)
            self.assertEqual(seen,[True])

if __name__=='__main__': unittest.main()
