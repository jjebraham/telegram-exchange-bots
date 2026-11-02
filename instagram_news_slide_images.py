"""Select distinct verified images for Instagram news carousels."""
from pathlib import Path
import hashlib
import time
import uuid
from PIL import Image, ImageOps


class SlideImageError(RuntimeError):
    pass


def image_key(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SlideImageError('A selected news image is unavailable.')
    with Image.open(path) as image:
        if image.width < 256 or image.height < 128 or image.width * image.height > 40_000_000:
            raise SlideImageError('A selected news image has unsuitable dimensions.')
        pixels = ImageOps.exif_transpose(image).convert('RGB').resize((32, 32)).tobytes()
    return hashlib.sha256(pixels).hexdigest()


def collect(engine, story, directory, *, origin, minimum=2, limit=4):
    """Prefer publisher images, then relevant licensed stock/illustrations."""
    from instagram_reel_source_image import fetch
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir() or minimum not in (1, 2):
        raise SlideImageError('News image selection is not safely configured.')
    selected, seen = [], set()

    def add(item):
        try:
            key = image_key(item['path'])
        except (OSError, ValueError, KeyError, SlideImageError):
            return
        if key not in seen and len(selected) < limit:
            seen.add(key)
            selected.append(item)

    urls = [story.get('image_url')]
    if isinstance(story.get('image_urls'), list):
        urls.extend(story['image_urls'])
    distinct_urls, deadline = set(), time.monotonic()+25
    for url in urls:
        if not isinstance(url, str) or not url or url in distinct_urls:
            continue
        distinct_urls.add(url)
        if len(distinct_urls) > 6 or len(selected) >= limit or time.monotonic() >= deadline:
            break
        path = directory/('publisher-'+uuid.uuid4().hex+'.jpg')
        try:
            fetch(engine, story['source_url'], url, path,
                  timeout=max(1, min(6, deadline-time.monotonic())))
            add(dict(path=path, kind='publisher'))
        except Exception as exc:
            print('News source image unavailable:', type(exc).__name__, flush=True)

    if len(selected) < limit:
        try:
            from instagram_reel_stock import collect as stock_collect
            # Existing Pixabay policy permits only an explicit human request.
            stock_origin = 'admin_link' if origin == 'manual' else 'daily_news'
            for item in stock_collect(story, directory, origin=stock_origin, limit=limit-len(selected)):
                add(item)
        except Exception as exc:
            print('Related stock images unavailable:', type(exc).__name__, flush=True)
    if len(selected) < limit:
        try:
            from instagram_reel_commons import collect as commons_collect
            for item in commons_collect(story, directory, limit=limit-len(selected), seconds=15):
                add(item)
        except Exception as exc:
            print('Licensed news illustrations unavailable:', type(exc).__name__, flush=True)
    if len(selected) < minimum:
        raise SlideImageError('برای اسلایدهای ضروری، تصویر مرتبط و قابل‌استفاده کافی پیدا نشد؛ پست منتشر نشد.')
    return selected


def caption_credit(images):
    entries = []
    for item in images:
        if item.get('kind') != 'illustrative':
            continue
        if item.get('provider') in {'pexels', 'pixabay'}:
            name = 'Pexels' if item['provider'] == 'pexels' else 'Pixabay'
            entries.append(name+': '+str(item['author'])+' — '+str(item['source_url']))
        else:
            entries.append(str(item['title'])+' — '+str(item['author'])+'; '+str(item['license'])+
                           '; resized/cropped. '+str(item['source_url'])+' '+str(item['license_url']))
    return ('برخی تصاویر نمادین هستند.\n'+'\n'.join(entries)) if entries else ''

