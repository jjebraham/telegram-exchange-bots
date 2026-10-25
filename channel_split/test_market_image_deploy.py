"""Exercise guarded installation/upgrades against disposable publisher copies."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class DeploymentTests(unittest.TestCase):
    def test_install_idempotency_and_guarded_renderer_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'repository'
            folder = repo / 'channel_split'
            folder.mkdir(parents=True)
            publisher = folder / 'publish_channels.py'
            publisher.write_bytes((ROOT / 'publish_channels.py').read_bytes())
            before = publisher.read_bytes()
            backup = Path(directory) / 'backups'

            def run(*flags):
                return subprocess.run([sys.executable, str(ROOT / 'deploy_market_images.py'),
                                       '--repo', str(repo), '--backup-dir', str(backup), *flags],
                                      capture_output=True, text=True, timeout=20)

            self.assertEqual(run().returncode, 0)
            self.assertEqual(publisher.read_bytes(), before)
            self.assertFalse(backup.exists())
            installed = run('--apply')
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertTrue((folder / 'market_image_assets/vazirmatn.ttf').is_file())
            self.assertTrue((folder / 'market_image_assets/flags/LICENSE.txt').is_file())
            self.assertTrue((folder / 'market_image_assets/flags/qa.svg').is_file())
            self.assertEqual((folder / 'market_report_templates.py').read_bytes(),(ROOT / 'market_report_templates.py').read_bytes())
            patched = publisher.read_bytes()
            self.assertIn(b'ALANCHANDE_POST_FORMAT', patched)
            self.assertEqual(run('--apply').returncode, 0)
            renderer = folder / 'market_images.py'
            renderer.write_text('# old renderer\n', encoding='utf-8')
            self.assertNotEqual(run('--apply').returncode, 0)
            upgraded = run('--upgrade-renderer', '--apply')
            self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
            self.assertEqual(publisher.read_bytes(), patched)
            self.assertEqual(renderer.read_bytes(), (ROOT / 'market_images.py').read_bytes())
            publisher.write_text(publisher.read_text(encoding='utf-8').replace('preview_dir = os.environ', 'changed_dir = os.environ'), encoding='utf-8')
            self.assertNotEqual(run('--upgrade-renderer', '--apply').returncode, 0)


if __name__ == '__main__':
    unittest.main()
