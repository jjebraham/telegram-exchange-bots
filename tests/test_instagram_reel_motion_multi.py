import ast
import importlib.util
import sys
import tempfile
import types
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from PIL import Image

import os
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT
sys.path.insert(0, str(ROOT))
try:
    import fcntl
except ImportError:
    sys.modules['fcntl'] = types.ModuleType('fcntl')
ASSETS = Path(os.environ.get('KIANI_TEST_ASSETS', str(ROOT)))
spec = importlib.util.spec_from_file_location('reel_check', OUT/'instagram_trial_reels.py')
trial = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = trial
spec.loader.exec_module(trial)
import instagram_reel_motion as motion

class MultiImageChecks(unittest.TestCase):
    def test_candidates_are_bounded_and_inside_article_figures(self):
        source = (OUT/'crypto_news_trial.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        node = next(n for n in tree.body if getattr(n, 'name', '') == 'ReelArticleFigures')
        scope = {'HTMLParser': HTMLParser}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'figures', 'exec'), scope)
        parser = scope['ReelArticleFigures']()
        parser.feed('<img src="/outside.jpg"><article>' +
                    ''.join(f'<figure><img data-lazy-src="/photo{i}.jpg"></figure>' for i in range(20)) +
                    '</article>')
        self.assertEqual(len(parser.urls), 16)
        self.assertEqual(parser.urls[0], '/photo0.jpg')

    def test_eight_images_reach_opening_and_story_cards(self):
        colors = [(30+i*25, 50+i*15, 70+i*10) for i in range(8)]
        captured = []
        with tempfile.TemporaryDirectory(dir=OUT) as tmp:
            folder = Path(tmp)
            media = []
            for i, color in enumerate(colors):
                path = folder/f'photo{i}.png'
                Image.new('RGB', (888, 500), color).save(path)
                media.append({'path':path, 'kind':'publisher'})
            trial.STATE = folder
            original_save = Image.Image.save
            def capture_frame(image, path, *args, **kwargs):
                if str(path).endswith('.jpg') and 'kiani-motion-' in str(path):
                    captured.append(image.getpixel((500, 500)))
                    return
                return original_save(image, path, *args, **kwargs)
            chunks = ['در این نمونه خبر آزمایشی برای نمایش تصویر آماده شده است.',
                      'در ادامه اطلاعات دیگری درباره بازار و شرایط ارائه می‌شود.']
            with patch.object(Image.Image, 'save', capture_frame), patch.object(motion.subprocess, 'run'):
                motion.render(trial, 'یک خبر آزمایشی درباره بازار', 'منبع آزمایشی',
                              'crypto', 'hard_news', chunks, folder/'unused.mp4',
                              ASSETS, media, None, 'ffmpeg')
        self.assertEqual(captured[0], colors[0])
        self.assertEqual(captured[24], colors[1])
        for color in colors:
            self.assertIn(color, captured)

if __name__ == '__main__':
    unittest.main()



