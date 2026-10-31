#!/usr/bin/env python3
"""Render and publish one daily Instagram Trial Reel using Meta graduation."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import argparse
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from arabic_reshaper import reshape
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

STATE = Path.home() / '.local/state/kiani-instagram-trial-reels'
DB = STATE / 'trial_reels.sqlite3'
PUBLIC_ROOT = Path('/var/www/peerexo.com/public/instagram-rates/trial-reels')
PUBLIC_BASE = 'https://peerexo.com/instagram-rates/trial-reels'
ZONE = ZoneInfo('Europe/Istanbul')
MAX_PER_DAY = 5
MAX_REEL_SECONDS = 180
MAX_ADMIN_PER_DAY = 5
AUTO_SLOTS = ('11:00', '13:00', '15:00', '17:00', '20:30')
DIRECT_ADMIN_PER_DAY = 10
DIRECT_AUTO_PER_DAY = 2
DIRECT_AUTO_SLOTS = ('12:00', '18:00')
PENDING = {'rendering', 'creating_container', 'container_processing', 'publishing', 'needs_review'}
DECISIVE = {'published', 'needs_review', 'container_processing', 'publishing', 'creating_container'}
SEGMENT_SECONDS = 5.0
CROSSFADE_SECONDS = 0.25
VIDEO_SIZE = (1080, 1920)
INK = '#112A52'
GREEN = '#00AFA8'
MINT = '#D8F7F1'
PAPER = '#07172C'
MUTED = '#70829A'
GOLD = '#FFB52E'


class TrialReelError(RuntimeError):
    pass


def _safe_text(value, limit=12000):
    if not isinstance(value, str):
        raise TrialReelError('The translated story text is unavailable.')
    value = ''.join(ch for ch in value if ch in '\n\t' or ord(ch) >= 32).strip()
    if not value or len(value) > limit:
        raise TrialReelError('The translated story text is empty or too long for a Reel.')
    return value


def _rtl(value):
    return get_display(reshape(str(value)), base_dir='R')


def _font(asset_root, size, bold=False):
    name = 'Vazirmatn-Bold.ttf' if bold else 'Vazirmatn-Regular.ttf'
    path = Path(asset_root) / 'fonts' / name
    if path.is_symlink() or not path.is_file():
        raise TrialReelError('Kiani Persian font assets are unavailable.')
    # _rtl already shapes Arabic and applies the bidi algorithm. RAQM would
    # shape and reorder the same text a second time, reversing Persian words.
    return ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)


def _wrap(draw, text, font, width):
    rows, current = [], ''
    # Keep multiword English names together while wrapping Persian headlines.
    for word in re.findall(r'[A-Za-z0-9]+(?:[ \t]+[A-Za-z0-9]+)+|\S+', text):
        candidate = (current + ' ' + word).strip()
        if current and draw.textlength(_rtl(candidate), font=font) > width:
            rows.append(current)
            current = word
        else:
            current = candidate
    if current:
        rows.append(current)
    if any(draw.textlength(_rtl(row), font=font) > width for row in rows):
        raise TrialReelError('An unusually long word does not fit the Reel layout.')
    return rows


def _chunks(text, limit=170):
    sentences = [part.strip() for part in re.split(r'(?<=[.!?؟۔])\s+', text) if part.strip()]
    if not sentences:
        sentences = [text]
    chunks, current = [], ''
    for sentence in sentences:
        words = sentence.split()
        for word in words:
            if len(word) > limit:
                raise TrialReelError('The summary contains an unbreakable text segment.')
            candidate = (current + ' ' + word).strip()
            if current and len(candidate) > limit:
                chunks.append(current)
                current = word
            else:
                current = candidate
        if current:
            chunks.append(current)
            current = ''
    return chunks


def _brand_mark(asset_root):
    """Draw the first, original Kiani logo polygon without an SVG runtime."""
    import xml.etree.ElementTree as ET
    path = Path(asset_root) / 'assets/instagram/kiani-logo.svg'
    if path.is_symlink() or not path.is_file():
        raise TrialReelError('Kiani logo asset is unavailable.')
    root = ET.parse(path).getroot()
    viewbox = root.attrib.get('viewBox', '').split()
    if len(viewbox) != 4:
        raise TrialReelError('Kiani logo asset has an unsupported format.')
    _, _, width, height = map(float, viewbox)
    canvas = Image.new('RGBA', (128, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for node in root.iter('{http://www.w3.org/2000/svg}polygon'):
        value = node.attrib.get('points', '')
        points = [tuple(map(float, pair.split(','))) for pair in value.split()]
        if len(points) < 3:
            continue
        draw.polygon([(x * 128 / width, y * 128 / height) for x, y in points], fill=INK)
    return canvas


def _frame(title, body, kind, page, pages, asset_root, story_type='hard_news'):
    image = Image.new('RGB', VIDEO_SIZE, PAPER)
    draw = ImageDraw.Draw(image)
    w, h = VIDEO_SIZE
    # Original geometry gives the still frames a consistent branded motion canvas.
    draw.ellipse((770, -220, 1320, 330), fill=MINT)
    draw.ellipse((-310, 1360, 300, 1970), fill='#E4F0E8')
    draw.rounded_rectangle((52, 58, w - 52, h - 58), radius=48, fill='#FFFFFF', outline='#D7E8DC', width=3)
    logo = _brand_mark(asset_root).resize((88, 88), Image.Resampling.LANCZOS)
    image.paste(logo, (w - 166, 216), logo)
    regular = _font(asset_root, 30)
    bold = _font(asset_root, 38, True)
    draw.text((w - 188, 250), _rtl('صرافی کیانی'), font=bold, fill=INK, anchor='rm')
    draw.text((w - 188, 297), 'kiani.exchange', font=regular, fill=MUTED, anchor='rm')
    if story_type == 'forecast':
        label = 'پیش‌بینی کریپتو' if kind == 'crypto' else 'پیش‌بینی اقتصادی'
    elif story_type == 'promotional':
        label = 'محتوای معرفی'
    elif story_type == 'opinion':
        label = 'تحلیل کریپتو' if kind == 'crypto' else 'تحلیل اقتصادی'
    else:
        label = 'خبر کریپتو' if kind == 'crypto' else 'خبر اقتصادی'
    draw.rounded_rectangle((96, 225, 350, 292), radius=32, fill=MINT)
    draw.text((223, 259), _rtl(label), font=_font(asset_root, 29, True), fill=INK, anchor='mm')
    draw.rounded_rectangle((96, 350, w - 96, 357), radius=4, fill='#D9E7DD')
    draw.rounded_rectangle((96, 350, max(96 + 8, int((w - 192) * page / pages) + 96), 357), radius=4, fill=GREEN)

    if page == 1:
        draw.rounded_rectangle((96, 390, w - 96, 1150), radius=42, fill=INK)
        draw.ellipse((w - 260, 452, w - 174, 538), fill=GOLD)
        draw.text((w - 217, 495), '!', font=_font(asset_root, 54, True), fill=INK, anchor='mm')
        title_font = _font(asset_root, 72, True)
        title_rows = _wrap(draw, title, title_font, w - 260)
        if len(title_rows) > 6:
            title_font = _font(asset_root, 60, True)
            title_rows = _wrap(draw, title, title_font, w - 260)
        if len(title_rows) > 7:
            raise TrialReelError('The headline is too long for the Reel cover.')
        y = 610
        for row in title_rows:
            draw.text((w - 150, y), _rtl(row), font=title_font, fill='#FFFFFF', anchor='rt')
            y += int(title_font.size * 1.45)
        draw.text((w - 150, 1070), _rtl('خبر را در چند ثانیه بخوانید'), font=_font(asset_root, 32, True), fill='#BCEBD3', anchor='rt')
        footer = 'روایت کوتاه از یک خبرِ تأییدشده'
        draw.text((w / 2, 1255), _rtl(footer), font=_font(asset_root, 31), fill=MUTED, anchor='mm')
    elif page < pages:
        draw.rounded_rectangle((96, 390, w - 96, h - 425), radius=42, fill='#FFFFFF', outline='#DDEBE1', width=3)
        draw.rounded_rectangle((w - 202, 416, w - 144, 474), radius=22, fill=GOLD)
        draw.text((w - 173, 445), str(page - 1).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')),
                  font=_font(asset_root, 28, True), fill=INK, anchor='mm')
        body_font = _font(asset_root, 56)
        rows = _wrap(draw, body, body_font, w - 300)
        if len(rows) > 7:
            body_font = _font(asset_root, 48)
            rows = _wrap(draw, body, body_font, w - 300)
        if len(rows) > 8:
            raise TrialReelError('A story segment needs another page; no text was shortened.')
        line_height = int(body_font.size * 1.72)
        top = (h - (len(rows) * line_height)) // 2
        for index, row in enumerate(rows):
            draw.text((w - 150, top + index * line_height), _rtl(row), font=body_font, fill=INK, anchor='rt')
        draw.text((w - 150, h - 510), _rtl('ادامه خبر'), font=_font(asset_root, 28, True), fill=GREEN, anchor='rt')
    else:
        draw.rounded_rectangle((96, 360, w - 96, 1240), radius=42, fill=INK)
        draw.text((w / 2, 520), _rtl('رسانه منتشرکننده'), font=_font(asset_root, 46, True), fill='#BCEBD3', anchor='mm')
        source_rows = _wrap(draw, body, _font(asset_root, 48, True), w - 280)
        y = 630
        for row in source_rows[:4]:
            draw.text((w - 150, y), _rtl(row), font=_font(asset_root, 48, True), fill='#FFFFFF', anchor='rt')
            y += 72
        draw.text((w - 150, 970), _rtl('پیوند کامل منبع در کپشن'), font=_font(asset_root, 32), fill='#D9E7DD', anchor='rt')
        draw.text((w / 2, 1165), 'kiani.exchange', font=_font(asset_root, 36, True), fill=GOLD, anchor='mm')

    draw.text((126, h - 290), 'kiani.exchange', font=_font(asset_root, 26, True), fill=GREEN, anchor='lm')
    draw.text((w - 140, h - 290), f'{page}/{pages}', font=_font(asset_root, 25), fill=MUTED, anchor='rm')
    return image


def _probe_video(path, ffprobe):
    result = subprocess.run([ffprobe, '-v', 'error',
        '-show_entries', 'stream=codec_name,width,height,pix_fmt,sample_rate,channels:format=duration',
        '-of', 'json', str(path)], capture_output=True, text=True, timeout=30, check=True)
    try:
        data = json.loads(result.stdout)
        streams = data['streams']
        stream = next((item for item in streams if item.get('codec_name') == 'h264'), None)
        audio = next((item for item in streams if item.get('codec_name') == 'aac'), None)
        duration = float(data['format']['duration'])
    except (ValueError, KeyError, IndexError, TypeError):
        raise TrialReelError('The rendered Reel could not be verified.') from None
    if (stream is None or audio is None or stream.get('width') != 1080 or stream.get('height') != 1920 or
            stream.get('pix_fmt') != 'yuv420p' or audio.get('sample_rate') != '48000' or
            audio.get('channels') != 2 or not 12 <= duration <= MAX_REEL_SECONDS):
        raise TrialReelError('Rendered video does not meet the reviewed Reel format.')
    return duration


def render_video(story, kind, destination, asset_root, *, ffmpeg=None, ffprobe=None, music_path=None, media=None, narration=None):
    title = _safe_text(story.get('title_fa'), 500)
    summary = _safe_text(story.get('summary_fa'))
    source = _safe_text(story.get('source_name'), 180)
    story_type = story.get('story_type', 'hard_news')
    chunks = _chunks(summary)
    if not chunks or len(chunks) > 8:
        raise TrialReelError('The complete verified summary needs more than eight Reel text cards.')
    pages = len(chunks) + 2
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    ffmpeg = ffmpeg or shutil.which('ffmpeg')
    ffprobe = ffprobe or shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise TrialReelError('FFmpeg and ffprobe are required to render and verify Trial Reels.')
    import sys
    from instagram_reel_motion import render
    length = story.get('reel_length')
    if length not in (None, 'short', 'long'):
        raise TrialReelError('Unknown Reel length.')
    max_seconds = {'short': 30, 'long': 90}.get(length, MAX_REEL_SECONDS)
    render(sys.modules[__name__], title, source, kind, story_type, chunks, destination, asset_root, media or [], music_path, ffmpeg, narration=narration, max_seconds=max_seconds, min_seconds=15 if length == 'short' else 12)
    if destination.is_symlink() or not destination.is_file() or not 100_000 <= destination.stat().st_size <= 250_000_000:
        raise TrialReelError('The rendered Reel is missing or has an invalid file size.')
    os.chmod(destination, 0o644)
    duration = _probe_video(destination, ffprobe)
    if duration > max_seconds + 0.15 or length == 'short' and duration < 14.85:
        raise TrialReelError('Rendered Reel is outside the selected duration.')
    return duration


def _connect():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    if DB.is_symlink():
        raise TrialReelError('Trial Reel state path is unsafe.')
    con = sqlite3.connect(DB, timeout=20)
    os.chmod(DB, 0o600)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('''CREATE TABLE IF NOT EXISTS trial_reels(
        trial_id TEXT PRIMARY KEY, source_key TEXT NOT NULL, source_url TEXT NOT NULL,
        kind TEXT NOT NULL, title_original TEXT NOT NULL, title_fa TEXT NOT NULL,
        summary_fa TEXT NOT NULL, source_name TEXT NOT NULL, article_published_at REAL NOT NULL,
        posted_day TEXT NOT NULL, origin TEXT NOT NULL, submission_id INTEGER,
        status TEXT NOT NULL, container_id TEXT, media_id TEXT, video_path TEXT,
        caption TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        published_at REAL, error_type TEXT, story_type TEXT NOT NULL DEFAULT 'hard_news')''')
    columns = {row['name'] for row in con.execute('PRAGMA table_info(trial_reels)')}
    if 'story_type' not in columns:
        con.execute("ALTER TABLE trial_reels ADD COLUMN story_type TEXT NOT NULL DEFAULT 'hard_news'")
    if 'music_json' not in columns:
        con.execute('ALTER TABLE trial_reels ADD COLUMN music_json TEXT')
    if 'reel_mode' not in columns:
        con.execute("ALTER TABLE trial_reels ADD COLUMN reel_mode TEXT NOT NULL DEFAULT 'trial'")
    con.execute('CREATE INDEX IF NOT EXISTS trial_reels_day_status ON trial_reels(posted_day,status)')
    con.execute('CREATE INDEX IF NOT EXISTS trial_reels_source_status ON trial_reels(source_key,status)')
    con.execute('''CREATE TABLE IF NOT EXISTS daily_runs(
        posted_day TEXT PRIMARY KEY, status TEXT NOT NULL, started_at REAL NOT NULL,
        updated_at REAL NOT NULL, error_type TEXT)''')
    con.execute('''CREATE TABLE IF NOT EXISTS scheduled_runs(
        posted_day TEXT NOT NULL, slot TEXT NOT NULL, status TEXT NOT NULL,
        started_at REAL NOT NULL, updated_at REAL NOT NULL, error_type TEXT,
        trial_id TEXT, PRIMARY KEY(posted_day,slot))''')
    # Retain the old daily latch as the historical 20:30 slot; never rewrite it.
    con.execute('''INSERT OR IGNORE INTO scheduled_runs(posted_day,slot,status,started_at,updated_at,error_type,trial_id)
        SELECT d.posted_day,'20:30',d.status,d.started_at,d.updated_at,d.error_type,
        (SELECT r.trial_id FROM trial_reels r WHERE r.posted_day=d.posted_day
         AND r.origin='daily_top_story' ORDER BY r.created_at LIMIT 1)
        FROM daily_runs d''')
    con.commit()
    return con


@contextmanager
def publisher_lock():
    lock = STATE / 'publisher.lock'
    if lock.is_symlink():
        raise TrialReelError('Trial Reel publisher lock path is unsafe.')
    with lock.open('a') as handle:
        os.chmod(lock, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TrialReelError('A Trial Reel run is already active.') from None
        yield


def istanbul_day(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, ZONE).date().isoformat()


def _source_key(url):
    from instagram_crypto_news import canonical_url
    return hashlib.sha256(canonical_url(url).encode('utf-8')).hexdigest()


def _live_guard():
    from instagram_news_batch import guard, plan
    capacity, detail = plan(True)
    if capacity < 1:
        raise TrialReelError('No publishing capacity is available after protecting scheduled posts.')
    reservation = guard()
    return detail, reservation


def _caption(story, kind, reel_mode='trial'):
    if story.get('story_type') == 'forecast':
        label = 'پیش‌بینی کریپتو' if kind == 'crypto' else 'پیش‌بینی اقتصادی'
    elif story.get('story_type') == 'promotional':
        label = 'محتوای معرفی'
    elif story.get('story_type') == 'opinion':
        label = 'تحلیل کریپتو' if kind == 'crypto' else 'تحلیل اقتصادی'
    else:
        label = 'خبر کریپتو' if kind == 'crypto' else 'خبر اقتصادی'
    text = ('صرافی کیانی | ' + label + '\n\n' + story['title_fa'] + '\n\nمنبع: ' +
        story['source_name'] + '\n' + story['source_url'])
    if story.get('source_scope') == 'coindesk_rss_summary':
        text += '\n\nاین ویدئو بر اساس عنوان و خلاصه فید رسمی کوین‌دسک تهیه شده است.'
    if reel_mode == 'trial':
        text += '\n\nاین ویدئو به‌صورت Trial Reel منتشر شده است.'
    if len(text) > 2200:
        raise TrialReelError('Trial Reel caption exceeds Instagram’s length limit.')
    return text


def _update(con, trial_id, **values):
    fields = ','.join(name + '=?' for name in values)
    with con:
        con.execute('UPDATE trial_reels SET ' + fields + ' WHERE trial_id=?', (*values.values(), trial_id))


def _mark_daily_result(con, trial_id, status):
    with con:
        con.execute('UPDATE scheduled_runs SET status=?,updated_at=? WHERE trial_id=?',
                    (status, time.time(), trial_id))


def _article_allowed(origin, article_time, now):
    if isinstance(article_time, bool) or not isinstance(article_time, (int, float)) or not math.isfinite(article_time) or article_time < 0:
        return False
    return origin in {'admin_link', 'admin_direct'} or now - 86400 <= article_time <= now + 60

def _enforce_daily_limit(con, origin, day, reel_mode='trial'):
    if reel_mode == 'direct':
        if origin not in {'admin_direct', 'daily_direct'}:
            raise TrialReelError('Direct Reel origin is unsupported.')
        maximum = DIRECT_ADMIN_PER_DAY if origin == 'admin_direct' else DIRECT_AUTO_PER_DAY
    else:
        if origin not in {'admin_link', 'daily_top_story'}:
            raise TrialReelError('Trial Reel origin is unsupported.')
        maximum = MAX_ADMIN_PER_DAY if origin == 'admin_link' else MAX_PER_DAY
    used = con.execute('''SELECT COUNT(*) FROM trial_reels WHERE posted_day=? AND origin=? AND reel_mode=? AND status IN
        ('rendering','creating_container','container_processing','publishing','needs_review','published')''',
        (day, origin, reel_mode)).fetchone()[0]
    if used >= maximum:
        if origin in {'admin_link', 'admin_direct'}:
            raise TrialReelError('سقف انتشار ریل ادمین برای امروز به وقت استانبول تکمیل شده است.')
        raise TrialReelError('The scheduled Reel limit for today has already been used.')

def check_admin_daily_limit(reel_mode='trial'):
    with _connect() as con:
        _enforce_daily_limit(con, 'admin_direct' if reel_mode == 'direct' else 'admin_link',
                             istanbul_day(), reel_mode)

def create_reel(story, kind, *, origin, asset_root, reel_mode='trial', submission_id=None, scheduled_slot=None,
                public_root=PUBLIC_ROOT, public_base=PUBLIC_BASE, _validated_image=None):
    """Render a direct or Trial Reel and persist its Meta container before polling."""
    allowed_origins = ({'daily_top_story', 'admin_link'} if reel_mode == 'trial'
                       else {'daily_direct', 'admin_direct'})
    if kind not in {'crypto', 'economy'} or origin not in allowed_origins:
        raise TrialReelError('Reel category, mode or origin is unsupported.')
    allowed_slots = AUTO_SLOTS if reel_mode == 'trial' else DIRECT_AUTO_SLOTS
    if origin in {'daily_top_story', 'daily_direct'} and scheduled_slot not in allowed_slots:
        raise TrialReelError('The automatic Reel slot is invalid.')
    article_time = story.get('article_published_at')
    if not _article_allowed(origin, article_time, time.time()):
        raise TrialReelError('The original article is outside the fresh 24-hour window.')
    normalized = dict(story)
    normalized['stock_category'] = kind
    for field, limit in (('source_url', 2048), ('source_name', 180), ('title_original', 800), ('title_fa', 500), ('summary_fa', 12000)):
        normalized[field] = _safe_text(normalized.get(field), limit)
    if normalized.get('source_scope') == 'coindesk_rss_summary':
        normalized['summary_fa'] = 'خلاصه فید رسمی کوین‌دسک: ' + normalized['summary_fa']
    normalized['story_type'] = normalized.get('story_type', 'hard_news')
    if normalized['story_type'] not in {'hard_news', 'opinion', 'forecast', 'roundup', 'promotional'}:
        raise TrialReelError('The selected story type is not eligible for Trial Reels.')
    source_key = _source_key(normalized['source_url'])
    caption = _caption(normalized, kind, reel_mode)
    from instagram_reel_media import select as select_media, caption as media_caption
    media = select_media(normalized)
    if media:
        caption += '\n\n' + media_caption(media)
        if len(caption) > 2200:
            raise TrialReelError('Trial Reel caption with image credits is too long.')
    trial_id = uuid.uuid4().hex
    posted_day = istanbul_day()
    public_root = Path(public_root)
    media_parent = Path('/var/www/peerexo.com/public/instagram-rates')
    if public_root.parent != media_parent or media_parent.is_symlink() or not media_parent.is_dir():
        raise TrialReelError('The approved public media directory is unavailable or changed.')
    if public_root.is_symlink():
        raise TrialReelError('Public Trial Reel media directory is unsafe.')
    public_root.mkdir(parents=True, exist_ok=True, mode=0o755)
    # The worker uses umask 077 for private state; mkdir's mode is masked by it.
    # Reapply the intended public traversal/read mode so the web server and Meta
    # can fetch the video from the document root.
    os.chmod(public_root, 0o755)
    video_path = public_root / (('kiani-trial-' if reel_mode == 'trial' else 'kiani-reel-') + trial_id + '.mp4')
    with publisher_lock(), _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        _enforce_daily_limit(con, origin, posted_day, reel_mode)
        duplicate = con.execute('''SELECT 1 FROM trial_reels WHERE source_key=? AND status IN
            ('rendering','creating_container','container_processing','publishing','needs_review','published') LIMIT 1''', (source_key,)).fetchone()
        if duplicate:
            raise TrialReelError('This story already has a Trial Reel or unresolved attempt.')
        con.execute('''INSERT INTO trial_reels(trial_id,source_key,source_url,kind,title_original,title_fa,
            summary_fa,source_name,article_published_at,posted_day,origin,submission_id,story_type,status,container_id,
            media_id,video_path,caption,created_at,updated_at,published_at,error_type,reel_mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'rendering',NULL,NULL,?,?,?, ?,NULL,NULL,?)''',
            (trial_id, source_key, normalized['source_url'], kind, normalized['title_original'], normalized['title_fa'],
             normalized['summary_fa'], normalized['source_name'], float(article_time), posted_day, origin,
             submission_id, normalized['story_type'], str(video_path), caption, time.time(), time.time(), reel_mode))
        if origin in {'daily_top_story', 'daily_direct'}:
            result = con.execute('''UPDATE scheduled_runs SET trial_id=?,updated_at=?
                WHERE posted_day=? AND slot=? AND status='selecting' AND trial_id IS NULL''',
                (trial_id, time.time(), posted_day, scheduled_slot))
            if result.rowcount != 1:
                raise TrialReelError('Automatic Trial Reel slot reservation changed.')
    music_path = STATE / ('music-' + trial_id + '.ogg')
    source_image_path = STATE / ('source-image-' + trial_id + '.jpg')
    extra_image_paths = []
    commons_temp = None
    stock_temp = None
    stock_used = []
    try:
        _live_guard()
        if normalized.get('image_url'):
            try:
                import crypto_news_trial as image_engine
                from instagram_reel_source_image import fetch as fetch_source_image
                if _validated_image is not None:
                    checked = Path(_validated_image)
                    if checked.is_symlink() or not checked.is_file() or checked.stat().st_size > 10_000_000:
                        raise ValueError('The prechecked publisher image is unavailable.')
                    with checked.open('rb') as src, source_image_path.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                    source_image_path.chmod(0o600)
                else:
                    fetch_source_image(image_engine, normalized['source_url'], normalized['image_url'], source_image_path)
                media.insert(0, {'path':source_image_path, 'kind':'publisher'})
                # Optional article figures are bounded by count and time;
                # duplicate or unavailable images never invalidate the lead.
                candidates = normalized.get('image_urls', [])
                if isinstance(candidates, list):
                    seen_hashes = {hashlib.sha256(source_image_path.read_bytes()).hexdigest()}
                    image_deadline = time.monotonic() + 30
                    for candidate in candidates[:16]:
                        if len(extra_image_paths) >= 7 or time.monotonic() >= image_deadline:
                            break
                        if not isinstance(candidate, str) or candidate == normalized['image_url']:
                            continue
                        extra_path = STATE / ('source-image-' + trial_id + '-' + str(len(extra_image_paths) + 1) + '.jpg')
                        try:
                            timeout = max(1, min(6, image_deadline - time.monotonic()))
                            fetch_source_image(image_engine, normalized['source_url'], candidate, extra_path, timeout=timeout)
                            digest = hashlib.sha256(extra_path.read_bytes()).hexdigest()
                            if digest in seen_hashes:
                                extra_path.unlink()
                                continue
                            seen_hashes.add(digest)
                            extra_image_paths.append(extra_path)
                            media.insert(len(extra_image_paths), {'path':extra_path, 'kind':'publisher'})
                        except Exception as extra_exc:
                            print('Optional publisher image unavailable:', type(extra_exc).__name__, flush=True)
                            if extra_path.is_file() and not extra_path.is_symlink():
                                extra_path.unlink()
                            if getattr(extra_exc, 'code', None) == 429:
                                break
                media = media[:8]
                print('Reel images selected:', len(media), flush=True)
                caption += '\n\nتصویر: ' + normalized['source_name'] + ' · ' + normalized['source_url']
                if len(caption)>2200: raise TrialReelError('Caption with image credit is too long.')
                _update(con, trial_id, caption=caption, updated_at=time.time())
            except TrialReelError:
                raise
            except Exception as exc:
                print('Publisher image unavailable:', type(exc).__name__, flush=True)
                raise TrialReelError('تصویر اصلی خبر در دسترس نیست؛ ریل بدون تصویر منتشر نشد.') from None
        if len(media) < 8:
            try:
                from instagram_reel_stock import collect as collect_stock
                stock_temp = tempfile.TemporaryDirectory(prefix='stock-' + trial_id + '-', dir=STATE)
                stock = collect_stock(normalized, Path(stock_temp.name), origin=origin, state=STATE, limit=8-len(media))
                seen = {hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() for item in media}
                providers_credited = set()
                for item in stock:
                    digest = hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()
                    if digest in seen:
                        continue
                    provider = item['provider']
                    label = 'Pexels' if provider == 'pexels' else 'Pixabay'
                    header = ('\n\nPhotos provided by Pexels: https://www.pexels.com' if provider == 'pexels'
                              else '\n\nIllustrations from Pixabay: https://pixabay.com')
                    credit = ('\n' + label + ': ' + item['author'] + ' — ' + item['source_url'])
                    addition = (header if provider not in providers_credited else '') + credit
                    if len(caption) + len(addition) > 1650:
                        continue
                    caption += addition
                    providers_credited.add(provider)
                    seen.add(digest)
                    media.append(item)
                    stock_used.append(item)
                if stock_used:
                    _update(con, trial_id, caption=caption, updated_at=time.time())
                print('Stock illustrations selected:', len(stock_used), flush=True)
            except Exception as exc:
                print('Stock illustrations unavailable:', type(exc).__name__, flush=True)
        if len(media) < 8:
            commons_added = False
            try:
                from instagram_reel_commons import collect as collect_illustrations
                commons_temp = tempfile.TemporaryDirectory(prefix='commons-' + trial_id + '-', dir=STATE)
                illustrations = collect_illustrations(normalized, Path(commons_temp.name), limit=8-len(media))
                seen = {hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() for item in media}
                for item in illustrations:
                    digest = hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()
                    if digest in seen:
                        continue
                    credit = ('\n\nIllustrative image: ' + item['title'] + ' — ' + item['author'] +
                              '; ' + item['license'] + '; resized/cropped. ' + item['source_url'] +
                              ' ' + item['license_url'])
                    # Keep room for the soundtrack attribution added below.
                    if len(caption) + len(credit) > 1650:
                        continue
                    seen.add(digest)
                    caption += credit
                    media.append(item)
                    commons_added = True
            except Exception as exc:
                print('Licensed illustrations unavailable:', type(exc).__name__, flush=True)
            if commons_added:
                _update(con, trial_id, caption=caption, updated_at=time.time())
        print('Total verified Reel images:', len(media), flush=True)
        if any(item.get('kind') == 'illustrative' for item in media):
            caption = 'برخی تصاویر این ویدئو نمادین هستند.\n\n' + caption
            if len(caption) > 2200:
                raise TrialReelError('Reel caption with image disclosure is too long.')
            _update(con, trial_id, caption=caption, updated_at=time.time())
        from instagram_trial_music import select_order, retrieve_track, caption_credit
        previous = con.execute("SELECT music_json FROM trial_reels WHERE status IN ('published','container_processing','publishing','needs_review') AND music_json IS NOT NULL ORDER BY COALESCE(published_at,created_at) DESC LIMIT 10").fetchall()
        recent_titles = []
        for previous_row in previous:
            try:
                title = json.loads(previous_row['music_json']).get('title')
                if isinstance(title, str):
                    recent_titles.append(title)
            except (ValueError, TypeError, AttributeError):
                continue
        music = None
        for candidate in select_order(normalized, recent_titles):
            try:
                music = retrieve_track(candidate, music_path)
                break
            except Exception as exc:
                print('Music source unavailable or unverified:', type(exc).__name__, flush=True)
        if music:
            caption += '\n\n' + caption_credit(music)
            if len(caption) > 2200:
                raise TrialReelError('Trial Reel caption with music credit is too long.')
            _update(con, trial_id, caption=caption, music_json=json.dumps(music, ensure_ascii=False), updated_at=time.time())
        else:
            print('Music unavailable; retaining the existing silent-audio fallback.', flush=True)
        duration = render_video(normalized, kind, video_path, asset_root,
                                music_path=music_path if music else None, media=media)
        if stock_used:
            try:
                from instagram_reel_stock import mark_used
                mark_used(stock_used, state=STATE)
            except Exception as exc:
                print('Stock image history unavailable:', type(exc).__name__, flush=True)
        if origin in {'daily_top_story', 'daily_direct'} and time.time() - article_time > 86400:
            raise TrialReelError('The article expired while its Reel was being rendered.')
        public_url = public_base.rstrip('/') + '/' + quote(video_path.name)
        request = Request(public_url, headers={'Range': 'bytes=0-31', 'User-Agent': 'KianiExchange-TrialReel/1.0'})
        try:
            with urlopen(request, timeout=20) as response:
                header = response.read(16)
                if response.headers.get_content_type() != 'video/mp4' or len(header) < 12 or header[4:8] != b'ftyp':
                    raise TrialReelError('The public video URL did not return the prepared MP4.')
        except TrialReelError:
            raise
        except Exception:
            raise TrialReelError('The prepared Reel video is not publicly reachable over HTTPS.') from None
        import sys
        publisher_root = Path(asset_root).resolve()
        sys.path.insert(0, str(publisher_root))
        import instagram_daily_rates as ig
        os.environ['INSTAGRAM_PUBLIC_MEDIA_BASE_URL'] = public_base
        # The renderer writes the finished cover as the first video frame.
        # Ask Meta to use that frame instead of selecting a partly typed title.
        fields = {'media_type': 'REELS', 'video_url': public_url, 'caption': caption,
                  'thumb_offset': '0'}
        if reel_mode == 'trial':
            fields.update(share_to_feed='false',
                trial_params=json.dumps({'graduation_strategy': 'SS_PERFORMANCE'}, separators=(',', ':')))
        else:
            fields['share_to_feed'] = 'true'
        _update(con, trial_id, status='creating_container', updated_at=time.time())
        try:
            container_id = ig._create_container(fields)
        except Exception as exc:
            # A timeout may happen after Meta created the container. Keep the
            # daily slot reserved and require review instead of blindly retrying.
            _update(con, trial_id, status='needs_review', error_type=type(exc).__name__, updated_at=time.time())
            raise TrialReelError('Meta’s container result is uncertain; the daily slot is reserved for review.') from None
        _update(con, trial_id, status='container_processing', container_id=container_id,
                error_type=None, updated_at=time.time())
        print(f'{"Trial " if reel_mode == "trial" else "Direct "}Reel container ready for processing: {trial_id}; {duration:.1f}s.', flush=True)
        return trial_id
    except BaseException as exc:
        row = con.execute('SELECT status FROM trial_reels WHERE trial_id=?', (trial_id,)).fetchone()
        if row and row['status'] == 'rendering':
            _update(con, trial_id, status='failed', error_type=type(exc).__name__, updated_at=time.time())
            _mark_daily_result(con, trial_id, 'failed')
        elif row and row['status'] == 'needs_review':
            _mark_daily_result(con, trial_id, 'needs_review')
        raise
    finally:
        if music_path.is_file() and not music_path.is_symlink():
            music_path.unlink()
        if source_image_path.is_file() and not source_image_path.is_symlink():
            source_image_path.unlink()
        for extra_path in extra_image_paths:
            if extra_path.is_file() and not extra_path.is_symlink():
                extra_path.unlink()
        if commons_temp is not None:
            commons_temp.cleanup()
        if stock_temp is not None:
            stock_temp.cleanup()


def create_trial(story, kind, *, origin, asset_root, submission_id=None, scheduled_slot=None,
                 public_root=PUBLIC_ROOT, public_base=PUBLIC_BASE):
    return create_reel(story, kind, origin=origin, asset_root=asset_root, reel_mode='trial',
        submission_id=submission_id, scheduled_slot=scheduled_slot, public_root=public_root, public_base=public_base)


def poll_pending(*, publisher_root, intake_con=None, send_message=None, token=None):
    """Advance at most one saved Meta container without ever blind-retrying publish."""
    publisher_root = Path(publisher_root).resolve()
    import sys
    sys.path.insert(0, str(publisher_root))
    import instagram_daily_rates as ig
    from instagram_news_batch import guard
    results = []
    try:
        from instagram_direct_reel_retention import process_due as process_direct_retention
        process_direct_retention()
    except Exception as exc:
        print('Direct Reel retention deferred safely:', type(exc).__name__, flush=True)
    with _connect() as con:
        interrupted = con.execute("SELECT trial_id,status,submission_id,title_fa,origin FROM trial_reels WHERE status IN ('creating_container','publishing')").fetchall()
        for row in interrupted:
            current = con.execute('SELECT updated_at FROM trial_reels WHERE trial_id=?', (row['trial_id'],)).fetchone()
            if current and time.time() - current['updated_at'] < 300:
                continue
            if row['status'] == 'creating_container':
                _update(con, row['trial_id'], status='failed', error_type='InterruptedContainerCreate', updated_at=time.time())
                _mark_daily_result(con, row['trial_id'], 'failed')
                results.append(dict(trial_id=row['trial_id'], submission_id=row['submission_id'], status='failed',
                                    title_fa=row['title_fa'], origin=row['origin']))
            else:
                _update(con, row['trial_id'], status='needs_review', error_type='InterruptedPublish', updated_at=time.time())
                _mark_daily_result(con, row['trial_id'], 'needs_review')
                results.append(dict(trial_id=row['trial_id'], submission_id=row['submission_id'], status='needs_review',
                                    title_fa=row['title_fa'], origin=row['origin']))
        stale_renders = con.execute("SELECT trial_id,submission_id,title_fa,origin FROM trial_reels WHERE status='rendering' AND created_at<?",
                                    (time.time() - 1800,)).fetchall()
        for row in stale_renders:
            _update(con, row['trial_id'], status='failed', error_type='InterruptedRender', updated_at=time.time())
            _mark_daily_result(con, row['trial_id'], 'failed')
            results.append(dict(trial_id=row['trial_id'], submission_id=row['submission_id'], status='failed',
                                title_fa=row['title_fa'], origin=row['origin']))
        row = con.execute("SELECT * FROM trial_reels WHERE status='container_processing' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return results
        job = dict(row)
        if job['origin'] in {'daily_top_story', 'daily_direct'} and time.time() - job['article_published_at'] > 86400:
            _update(con, job['trial_id'], status='failed', error_type='ArticleExpiredDuringProcessing', updated_at=time.time())
            _mark_daily_result(con, job['trial_id'], 'failed')
            results.append(dict(trial_id=job['trial_id'], submission_id=job['submission_id'], status='failed',
                                title_fa=job['title_fa'], origin=job['origin']))
            return results
        try:
            status = ig._graph_request('', 'GET', {'fields': 'status_code,status'}, object_id=job['container_id'])
        except Exception as exc:
            print('Trial Reel container check deferred:', type(exc).__name__, flush=True)
            return results
        state = str(status.get('status_code', '')).upper()
        if state == 'IN_PROGRESS':
            _update(con, job['trial_id'], updated_at=time.time())
            return results
        if state in {'ERROR', 'EXPIRED'}:
            _update(con, job['trial_id'], status='failed', error_type='Container' + state.title(), updated_at=time.time())
            _mark_daily_result(con, job['trial_id'], 'failed')
            results.append(dict(trial_id=job['trial_id'], submission_id=job['submission_id'], status='failed',
                                title_fa=job['title_fa'], origin=job['origin']))
            return results
        if state == 'PUBLISHED':
            _update(con, job['trial_id'], status='needs_review', error_type='PublishedWithoutRecordedMediaId', updated_at=time.time())
            _mark_daily_result(con, job['trial_id'], 'needs_review')
            results.append(dict(trial_id=job['trial_id'], submission_id=job['submission_id'], status='needs_review',
                                title_fa=job['title_fa'], origin=job['origin']))
            return results
        if state != 'FINISHED':
            print('Trial Reel container has an unrecognized status; waiting for review.', flush=True)
            return results
        try:
            guard()
        except Exception as exc:
            print('Trial Reel publishing deferred by quota/source reservation:', type(exc).__name__, flush=True)
            return results
        if job['origin'] in {'daily_top_story', 'daily_direct'} and time.time() - job['article_published_at'] > 86400:
            _update(con, job['trial_id'], status='failed', error_type='ArticleExpiredBeforePublish', updated_at=time.time())
            _mark_daily_result(con, job['trial_id'], 'failed')
            results.append(dict(trial_id=job['trial_id'], submission_id=job['submission_id'], status='failed',
                                title_fa=job['title_fa'], origin=job['origin']))
            return results
        _update(con, job['trial_id'], status='publishing', updated_at=time.time())
        try:
            media_id = ig._publish_container(job['container_id'])
        except Exception as exc:
            _update(con, job['trial_id'], status='needs_review', error_type=type(exc).__name__, updated_at=time.time())
            _mark_daily_result(con, job['trial_id'], 'needs_review')
            results.append(dict(trial_id=job['trial_id'], submission_id=job['submission_id'], status='needs_review',
                                title_fa=job['title_fa'], origin=job['origin']))
            return results
        published_at = time.time()
        _update(con, job['trial_id'], status='published', media_id=media_id, published_at=published_at,
                error_type=None, updated_at=published_at)
        _mark_daily_result(con, job['trial_id'], 'published')
        results.append(dict(trial_id=job['trial_id'], submission_id=job['submission_id'], status='published',
                            title_fa=job['title_fa'], media_id=media_id, origin=job['origin']))
    return results


from instagram_reel_usage import tracked as track_reel_usage

def _slot_due(local, slot, reel_mode='trial'):
    slots = AUTO_SLOTS if reel_mode == 'trial' else DIRECT_AUTO_SLOTS
    if slot not in slots:
        raise TrialReelError('Unknown automatic Reel slot.')
    hour, minute = (int(value) for value in slot.split(':'))
    due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return due.timestamp() <= local.timestamp() < due.timestamp() + 600

def _reserve_auto_slot(con, day, slot, now, reel_mode='trial'):
    origin = 'daily_top_story' if reel_mode == 'trial' else 'daily_direct'
    _enforce_daily_limit(con, origin, day, reel_mode)
    old = con.execute('SELECT status FROM scheduled_runs WHERE posted_day=? AND slot=?', (day, slot)).fetchone()
    if old:
        return False
    con.execute("INSERT INTO scheduled_runs VALUES (?,?,'selecting',?,?,NULL,NULL)", (day, slot, now, now))
    return True

def _run_scheduled(runtime_root, asset_root, slot, reel_mode):
    """Choose and prepare the highest-ranked eligible story for one durable slot."""
    origin = 'daily_top_story' if reel_mode == 'trial' else 'daily_direct'
    slot_label = 'Trial Reel' if reel_mode == 'trial' else 'direct Reel'
    import sys
    runtime_root = Path(runtime_root).resolve()
    sys.path[:0] = [str(runtime_root), str(runtime_root / 'selector_trial_runtime')]
    from economy_news_translation import load_translation_env
    from instagram_manual_news_intake import load_publish_env
    from instagram_ranked_news import configure_engine, locks, rank_events, select_main_stories
    from instagram_crypto_news import database

    load_translation_env(Path.home() / 'sub/.env')
    load_publish_env()
    now = time.time()
    local = datetime.fromtimestamp(now, ZONE)
    day = local.date().isoformat()
    if not _slot_due(local, slot, reel_mode):
        print(f'Scheduled {slot_label} slot is outside its ten-minute start window.', flush=True)
        return None
    with publisher_lock(), _connect() as con:
        try:
            reserved = _reserve_auto_slot(con, day, slot, now, reel_mode)
        except TrialReelError:
            print(f'The automatic {slot_label} daily limit is already reserved.', flush=True)
            return None
        if not reserved:
            print(f'This automatic {slot_label} slot was already recorded.', flush=True)
            return None
    image_temp = None
    try:
        # Avoid running paid selection when Meta capacity is already unavailable.
        _live_guard()
        image_temp = tempfile.TemporaryDirectory(prefix='auto-image-check-', dir=STATE)
        image_dir = Path(image_temp.name)
        image_deadline = [None]
        deadline_lock = threading.Lock()
        def check_material_image(material):
            from instagram_reel_source_image import fetch
            from instagram_crypto_news import NewsError
            if _source_key(material['source_url']) in used_sources:
                raise NewsError('Reel source already used or in progress.')
            with deadline_lock:
                if image_deadline[0] is None:
                    image_deadline[0] = time.monotonic() + 90
                deadline = image_deadline[0]
            urls = [material.get('image_url')]
            extra = material.get('image_urls')
            if isinstance(extra, list):
                urls.extend(extra)
            seen = set()
            for url in urls:
                if not isinstance(url, str) or not url or url in seen:
                    continue
                seen.add(url)
                if len(seen) > 3 or time.monotonic() >= deadline:
                    break
                path = image_dir / (uuid.uuid4().hex + '.jpg')
                try:
                    fetch(engine, material['source_url'], url, path,
                          timeout=max(1, min(5, deadline - time.monotonic())))
                    material['image_url'] = url
                    material['_reel_checked_image'] = str(path)
                    return
                except Exception:
                    if path.is_file() and not path.is_symlink():
                        path.unlink()
            raise NewsError('No verified usable publisher image for automatic Reel.')
        import crypto_news_trial as engine
        import instagram_ranked_news as ranked
        candidates = []
        with _connect() as reel_con:
            used_sources = {row['source_key'] for row in reel_con.execute('''SELECT source_key FROM trial_reels
                WHERE status IN ('rendering','creating_container','container_processing','publishing','needs_review','published')''')}
        # This lock is shared with both ordinary news publishers, so event
        # history cannot change while the daily cross-category ranking runs.
        with locks('crypto'):
            for kind in ('crypto', 'economy'):
                image_deadline[0] = None
                configure_engine(kind)
                source_db = ranked.SOURCES[kind]
                with database(source_db) as con:
                    engine.init_trial(con)
                    rows, audit = rank_events(con, kind, now, trial_relaxed=True,
                                              material_filter=check_material_image)
                    rows = [item for item in rows if _source_key(item['source_url']) not in used_sources]
                    if rows:
                        selected = select_main_stories(con, rows, kind, 1, now, audit, lambda: None)
                        candidates.extend((kind, item) for item in selected)
        if not candidates:
            with _connect() as con:
                con.execute("UPDATE scheduled_runs SET status='no_candidate',updated_at=? WHERE posted_day=? AND slot=?", (time.time(), day, slot))
            print(f'No verified fresh eligible story ranked today; no {slot_label} was prepared.', flush=True)
            return None
        kind, row = max(candidates, key=lambda item: (item[1]['trial_score'], item[1]['article_published_at'], item[0] == 'crypto'))
        configure_engine(kind)
        import instagram_ranked_news as ranked
        with database(ranked.SOURCES[kind]) as con:
            title, summary = ranked.translate(con, row)
        story = dict(source_url=row['source_url'], source_name=row['source_name'],
            title_original=row['title_original'], title_fa=title, summary_fa=summary,
            image_url=row.get('image_url'), image_urls=row.get('image_urls', []),
            article_published_at=row['article_published_at'],
            story_type=row['assessment']['story_type'])
        trial_id = create_reel(story, kind, origin=origin, asset_root=asset_root,
            reel_mode=reel_mode, scheduled_slot=slot, _validated_image=row['_reel_checked_image'])
        with _connect() as con:
            con.execute("UPDATE scheduled_runs SET status='container_processing',updated_at=? WHERE posted_day=? AND slot=? AND status='selecting'", (time.time(), day, slot))
        return trial_id
    except BaseException as exc:
        with _connect() as con:
            con.execute("UPDATE scheduled_runs SET status='failed',error_type=?,updated_at=? WHERE posted_day=? AND slot=? AND trial_id IS NULL",
                        (type(exc).__name__, time.time(), day, slot))
        raise
    finally:
        if image_temp is not None:
            image_temp.cleanup()

@track_reel_usage('daily_top_story')
def run_daily(runtime_root, asset_root, slot):
    return _run_scheduled(runtime_root, asset_root, slot, 'trial')

@track_reel_usage('daily_direct')
def run_direct_daily(runtime_root, asset_root, slot):
    return _run_scheduled(runtime_root, asset_root, slot, 'direct')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--daily', action='store_true')
    modes.add_argument('--direct-daily', action='store_true')
    parser.add_argument('--slot', choices=AUTO_SLOTS + DIRECT_AUTO_SLOTS, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the existing Instagram publisher user, without sudo.')
    os.umask(0o077)
    try:
        result = run_direct_daily(args.runtime, args.assets, args.slot) if args.direct_daily else run_daily(args.runtime, args.assets, args.slot)
        if result:
            print(('Daily direct Reel' if args.direct_daily else 'Daily Trial Reel') + ' container queued: ' + result, flush=True)
        return 0
    except Exception as exc:
        print(('Daily direct Reel' if args.direct_daily else 'Daily Trial Reel') + ' stopped: ' +
              (str(exc) if isinstance(exc, TrialReelError) else type(exc).__name__), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())








