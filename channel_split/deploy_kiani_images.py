"""Guarded installation of Kiani image presentation; text stays the default."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

BUILDERS = {'build_kiani_rate_post': 'kiani-rates', 'build_kiani_try_post': 'kiani-try',
            'build_kiani_try_receive_post': 'kiani-examples',
            'build_kiani_toman_receive_post': 'kiani-examples-reverse'}
IMPORT = 'from kiani_images import KIANI_IMAGE_POSTS, render_kiani_png\n\n'
BRANCH = '''            # Kiani customer image delivery v1
            if (
                destination_env == "KIANI_CHANNEL_ID"
                and post_key in KIANI_IMAGE_POSTS
                and os.environ.get("KIANI_POST_FORMAT", "text").lower() == "image"
            ):
                import tempfile
                from market_images import telegram_send_photo
                with tempfile.TemporaryDirectory(prefix="kiani-customer-image-") as temp:
                    image_path = Path(temp) / f"{post_key}.png"
                    render_kiani_png(post_key, text, image_path)
                    send_result = telegram_send_photo(
                        token, chat_id, image_path, "", caption_style="links",
                    )
'''


def assign_keys(source: bytes) -> bytes:
    tree = ast.parse(source.decode('utf-8'))
    lines = source.splitlines(keepends=True)
    edits = []
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'add_kiani' or not node.args:
            continue
        value = node.args[0]
        if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name) or value.func.id not in BUILDERS:
            continue
        builder = value.func.id
        if builder in found or len(node.args) not in (1, 2) or node.keywords:
            raise ValueError('Unexpected or repeated Kiani formatter job')
        found.add(builder)
        key = BUILDERS[builder]
        if len(node.args) == 2:
            if not isinstance(node.args[1], ast.Constant) or node.args[1].value != key:
                raise ValueError('Unexpected Kiani image post key')
        else:
            position = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset - 1
            if source[position:position + 1] != b')':
                raise ValueError('Unexpected Kiani job closing token')
            arg_end = sum(map(len, lines[:value.end_lineno - 1])) + value.end_col_offset
            gap = source[arg_end:position]
            if gap.strip() not in (b'', b','):
                raise ValueError('Unexpected text after Kiani formatter call')
            if node.end_lineno > value.end_lineno:
                newline = b'\r\n' if b'\r\n' in source else b'\n'
                if gap.strip():
                    position = arg_end + gap.index(b',') + 1
                    prefix = b''
                else:
                    position, prefix = arg_end, b','
                insertion = prefix + newline + b' ' * (node.col_offset + 4) + json.dumps(key).encode('ascii') + b','
            else:
                insertion = ((' ' if gap.strip() else ', ') + json.dumps(key)).encode('ascii')
            edits.append((position, insertion))
    if found != set(BUILDERS):
        raise ValueError('Expected all four existing Kiani producer jobs')
    for position, insertion in sorted(edits, reverse=True):
        source = source[:position] + insertion + source[position:]
    return source


def patch_publisher(original: bytes) -> bytes:
    changed = assign_keys(original)
    newline = '\r\n' if b'\r\n' in original else '\n'
    if newline == '\r\n' and b'\n' in original.replace(b'\r\n', b''):
        raise ValueError('Mixed publisher line endings require review')
    source = changed.decode('utf-8').replace('\r\n', '\n')
    if IMPORT in source or '# Kiani customer image delivery v1' in source:
        if source.count(IMPORT) != 1 or source.count(BRANCH) != 1:
            raise ValueError('Installed Kiani image integration differs from the reviewed version')
        return changed
    anchor = 'DEFAULT_RATES_URL = "https://miniapp.kiani.exchange/api/rates/current"'
    if source.count(anchor) != 1:
        raise ValueError('Unexpected publisher import anchor')
    source = source.replace(anchor, IMPORT + anchor, 1)
    alan = '            if (\n                destination_env == "ALANCHANDE_CHANNEL_ID"\n'
    raw = '            send_result = telegram_send(token, chat_id, text)'
    if source.count(alan) == 1:
        source = source.replace(alan, BRANCH + alan.replace('            if (', '            elif (', 1), 1)
    elif source.splitlines().count(raw) == 1:
        source = source.replace('\n' + raw + '\n', '\n' + BRANCH + '            else:\n    ' + raw + '\n', 1)
    else:
        raise ValueError('Unexpected publisher send anchor')
    ast.parse(source)
    return source.replace('\n', newline).encode('utf-8')


def atomic(path: Path, blob: bytes, mode: int) -> None:
    fd, name = tempfile.mkstemp(prefix='.kiani-image-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(blob)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', type=Path, default=Path.home() / 'telegram_bot_repo')
    parser.add_argument('--backup-dir', type=Path, default=Path.home() / 'kiani-image-backups')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    folder = args.repo.resolve() / 'channel_split'
    publisher = folder / 'publish_channels.py'
    original = publisher.read_bytes()
    changed = patch_publisher(original)
    root = Path(__file__).resolve().parent
    sources = {name: (root / name).read_bytes() for name in
               ('kiani_images.py', 'kiani_image_assets/kiani-logo.svg', 'kiani_image_assets/SOURCES.md')}
    compile(sources['kiani_images.py'], 'kiani_images.py', 'exec')
    if not (folder / 'market_images.py').is_file() or not (folder / 'kiani_posts.py').is_file():
        raise SystemExit('Existing renderer helpers or pricing formatters are unavailable')
    if 'caption_style' not in (folder / 'market_images.py').read_text(encoding='utf-8'):
        raise SystemExit('Current photo delivery helper is required')
    if changed == original and all((folder / name).is_file() and (folder / name).read_bytes() == blob for name, blob in sources.items()):
        print('ALREADY INSTALLED: exact Kiani image integration and artwork')
        return 0
    if not args.apply:
        print('DRY RUN: four Kiani jobs and image-send integration validated; pricing functions preserved')
        return 0
    if publisher.is_symlink() or not stat.S_ISREG(publisher.stat().st_mode):
        raise SystemExit('Unexpected publisher file type')
    if publisher.read_bytes() != original:
        raise SystemExit('Publisher changed during preparation')
    backup = args.backup_dir / ('kiani-images-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True, exist_ok=False)
    os.chmod(backup, 0o700)
    files = {'publish_channels.py': changed, **sources}
    before = {}
    for name in files:
        target = folder / name
        if target.is_symlink():
            raise SystemExit('Unexpected target symlink')
        before[name] = target.read_bytes() if target.exists() else None
        if target.exists():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
            os.chmod(saved, 0o600)
    manifest = {name: {'before': hashlib.sha256(blob).hexdigest() if blob is not None else None,
                       'after': hashlib.sha256(files[name]).hexdigest()} for name, blob in before.items()}
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for name, blob in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
        atomic(target, blob, mode)
    print('INSTALLED: four Kiani image templates; KIANI_POST_FORMAT still defaults to text')
    print('BACKUP:', backup)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
