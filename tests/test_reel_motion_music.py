import sys
import json
import ast
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
    def test_publisher_and_activation_do_not_require_azure_narration(self):
        source = (ROOT/'instagram_trial_reels.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        publisher = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'create_reel')
        self.assertFalse(any(isinstance(n, ast.ImportFrom) and n.module == 'instagram_reel_voice'
                             for n in ast.walk(publisher)))
        calls = [n for n in ast.walk(publisher) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == 'render_video']
        self.assertEqual(len(calls), 1)
        self.assertFalse(any(k.arg == 'narration' for k in calls[0].keywords))
        activation = (ROOT/'deploy/instagram-trial-reels/activate_trial_reels.py').read_text(encoding='utf-8')
        self.assertNotIn('instagram_reel_voice', activation)

    def test_without_narration_mix_contains_music_and_typing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            reel.STATE=root
            music_path=root/'music.ogg'
            music_path.write_bytes(b'synthetic')
            assets=Path(__import__('os').environ.get('KIANI_TEST_ASSETS',str(ROOT)))
            checked=[]
            def run(cmd,**kwargs):
                self.assertIn(str(music_path),cmd)
                self.assertIn('amix=inputs=2',cmd[cmd.index('-filter_complex')+1])
                self.assertNotIn('narration.wav', ' '.join(cmd))
                checked.append(True)
            with patch.object(motion.subprocess,'run',side_effect=run):
                motion.render(reel,'عنوان خبر آزمایشی','منبع','crypto','hard_news',
                  ['متن اول این آزمایش برای خواندن خبر است.', 'متن دوم برای ادامه است.'],
                  root/'out.mp4',assets,[],music_path,'ffmpeg')
            self.assertEqual(checked,[True])

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
                    sound.setpos(round(.24*sound.getframerate()))
                    self.assertNotEqual(sound.readframes(100),b'\x00'*200)
                seen.append(True)
            with patch.object(motion.subprocess,'run',side_effect=run):
                motion.render(reel,'عنوان خبر آزمایشی','منبع','crypto','hard_news',
                  ['متن اول این آزمایش برای خواندن خبر است.','متن دوم آزمایش برای ادامه است.'],
                  root/'out.mp4',assets,media,None,'ffmpeg',narration=segments)
            self.assertEqual(seen,[True])

    def test_long_narration_and_video_probe_allow_over_one_minute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            reel.STATE=root
            narration=[]
            for i, seconds in enumerate((2,35,35)):
                path=root/('long-voice'+str(i)+'.wav')
                with wave.open(str(path),'wb') as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                    w.writeframes(b'\x00\x00'*(24000*seconds))
                narration.append({'path':path,'duration':seconds})
            assets=Path(__import__('os').environ.get('KIANI_TEST_ASSETS',str(ROOT)))
            def check_run(cmd,**kwargs):
                with wave.open(cmd[cmd.index('-filter_complex')-1],'rb') as w:
                    self.assertGreater(w.getnframes()/w.getframerate(),60)
            with patch.object(motion.subprocess,'run',side_effect=check_run):
                motion.render(reel,'نمونه خبر','منبع','crypto','hard_news',
                    ['این یک بخش خبری است.','این بخش دیگری از خبر است.'],
                    root/'out.mp4',assets,[],None,'ffmpeg',narration=narration)
        data={'streams':[{'codec_name':'h264','width':1080,'height':1920,'pix_fmt':'yuv420p'},
                         {'codec_name':'aac','sample_rate':'48000','channels':2}],
              'format':{'duration':'80'}}
        with patch.object(reel.subprocess,'run',return_value=types.SimpleNamespace(stdout=json.dumps(data))):
            self.assertEqual(reel._probe_video('test.mp4','ffprobe'),80)
        data['format']['duration']='181'
        with patch.object(reel.subprocess,'run',return_value=types.SimpleNamespace(stdout=json.dumps(data))):
            with self.assertRaises(reel.TrialReelError):
                reel._probe_video('test.mp4','ffprobe')

if __name__=='__main__': unittest.main()
