from pathlib import Path
import tempfile
import types
import unittest

from PIL import Image
import reel_preview_images as images


class PreviewImageTests(unittest.TestCase):
    def test_stock_and_commons_are_used_and_credits_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            def fetch(engine, article, url, path, timeout):
                Image.new('RGB', (320, 180), 'red').save(path, 'JPEG')
            def stock(story, folder, *, origin, state, limit):
                calls.append(('stock', origin, story['title_original']))
                path = folder / 'stock.jpg'
                Image.new('RGB', (320, 180), 'blue').save(path, 'JPEG')
                return [{'path': path, 'kind': 'illustrative', 'provider': 'pixabay',
                         'author': 'Photographer', 'source_url': 'https://pixabay.com/photo/example/'}]
            def commons(story, folder, *, limit):
                calls.append(('commons', limit))
                path = folder / 'commons.jpg'
                Image.new('RGB', (320, 180), 'green').save(path, 'JPEG')
                return [{'path': path, 'kind': 'illustrative', 'title': 'Example', 'author': 'Artist',
                         'license': 'CC BY 4.0', 'license_url': 'https://creativecommons.org/licenses/by/4.0/',
                         'source_url': 'https://commons.wikimedia.org/wiki/File:Example.jpg'}]
            row = {'title_fa': 'خبر', 'summary_fa': 'متن خبر', 'kind': 'crypto'}
            material = {'title_original': 'Bitcoin news', 'source_url': 'https://example.com/a',
                        'image_urls': ['https://example.com/photo.jpg']}
            result = images.collect(row, material, root / 'images', object(), types.SimpleNamespace(fetch=fetch),
                                    state=root, stock_collector=stock, commons_collector=commons)
            self.assertEqual(len(result), 3)
            self.assertEqual(calls[0], ('stock', 'admin_direct', 'Bitcoin news'))
            credits = images.image_credits(result)
            self.assertIn('Pixabay: Photographer', credits)
            self.assertIn('CC BY 4.0', credits)
            self.assertIn('Artist', credits)

    def test_visually_duplicate_images_are_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def fetch(engine, article, url, path, timeout):
                Image.new('RGB', (320, 180), 'red').save(path, 'JPEG', quality=90)
            def stock(story, folder, *, origin, state, limit):
                path = folder / 'duplicate.jpg'
                Image.new('RGB', (320, 180), 'red').save(path, 'JPEG', quality=75)
                return [{'path': path, 'kind': 'illustrative', 'provider': 'pixabay',
                         'author': 'Photographer', 'source_url': 'https://pixabay.com/photo/example/'}]
            material = {'source_url': 'https://example.com/a', 'image_urls': ['https://example.com/photo.jpg']}
            result = images.collect({'kind': 'crypto'}, material, root / 'images', object(),
                                    types.SimpleNamespace(fetch=fetch), state=root, stock_collector=stock,
                                    commons_collector=lambda *args, **kwargs: [])
            self.assertEqual(len(result), 1)

    def test_missing_publisher_image_does_not_use_unrelated_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def fail(*args, **kwargs):
                raise ValueError('No verified source image')
            result = images.collect({'kind': 'crypto'}, {'source_url': 'https://example.com',
                                    'image_urls': ['https://example.com/a']}, Path(tmp) / 'images',
                                    object(), types.SimpleNamespace(fetch=fail), state=Path(tmp),
                                    stock_collector=lambda *args, **kwargs: calls.append('stock'),
                                    commons_collector=lambda *args, **kwargs: calls.append('commons'))
            self.assertEqual(result, [])
            self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
