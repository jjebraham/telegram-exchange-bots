"""Use the production image collectors for a private, attributed preview."""
import hashlib
from pathlib import Path
from PIL import Image, ImageOps


def _signature(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError('Preview image is unavailable or unsafe.')
    raw = path.read_bytes()
    with Image.open(path) as image:
        if image.width < 256 or image.height < 128 or image.width * image.height > 40_000_000:
            raise ValueError('Preview image dimensions are invalid.')
        small = ImageOps.fit(ImageOps.exif_transpose(image).convert('RGB'), (16, 16), Image.Resampling.LANCZOS)
        signature = small.tobytes()
    return hashlib.sha256(raw).hexdigest(), signature


def _different(signature, seen):
    digest, pixels = signature
    for prior_digest, prior_pixels in seen:
        if digest == prior_digest:
            return False
        if sum(abs(a - b) for a, b in zip(pixels, prior_pixels)) / len(pixels) <= 3:
            return False
    return True


def collect(story, material, folder, engine, source_image, *, state, stock_collector, commons_collector):
    """Fetch up to eight unique, verified images; never mark preview stock as published."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink():
        raise ValueError('Unsafe preview image directory.')
    media, seen = [], []

    def add(item):
        try:
            signature = _signature(item['path'])
            if not _different(signature, seen):
                return False
            media.append(item)
            seen.append(signature)
            return True
        except (OSError, ValueError, KeyError):
            return False

    for index, image_url in enumerate((material.get('image_urls') or [])[:8]):
        if not isinstance(image_url, str) or len(media) >= 8:
            continue
        target = folder / ('article-' + str(index) + '.jpg')
        try:
            source_image.fetch(engine, material['source_url'], image_url, target, timeout=8)
            if not add({'path': target, 'kind': 'publisher'}):
                target.unlink(missing_ok=True)
        except Exception as exc:
            print('Preview article image unavailable:', type(exc).__name__, flush=True)
            if target.is_file() and not target.is_symlink():
                target.unlink()
    if not media:
        return []
    search_story = dict(material, **{key: story.get(key, '') for key in ('title_fa', 'summary_fa')},
                        stock_category=story.get('kind'))
    if len(media) < 8:
        directory = folder / 'stock'
        directory.mkdir(mode=0o700)
        try:
            # This is an explicitly requested private admin preview. Scheduled
            # production keeps the collector's existing provider restrictions.
            items = stock_collector(search_story, directory, origin='admin_direct', state=state, limit=8-len(media))
            for item in items:
                if len(media) >= 8:
                    break
                if item.get('provider') in {'pixabay', 'pexels'} and item.get('author') and item.get('source_url'):
                    add(item)
        except Exception as exc:
            print('Preview stock images unavailable:', type(exc).__name__, flush=True)
    if len(media) < 8:
        directory = folder / 'commons'
        directory.mkdir(mode=0o700)
        try:
            for item in commons_collector(search_story, directory, limit=8-len(media)):
                if len(media) >= 8:
                    break
                if all(item.get(key) for key in ('author', 'title', 'license', 'license_url', 'source_url')):
                    add(item)
        except Exception as exc:
            print('Preview licensed illustrations unavailable:', type(exc).__name__, flush=True)
    return media


def image_credits(media):
    lines = []
    for item in media:
        if item.get('kind') != 'illustrative':
            continue
        if item.get('provider') in {'pixabay', 'pexels'}:
            label = 'Pixabay' if item['provider'] == 'pixabay' else 'Pexels'
            lines.append(label + ': ' + item['author'] + ' — ' + item['source_url'])
        elif all(item.get(key) for key in ('author', 'title', 'license', 'license_url', 'source_url')):
            lines.append(item['title'] + ' — ' + item['author'] + '; ' + item['license'] +
                         '; resized/cropped. ' + item['source_url'] + ' ' + item['license_url'])
    return '\n'.join(lines)
