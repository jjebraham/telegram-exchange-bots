#!/usr/bin/env python3
"""Extract the pinned Trial/Direct Reel runtime and optionally activate it."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

FILES = (
    'instagram_manual_news_intake.py',
    'instagram_news_slide_images.py',
    'test_intake_menu.py',
    'test_news_slide_images.py',
    'instagram_news_menu.py',
    'instagram_trial_reels.py',
    'instagram_direct_reel_retention.py',
    'instagram_trial_music.py',
    'test_trial_music.py',
    'deploy/instagram-trial-reels/check_music_pool.py',
    'instagram_reel_usage.py',
    'report_reel_usage.py',
    'instagram_reel_media.py',
    'instagram_reel_commons.py',
    'instagram_reel_stock.py',
    'instagram_reel_source_image.py',
    'instagram_reel_motion.py',
    'voice_review/reel_narration_timing.py',
    'voice_review/reel_persian_pronunciation.py',
    'voice_review/check_pronunciation.py',
    'voice_review/test_reel_pronunciation.py',
    'voice_review/test_persian_news_editing.py',
    'voice_review/test_reel_schedule_policy.py',
    'voice_review/test_reel_translation_recovery.py',
    'voice_review/reel_elevenlabs.py',
    'voice_review/reel_audio_mix.py',
    'voice_review/reel_voice_registry.py',
    'voice_review/reel_voice_discovery.py',
    'voice_review/reel_voice_review.py',
    'voice_review/reel_voice_samples.py',
    'voice_review/reel_voice_telegram.py',
    'voice_review/reel_voice_tool.py',
    'voice_review/reel_voice_credentials.py',
    'voice_review/reel_local_settings.py',
    'voice_review/reel_narration_usage.py',
    'voice_review/reel_voice_performance.py',
    'voice_review/check_local_voice.py',
    'voice_review/test_reel_local_release.py',
    'voice_review/LOCAL-VOICE-ROLLOUT.md',
    'voice_review/test_reel_voice_credentials.py',
    'voice_review/test_music_match.py',
    'voice_review/preview_voice_reel.py',
    'voice_review/reel_preview_images.py',
    'voice_review/test_reel_preview_images.py',
    'voice_review/runpod_audit.py',
    'voice_review/test_runpod_audit.py',
    'voice_review/runpod_inspect.py',
    'voice_review/test_runpod_inspect.py',
    'voice_review/runpod_guard.py',
    'voice_review/test_runpod_guard.py',
    'voice_review/runpod_local_readiness.py',
    'voice_review/test_runpod_local_readiness.py',
    'voice_review/runpod_api_client.py',
    'voice_review/test_runpod_api_client.py',
    'voice_review/runpod_lease_store.py',
    'voice_review/test_runpod_lease_store.py',
    'voice_review/runpod_timer_probe.py',
    'voice_review/test_runpod_timer_probe.py',
    'voice_review/runpod_watchdog.py',
    'voice_review/test_runpod_watchdog.py',
    'voice_review/runpod_crash_probe.py',
    'voice_review/test_runpod_crash_probe.py',
    'voice_review/runpod_worker_lock.py',
    'voice_review/test_runpod_worker_lock.py',
    'voice_review/runpod_manager.py',
    'voice_review/test_runpod_manager.py',
    'voice_review/runpod_supervisor.py',
    'voice_review/test_runpod_supervisor.py',
    'voice_review/runpod_secrets.py',
    'voice_review/test_runpod_secrets.py',
    'voice_review/configure_runpod.py',
    'voice_review/test_runpod_configure.py',
    'voice_review/runpod_watchdog_service.py',
    'voice_review/test_runpod_watchdog_service.py',
    'voice_review/install_runpod_watchdog.py',
    'voice_review/test_runpod_watchdog_installer.py',
    'voice_review/test_runpod_recovery.py',
    'voice_review/upgrade_runpod_watchdog.py',
    'voice_review/test_runpod_watchdog_upgrade.py',
    'voice_review/runpod_systemd_guard.py',
    'voice_review/test_runpod_systemd_guard.py',
    'voice_review/runpod_api_probe.py',
    'voice_review/test_runpod_api_probe.py',
    'voice_review/runpod_supervision_probe.py',
    'voice_review/test_runpod_supervision_probe.py',
    'voice_review/test_reel_narration_timing.py',
    'voice_review/test_reel_elevenlabs.py',
    'voice_review/test_reel_audio_mix.py',
    'voice_review/test_reel_voice_registry.py',
    'voice_review/test_reel_voice_discovery.py',
    'voice_review/test_trial_voice_integration.py',
    'voice_review/test_private_voice_preview.py',
    'instagram_ranked_news.py',
    'crypto_news_trial.py',
    'instagram_news_batch.py',
    'instagram_insights_data.py',
    'instagram_news_retention.py',
    'selector_trial_runtime/economy_news_picker.py',
    'selector_trial_runtime/economy_news_translation.py',
    'selector_trial_runtime/instagram_crypto_news.py',
    'selector_trial_runtime/instagram_news_renderer.py',
    'selector_trial_runtime/PINNED.md',
    'deploy/instagram-trial-reels/activate_trial_reels.py',
    'deploy/instagram-trial-reels/check_reel_schedule.py',
    'deploy/instagram-trial-reels/check_multi_images.py',
    'deploy/instagram-trial-reels/check_auto_images.py',
    'deploy/instagram-trial-reels/configure_stock.py',
    'deploy/instagram-trial-reels/check_reel_motion.py',
    'deploy/instagram-trial-reels/check_reel_cover.py',
    'deploy/instagram-trial-reels/check_news_menu.py',
    'deploy/instagram-trial-reels/check_admin_layout.py',
    'deploy/instagram-trial-reels/check_slide_images.py',
    'deploy/instagram-trial-reels/check_live_slide_images.py',
    'deploy/instagram-trial-reels/automatic_ranked_news_images.py',
    'deploy/instagram-trial-reels/activate_auto_news_images.py',
    'deploy/instagram-trial-reels/check_auto_news_images.py',
    'deploy/instagram-trial-reels/test_auto_news_images.py',
    'deploy/instagram-trial-reels/test_auto_news_installer.py',
    'deploy/instagram-trial-reels/check_reel_long_news.py',
    'deploy/instagram-trial-reels/check_blockchain_news.py',
    'deploy/instagram-trial-reels/check_scheduler_lock.py',
    'deploy/instagram-trial-reels/TRIAL-REELS.md',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the existing Instagram publisher user, without sudo.')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('Supply the exact reviewed revision.')
    os.umask(0o077)
    home = Path.home()
    if shutil.disk_usage(home).free < 256 * 1024**2:
        raise RuntimeError('At least 256 MiB free is required for safe rendering and state writes.')
    repo = args.repo.expanduser().resolve()
    sources, size = {}, 0
    for name in FILES:
        spec = args.revision + ':' + name
        length = int(subprocess.check_output(['git', '-C', str(repo), 'cat-file', '-s', spec], timeout=20))
        size += length
        if length <= 0 or size > 4 * 1024**2:
            raise RuntimeError('Pinned source extraction exceeded its size limit.')
        sources[name] = subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', spec], timeout=20)
        if len(sources[name]) != length:
            raise RuntimeError('A pinned source file changed size during extraction.')
    root = home / '.local/state/kiani-instagram-manual-news/source' / args.revision
    if root.is_symlink():
        raise RuntimeError('The pinned runtime directory is unsafe.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    for name, data in sources.items():
        path = root / name
        if path.is_symlink() or path.exists() and path.read_bytes() != data:
            raise RuntimeError('An existing pinned source file differs; no overwrite performed.')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            with path.open('xb') as handle:
                handle.write(data)
            path.chmod(0o600)
    print(f'Extracted/verified {len(FILES)} files ({size / 1024:.1f} KiB); no repository checkout.', flush=True)
    if args.install:
        python = home / 'kiani-instagram-venv/bin/python'
        command = [str(python), '-u', str(root / 'deploy/instagram-trial-reels/activate_trial_reels.py'),
                   '--runtime', str(root), '--revision', args.revision]
        env = dict(os.environ, PYTHONIOENCODING='utf-8', TZ='Europe/Istanbul')
        return subprocess.run(command, check=False, cwd=root, env=env).returncode
    print('Runtime prepared only. Add --install to activate /trial, /reel and their daily schedules.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}' if isinstance(exc, RuntimeError) else
              f'Instagram Reel setup stopped ({type(exc).__name__}).', file=sys.stderr)
        raise SystemExit(1)







