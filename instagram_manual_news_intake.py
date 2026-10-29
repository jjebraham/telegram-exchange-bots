#!/usr/bin/env python3
"""Admin-only Telegram intake for verified, automatically published news."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import sys
import time
from datetime import datetime
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, urlopen

HOME = Path.home()
STATE = HOME / '.local/state/kiani-instagram-manual-news'
DB = STATE / 'intake.sqlite3'
CONFIG_DEFAULT = HOME / '.config/kiani-instagram-manual-news/config.json'
ADMIN_IDS = re.compile(r'^[0-9]{5,20}$')
URL_RE = re.compile(r'https?://[^\s<>]+', re.IGNORECASE)
MAX_TELEGRAM_BODY = 1_000_000
POLL_TIMEOUT = 20


class IntakeError(RuntimeError):
    pass


def canonical_url(value):
    from instagram_crypto_news import canonical_url as normalize
    return normalize(value)


def url_in(text):
    found = [match.group(0).rstrip('.,;:!?)]}»”\'"') for match in URL_RE.finditer(str(text or ''))]
    if len(found) != 1:
        return None
    value = found[0]
    if len(value) > 2048:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        return None
    return value


def open_database():
    if STATE.is_symlink():
        raise IntakeError('The private intake directory is unsafe.')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE, 0o700)
    if DB.is_symlink():
        raise IntakeError('The intake database path is unsafe.')
    con = sqlite3.connect(DB, timeout=15)
    os.chmod(DB, 0o600)
    con.row_factory = sqlite3.Row
    con.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS submissions(
            update_id INTEGER PRIMARY KEY, admin_id TEXT NOT NULL, chat_id TEXT NOT NULL,
            message_id INTEGER NOT NULL, source_url TEXT, source_key TEXT,
            received_at REAL NOT NULL, status TEXT NOT NULL, kind TEXT,
            request_type TEXT NOT NULL DEFAULT 'feed',
            title_fa TEXT, media_id TEXT, response TEXT NOT NULL DEFAULT '',
            reply_sent INTEGER NOT NULL DEFAULT 0, error_code TEXT);
        CREATE INDEX IF NOT EXISTS manual_news_source ON submissions(source_key,received_at);
        CREATE INDEX IF NOT EXISTS manual_news_pending ON submissions(status,received_at);
    ''')
    columns = {row['name'] for row in con.execute('PRAGMA table_info(submissions)')}
    if 'request_type' not in columns:
        con.execute("ALTER TABLE submissions ADD COLUMN request_type TEXT NOT NULL DEFAULT 'feed'")
    return con


def set_offset(con, offset):
    con.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', ('telegram_offset', str(offset)))


def get_offset(con):
    row = con.execute("SELECT value FROM settings WHERE key='telegram_offset'").fetchone()
    return int(row['value']) if row else None


def private_json(path):
    if path.is_symlink() or not path.is_file():
        raise IntakeError('Private Telegram configuration is missing or unsafe.')
    info = path.stat()
    if hasattr(os, 'getuid') and info.st_uid != os.getuid():
        raise IntakeError('Private Telegram configuration has an unexpected owner.')
    if info.st_mode & 0o077:
        raise IntakeError('Private Telegram configuration permissions are too open.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise IntakeError('Private Telegram configuration cannot be read.') from None
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise IntakeError('Private Telegram configuration schema is unsupported.')
    token = data.get('bot_token')
    admins = data.get('admin_ids')
    if not isinstance(token, str) or not re.fullmatch(r'[0-9]{5,15}:[A-Za-z0-9_-]{20,}', token):
        raise IntakeError('Telegram bot token is invalid.')
    if not isinstance(admins, list) or not admins or any(not isinstance(x, str) or not ADMIN_IDS.fullmatch(x) for x in admins):
        raise IntakeError('At least one numeric admin account ID is required.')
    return token, set(admins)


def telegram(token, method, payload, *, timeout=35):
    url = 'https://api.telegram.org/bot' + token + '/' + method
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                      headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                               'User-Agent': 'KianiInstagramManualNews/1.0'})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_TELEGRAM_BODY + 1)
        if len(raw) > MAX_TELEGRAM_BODY:
            raise IntakeError('Telegram response exceeded the size limit.')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise IntakeError('Telegram did not confirm the request.')
        return result.get('result')
    except IntakeError:
        raise
    except Exception as exc:
        status = getattr(exc, 'code', None)
        detail = 'HTTP ' + str(status) if type(status) is int else type(exc).__name__
        raise IntakeError('Telegram request failed (' + detail + ').') from None


def send_message(token, chat_id, text):
    if not isinstance(text, str) or not text:
        return
    telegram(token, 'sendMessage', {'chat_id': str(chat_id), 'text': text[:3900]}, timeout=20)


def no_webhook(token):
    result = telegram(token, 'getWebhookInfo', {}, timeout=20)
    if not isinstance(result, dict):
        raise IntakeError('Telegram webhook status is unavailable.')
    if result.get('url'):
        raise IntakeError('This bot has a webhook configured; polling is disabled to avoid replacing it.')


def ingest(con, updates, admins):
    acknowledgements, final_messages = [], []
    if not isinstance(updates, list):
        raise IntakeError('Telegram returned an invalid update batch.')
    with con:
        for update in updates:
            if not isinstance(update, dict) or type(update.get('update_id')) is not int:
                continue
            offset = update['update_id'] + 1
            current = get_offset(con)
            if current is None or offset > current:
                set_offset(con, offset)
            message = update.get('message')
            if not isinstance(message, dict):
                continue
            sender, chat = message.get('from'), message.get('chat')
            if not isinstance(sender, dict) or not isinstance(chat, dict):
                continue
            admin_id = str(sender.get('id', ''))
            chat_id = str(chat.get('id', ''))
            if admin_id not in admins or chat.get('type') != 'private' or admin_id != chat_id:
                continue
            raw_text = message.get('text') or message.get('caption') or ''
            text = str(raw_text).strip()
            if text.startswith(('/start', '/help')):
                final_messages.append((update['update_id'], chat_id,
                    'برای خبر معمولی، لینک را بفرستید. برای درخواست Trial Reel، دستور /trial را پیش از لینک بنویسید؛ نمونه: /trial https://example.com/news. این ریل ابتدا برای غیردنبال‌کنندگان است و در صورت تشخیص عملکرد خوب ممکن است اینستاگرام آن را خودکار با دنبال‌کنندگان به‌اشتراک بگذارد.'))
                continue
            trial_match = re.match(r'^/trial(?:@[A-Za-z0-9_]+)?(?:\s|$)', text, re.IGNORECASE)
            malformed_trial = text.lower().startswith('/trial') and not trial_match
            request_type = 'trial' if trial_match else 'feed'
            link_text = text[trial_match.end():] if trial_match else text
            if malformed_trial:
                response = 'برای ساخت Trial Reel لینک را بعد از دستور بفرستید؛ نمونه: /trial https://example.com/news'
                con.execute('''INSERT OR IGNORE INTO submissions
                    (update_id,admin_id,chat_id,message_id,received_at,status,request_type,response,reply_sent)
                    VALUES (?,?,?,?,?,'rejected','trial',?,0)''',
                    (update['update_id'], admin_id, chat_id, int(message.get('message_id', 0)), time.time(), response))
                final_messages.append((update['update_id'], chat_id, response))
                continue
            matches = list(URL_RE.finditer(link_text))
            source_url = url_in(link_text)
            if source_url is None:
                response = ('فقط یک لینک خبر در هر پیام بفرستید.' if len(matches) > 1 else
                            'یک لینک کامل خبر بفرستید؛ رسانه باید در فهرست منابع بررسی‌شده باشد.')
                con.execute('''INSERT OR IGNORE INTO submissions
                    (update_id,admin_id,chat_id,message_id,received_at,status,request_type,response,reply_sent)
                    VALUES (?,?,?,?,?,'rejected',?,?,0)''',
                    (update['update_id'], admin_id, chat_id, int(message.get('message_id', 0)), time.time(), request_type, response))
                final_messages.append((update['update_id'], chat_id, response))
                continue
            try:
                normalized = canonical_url(source_url)
                source_key = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
            except Exception:
                con.execute('''INSERT OR IGNORE INTO submissions
                    (update_id,admin_id,chat_id,message_id,received_at,status,request_type,response,reply_sent)
                    VALUES (?,?,?,?,?,'rejected',?,?,0)''',
                    (update['update_id'], admin_id, chat_id, int(message.get('message_id', 0)),
                     time.time(), request_type, 'لینک قابل پردازش نیست. نشانی مقاله را بررسی کنید.'))
                continue
            con.execute('''INSERT OR IGNORE INTO submissions
                (update_id,admin_id,chat_id,message_id,source_url,source_key,received_at,status,request_type,response,reply_sent)
                VALUES (?,?,?,?,?,?,?,'received',?,'',0)''',
                (update['update_id'], admin_id, chat_id, int(message.get('message_id', 0)),
                 source_url, source_key, time.time(), request_type))
            saved = con.execute('SELECT status,response FROM submissions WHERE update_id=?', (update['update_id'],)).fetchone()
            if saved and saved['status'] == 'received':
                acknowledgements.append((update['update_id'], chat_id,
                    'لینک دریافت شد؛ منبع، تازگی و محتوای خبر را بررسی می‌کنم.'))
    return acknowledgements, final_messages


def recent_duplicate(con, source_key, except_update):
    row = con.execute('''SELECT status,media_id FROM submissions WHERE source_key=? AND update_id!=?
        AND status IN ('received','received_trial','processing','trial_processing','trial_pending','published','trial_published','needs_review') ORDER BY received_at DESC LIMIT 1''',
        (source_key, except_update)).fetchone()
    return dict(row) if row else None


def load_publish_env():
    from economy_news_translation import load_translation_env
    load_translation_env(HOME / 'sub/.env')
    path = HOME / '.kiani-instagram.env'
    if path.is_symlink() or not path.is_file():
        raise IntakeError('The existing private Instagram publishing configuration is unavailable.')
    info = path.stat()
    if ((hasattr(os, 'getuid') and info.st_uid != os.getuid()) or info.st_mode & 0o077):
        raise IntakeError('The existing Instagram configuration has unsafe ownership or permissions.')
    allowed = {'INSTAGRAM_USER_ID', 'INSTAGRAM_ACCESS_TOKEN', 'INSTAGRAM_GRAPH_API_VERSION'}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)$', line)
        if not match or match.group(1) not in allowed:
            continue
        try:
            parts = shlex.split(match.group(2), comments=True)
        except ValueError:
            continue
        if len(parts) == 1 and parts[0] and '$' not in parts[0]:
            os.environ.setdefault(match.group(1), parts[0])
    if not os.getenv('INSTAGRAM_USER_ID') or not os.getenv('INSTAGRAM_ACCESS_TOKEN') or not os.getenv('INSTAGRAM_GRAPH_API_VERSION'):
        raise IntakeError('The existing Instagram publisher credentials or Graph API version are missing.')
    os.environ['INSTAGRAM_PUBLISH_MODE'] = 'feed'


def classify(engine, ranked, con, material, now, *, allow_opinion=False, trial_relaxed=False):
    scored = {}
    for kind in ('crypto', 'economy'):
        ranked.configure_engine(kind)
        rows = engine.grade(con, [material], now)
        if len(rows) != 1:
            raise IntakeError('DeepSeek did not return one validated assessment.')
        row = rows[0]
        assessment = row['assessment']
        if trial_relaxed:
            scored[kind] = row
            continue
        eligible = (assessment['story_type'] == 'hard_news' or allow_opinion and
                    assessment['story_type'] == 'opinion' and assessment['usefulness']['points'] > 0)
        eligible = (eligible and
                    assessment['certainty'] != 'unknown' and
                    assessment['relevance']['points'] > 0)
        if eligible:
            scored[kind] = row
    if not scored:
        if allow_opinion:
            raise IntakeError('این پیوند برای Trial Reel واجد شرایط نشد؛ تازگی، ارتباط موضوعی، اعتبار منبع و محتوای مقاله بررسی نشد یا تأیید نشد.')
        raise IntakeError('This link did not qualify as a fresh, relevant hard-news post.')
    if len(scored) == 1:
        return next(iter(scored.items()))
    crypto_relevance = scored['crypto']['assessment']['relevance']['points']
    economy_relevance = scored['economy']['assessment']['relevance']['points']
    if trial_relaxed:
        return ('crypto', scored['crypto']) if crypto_relevance >= economy_relevance else ('economy', scored['economy'])
    if abs(crypto_relevance - economy_relevance) < 10:
        raise IntakeError('The news category is ambiguous; this link was not posted.')
    return ('crypto', scored['crypto']) if crypto_relevance > economy_relevance else ('economy', scored['economy'])


def publication_state(kind, source_url):
    import instagram_ranked_news as ranked
    from instagram_crypto_news import database
    target = canonical_url(source_url)
    with database(ranked.SOURCES[kind]) as con:
        row = con.execute('''SELECT n.id,n.title_fa,p.status,p.media_id FROM instagram_news n
            LEFT JOIN instagram_news_publications p ON p.story_id=n.id WHERE n.source_url=?''', (target,)).fetchone()
        return dict(row) if row else None


def hourly_count(con, now, exclude_story_id=None):
    start = now - (now % 3600)
    return con.execute('''SELECT COUNT(*) FROM instagram_news_publications
        WHERE status!='failed' AND ((started_at>=? AND started_at<?) OR (finished_at>=? AND finished_at<?))
        AND (? IS NULL OR story_id!=?)''',
        (start, start + 3600, start, start + 3600, exclude_story_id, exclude_story_id)).fetchone()[0]


def scheduled_slot_pending(kind, now, engine, ranked):
    local = datetime.fromtimestamp(now, engine.ISTANBUL)
    slot = f'hour-{local.hour:02d}'
    if slot not in ranked.HOURLY_SLOTS:
        return False
    minute = 0 if kind == 'crypto' else 30
    scheduled = local.replace(minute=minute, second=0, microsecond=0).timestamp()
    hour_start = local.replace(minute=0, second=0, microsecond=0).timestamp()
    return now <= scheduled < hour_start + 3600


def process_submission(con, record, runtime):
    import crypto_news_trial as engine
    import instagram_ranked_news as ranked
    from instagram_crypto_news import NewsError, database, publish, save_story
    from instagram_news_batch import guard, plan

    update_id = record['update_id']
    source_url, source_key = record['source_url'], record['source_key']
    with con:
        duplicate = recent_duplicate(con, source_key, update_id)
        if duplicate:
            raise IntakeError('این لینک قبلاً دریافت یا منتشر شده است؛ انتشار تکراری انجام نشد.')
        con.execute("UPDATE submissions SET status='processing',response='' WHERE update_id=? AND status='received'", (update_id,))
    now = time.time()
    ranked.configure_engine('crypto')
    blocked, _history = ranked.histories(now)
    if canonical_url(source_url) in blocked:
        raise IntakeError('این خبر قبلاً منتشر شده یا تلاش انتشار آن نیازمند بررسی است.')
    material = engine.source_material(dict(id='manual-' + str(update_id), source_url=source_url,
        title_original='', source_name=''), now)
    final_url = canonical_url(material['source_url'])
    if final_url in blocked:
        raise IntakeError('نشانی نهایی این خبر قبلاً منتشر شده یا تلاش انتشار آن نیازمند بررسی است.')
    final_key = hashlib.sha256(final_url.encode('utf-8')).hexdigest()
    with con:
        duplicate = recent_duplicate(con, final_key, update_id)
        if duplicate:
            raise IntakeError('این خبر قبلاً از نشانی نهایی دیگری دریافت یا منتشر شده است.')
        con.execute('UPDATE submissions SET source_url=?,source_key=? WHERE update_id=?', (final_url, final_key, update_id))

    trial_path = STATE / 'assessment.sqlite3'
    with sqlite3.connect(trial_path, timeout=15) as assessment_db:
        assessment_db.row_factory = sqlite3.Row
        os.chmod(trial_path, 0o600)
        engine.init_trial(assessment_db)
        kind, row = classify(engine, ranked, assessment_db, material, now)
        with con:
            con.execute('UPDATE submissions SET kind=? WHERE update_id=?', (kind, update_id))
        record['kind'] = kind
        ranked.configure_engine(kind)
        _blocked, history = ranked.histories(now)
        groups = engine.event_groups(assessment_db, [row], history)
        if not groups or groups[0].get('published_match'):
            raise IntakeError('همین رویداد قبلاً منتشر شده است؛ انتشار تکراری انجام نشد.')

        with ranked.locks(kind):
            with database(ranked.SOURCES[kind]) as production:
                now = time.time()
                blocked_now, _ = ranked.histories(now)
                if final_url in blocked_now:
                    raise IntakeError('این خبر در فاصله بررسی تا انتشار ثبت شده است؛ انتشار تکراری انجام نشد.')
                cap, quota = plan(True)
                if ranked.consumed(production, now) >= cap:
                    raise IntakeError('سقف روزانه یا ظرفیت قابل‌استفاده خبر برای این دسته تکمیل شده است.')
                if hourly_count(production, now):
                    raise IntakeError('در این ساعت از این دسته یک پست منتشر شده است؛ برای جلوگیری از ازدحام این لینک منتشر نشد.')
                if scheduled_slot_pending(kind, now, engine, ranked):
                    raise IntakeError('زمان انتشار برنامه‌ریزی‌شده همین دسته در این ساعت نزدیک است؛ این لینک منتشر نشد تا دو پست پشت سر هم قرار نگیرند.')
                reservation = guard()
                print('Manual news quota checked:', json.dumps(dict(category=kind,
                    category_day_cap=cap, category_posts_today=ranked.consumed(production, now),
                    remaining=quota.get('remaining'), reserved_units=reservation.get('reserved_units'))), flush=True)

                components = row['components']
                row['components'] = dict(impact=row['assessment']['impact']['points'],
                    relevance=round(row['assessment']['relevance']['points'] * .8),
                    usefulness=round(row['assessment']['usefulness']['points'] * .75),
                    sourcing=components['sourcing'], freshness=components['freshness'], attention=0)
                row['trial_score'] = sum(row['components'].values())
                row['coverage_outlets'] = [material['source_name']]
                publisher_root = Path.home() / 'kiani-instagram-publisher'
                if not publisher_root.is_dir():
                    raise IntakeError('The installed Instagram artwork assets are unavailable.')
                output = Path('/var/www/peerexo.com/public/instagram-rates/' +
                              ('news' if kind == 'crypto' else 'economy'))
                import instagram_news_renderer as renderer
                from PIL import Image
                original_hero = renderer.hero_image

                def safe_hero(story, cache):
                    image_url = story.get('image_url')
                    if not image_url:
                        return None
                    try:
                        safe_url = engine.checked_url(image_url, article=True)
                        request = Request(safe_url, headers={
                            'User-Agent': 'KianiExchange-NewsSelectorTrial/1.0',
                            'Accept': 'image/*'})
                        with build_opener(engine.PublisherRedirects()).open(request, timeout=20) as response:
                            final_url = engine.checked_url(response.geturl(), article=True)
                            if not response.headers.get_content_type().startswith('image/'):
                                raise ValueError('Not an approved source image')
                            data = response.read(10_000_001)
                        if len(data) > 10_000_000:
                            raise ValueError('Source image is too large')
                        with Image.open(io.BytesIO(data)) as opened:
                            image = opened.convert('RGB')
                            image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                            cache.mkdir(parents=True, exist_ok=True, mode=0o700)
                            target = cache / (hashlib.sha256(final_url.encode()).hexdigest() + '.jpg')
                            image.save(target, quality=95)
                            return image.copy()
                    except Exception as exc:
                        print('Approved source illustration unavailable:', type(exc).__name__, flush=True)
                        return None

                try:
                    renderer.hero_image = safe_hero
                    saved, paths, caption, manifest = ranked.prepare(assessment_db, row, kind, output, publisher_root)
                finally:
                    renderer.hero_image = original_hero
                saved['source_url'] = final_url
                saved['origin'] = 'manual'
                story_id = save_story(production, saved)
                with production:
                    production.execute('UPDATE instagram_news SET importance_score=?,importance_reasons=? WHERE id=?',
                        (row['trial_score'], json.dumps(row['components']), story_id))
                story = dict(production.execute('SELECT * FROM instagram_news WHERE id=?', (story_id,)).fetchone())
                public_base = 'https://peerexo.com/instagram-rates/' + ('news' if kind == 'crypto' else 'economy')
                manifest['manual_telegram_intake'] = dict(update_id=update_id, category=kind,
                    source_url=final_url, received_at=record['received_at'])
                manifest['news_v2_ranking'] = dict(score=row['trial_score'], components=row['components'],
                    outlets=[material['source_name']], version=ranked.VERSION)
                os.environ['INSTAGRAM_PUBLIC_MEDIA_BASE_URL'] = public_base
                sys.path.insert(0, str(publisher_root))
                import instagram_daily_rates as ig

                class FinalQuotaGuard:
                    def __getattr__(self, name):
                        return getattr(ig, name)

                    def _publish_container(self, container):
                        current = time.time()
                        if material['article_published_at'] < current - 86400:
                            raise NewsError('The source became stale before publication.')
                        if ranked.consumed(production, current, story_id) >= cap:
                            raise NewsError('The daily news limit was reached before publication.')
                        if hourly_count(production, current, story_id):
                            raise NewsError('A news post already occupies this hour.')
                        if scheduled_slot_pending(kind, current, engine, ranked):
                            raise NewsError('A scheduled news slot is imminent in this hour.')
                        guard()
                        if material['article_published_at'] < time.time() - 86400:
                            raise NewsError('The source became stale during final checks.')
                        return ig._publish_container(container)

                media_id = publish(production, [story], paths, caption, FinalQuotaGuard(), manifest)
                return kind, saved['title_fa'], media_id


from instagram_reel_usage import tracked as track_reel_usage

@track_reel_usage('admin_link')
def process_trial_submission(con, record, runtime):
    """Verify and queue a private-admin link as an isolated Trial Reel."""
    import crypto_news_trial as engine
    import instagram_ranked_news as ranked
    from instagram_crypto_news import NewsError, database
    from instagram_news_batch import guard
    from instagram_trial_reels import TrialReelError, create_trial

    update_id = record['update_id']
    source_url, source_key = record['source_url'], record['source_key']
    with con:
        duplicate = recent_duplicate(con, source_key, update_id)
        if duplicate:
            raise IntakeError('این لینک قبلاً دریافت یا منتشر شده است؛ ریل تکراری ساخته نشد.')
        con.execute("UPDATE submissions SET status='trial_processing',response='' WHERE update_id=? AND status='received'", (update_id,))
    now = time.time()
    ranked.configure_engine('crypto')
    blocked, _ = ranked.histories(now)
    if canonical_url(source_url) in blocked:
        raise IntakeError('این خبر قبلاً منتشر شده یا برایش تلاش انتشار ثبت شده است؛ ریل تکراری ساخته نشد.')
    material = engine.source_material(dict(id='trial-' + str(update_id), source_url=source_url,
        title_original='', source_name=''), now)
    final_url = canonical_url(material['source_url'])
    final_key = hashlib.sha256(final_url.encode('utf-8')).hexdigest()
    blocked, _ = ranked.histories(time.time())
    if final_url in blocked:
        raise IntakeError('نشانی نهایی این خبر قبلاً منتشر شده یا در انتظار انتشار است.')
    with con:
        duplicate = recent_duplicate(con, final_key, update_id)
        if duplicate:
            raise IntakeError('این خبر از نشانی نهایی دیگری قبلاً دریافت یا منتشر شده است.')
        con.execute('UPDATE submissions SET source_url=?,source_key=? WHERE update_id=?', (final_url, final_key, update_id))

    assessment_path = STATE / 'assessment.sqlite3'
    with sqlite3.connect(assessment_path, timeout=15) as assessment_db:
        assessment_db.row_factory = sqlite3.Row
        os.chmod(assessment_path, 0o600)
        engine.init_trial(assessment_db)
        # The admin explicitly chooses this Trial Reel experiment. Accept a
        # verified publisher's useful analysis/opinion as well as hard news;
        # the automatic daily selector remains hard-news-only.
        kind, row = classify(engine, ranked, assessment_db, material, time.time(), trial_relaxed=True)
        record['kind'] = kind
        ranked.configure_engine(kind)
        _blocked, history = ranked.histories(time.time())
        groups = engine.event_groups(assessment_db, [row], history)
        if not groups or groups[0].get('published_match'):
            raise IntakeError('همین رویداد قبلاً منتشر شده است؛ ریل تکراری ساخته نشد.')
        with ranked.locks(kind):
            blocked_now, _ = ranked.histories(time.time())
            if final_url in blocked_now:
                raise IntakeError('این خبر در فاصله بررسی تا انتشار ثبت شده است؛ ریل تکراری ساخته نشد.')
            try:
                guard()
            except Exception as exc:
                raise IntakeError('ظرفیت امن انتشار یا رزرو استوری در حال حاضر کافی نیست؛ ریل ساخته نشد.') from exc
            title, summary = ranked.translate(assessment_db, row)
            story = dict(source_url=final_url, source_name=material['source_name'],
                title_original=material['title_original'], title_fa=title, summary_fa=summary,
                article_published_at=material['article_published_at'],
                story_type=row['assessment']['story_type'])
            asset_root = Path.home() / 'kiani-instagram-publisher'
            if not asset_root.is_dir():
                raise IntakeError('فایل‌های طراحی رسمی برای Trial Reel در دسترس نیستند.')
            try:
                trial_id = create_trial(story, kind, origin='admin_link', asset_root=asset_root,
                    submission_id=update_id)
            except TrialReelError as exc:
                raise IntakeError(str(exc)) from None
    return kind, title, trial_id


def record_trial_results(con, token, results):
    for result in results:
        submission_id = result.get('submission_id')
        if not submission_id:
            continue
        status = result['status']
        if status == 'published':
            final_status = 'trial_published'
            response = ('Trial Reel منتشر شد؛ ابتدا به غیردنبال‌کنندگان نمایش داده می‌شود. اگر اینستاگرام عملکرد آن را خوب تشخیص دهد، ممکن است خودکار برای دنبال‌کنندگان نیز به‌اشتراک گذاشته شود.\n' +
                        result.get('title_fa', '') + '\nشناسه ریل: ' + str(result.get('media_id', '')))
        elif status == 'failed':
            final_status = 'rejected'
            response = 'Trial Reel آماده یا منتشر نشد؛ اینستاگرام وضعیت ساخت و محدودیت‌های انتشار را نپذیرفت. لینک را بررسی کنید و در صورت نیاز بعداً دوباره بفرستید.'
        else:
            final_status = 'needs_review'
            response = 'نتیجه انتشار Trial Reel قطعی نیست؛ برای جلوگیری از انتشار تکراری، تلاش خودکار متوقف شد و سهم امروز محفوظ ماند. وضعیت را در اینستاگرام بررسی کنید.'
        with con:
            con.execute('''UPDATE submissions SET status=?,title_fa=COALESCE(?,title_fa),media_id=COALESCE(?,media_id),
                response=?,reply_sent=0,error_code=? WHERE update_id=?''',
                (final_status, result.get('title_fa'), result.get('media_id'), response,
                 'TrialReel' + status.title(), submission_id))
    if results:
        deliver_unsent(con, token)


def finish(con, token, record, status, response, *, kind=None, title=None, media_id=None, code=None):
    with con:
        con.execute('''UPDATE submissions SET status=?,kind=COALESCE(?,kind),title_fa=COALESCE(?,title_fa),
            media_id=COALESCE(?,media_id),response=?,reply_sent=0,error_code=? WHERE update_id=?''',
            (status, kind, title, media_id, response, code, record['update_id']))
    if token:
        deliver_unsent(con, token)


def deliver_unsent(con, token):
    rows = con.execute('SELECT update_id,chat_id,response FROM submissions WHERE reply_sent=0 AND response!="" ORDER BY received_at LIMIT 20').fetchall()
    for row in rows:
        try:
            send_message(token, row['chat_id'], row['response'])
        except IntakeError as exc:
            print('Telegram reply deferred:', str(exc), flush=True)
            return
        with con:
            con.execute('UPDATE submissions SET reply_sent=1 WHERE update_id=?', (row['update_id'],))


def recover_interrupted(con):
    rows = con.execute("SELECT update_id,request_type FROM submissions WHERE status IN ('processing','trial_processing')").fetchall()
    if rows:
        with con:
            for row in rows:
                con.execute('''UPDATE submissions SET status='needs_review',response=?,reply_sent=0,
                    error_code='InterruptedProcessing' WHERE update_id=?''',
                    ('فرآیند هنگام اجرا متوقف شد. برای جلوگیری از انتشار تکراری، دوباره خودکار ارسال نمی‌شود؛ وضعیت پست یا ریل را در اینستاگرام بررسی کنید.',
                     row['update_id']))


def run_once(config_path, runtime):
    token, admins = private_json(config_path)
    load_publish_env()
    no_webhook(token)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = STATE / 'worker.lock'
    if lock.is_symlink():
        raise IntakeError('The intake worker lock path is unsafe.')
    with lock.open('a') as handle:
        os.chmod(lock, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        with open_database() as con:
            recover_interrupted(con)
            offset = get_offset(con)
            parameters = {'timeout': POLL_TIMEOUT, 'allowed_updates': ['message']}
            if offset is not None:
                parameters['offset'] = offset
            updates = telegram(token, 'getUpdates', parameters, timeout=POLL_TIMEOUT + 12)
            acknowledgements, messages = ingest(con, updates, admins)
            for _, chat_id, response in acknowledgements:
                try:
                    send_message(token, chat_id, response)
                except IntakeError as exc:
                    print('Telegram acknowledgement deferred:', str(exc), flush=True)
            for update_id, chat_id, response in messages:
                try:
                    send_message(token, chat_id, response)
                except IntakeError as exc:
                    print('Telegram reply deferred:', str(exc), flush=True)
                else:
                    with con:
                        con.execute('UPDATE submissions SET reply_sent=1 WHERE update_id=?', (update_id,))
            deliver_unsent(con, token)
            from instagram_reel_usage import deliver_notices
            deliver_notices(token, admins, send_message)
            try:
                from instagram_trial_reels import poll_pending
                results = poll_pending(publisher_root=HOME / 'kiani-instagram-publisher')
                record_trial_results(con, token, results)
            except Exception as exc:
                print('Trial Reel processing deferred:', type(exc).__name__, flush=True)
            record = con.execute("SELECT * FROM submissions WHERE status='received' ORDER BY received_at LIMIT 1").fetchone()
            if record is not None:
                record = dict(record)
                try:
                    if record.get('request_type') == 'trial':
                        kind, title, trial_id = process_trial_submission(con, record, runtime)
                        response = ('درخواست Trial Reel پذیرفته شد و ویدئو برای بررسی اینستاگرام آماده شده است. هنوز منتشر نشده؛ پس از آماده‌شدن، ابتدا برای غیردنبال‌کنندگان نمایش داده می‌شود و اینستاگرام دربارهٔ اشتراک‌گذاری خودکار با دنبال‌کنندگان تصمیم می‌گیرد.\n' +
                                    title + '\nشناسه پیگیری: ' + trial_id)
                        finish(con, token, record, 'trial_pending', response, kind=kind, title=title, media_id=trial_id)
                        print('Admin Trial Reel queued:', kind, trial_id, flush=True)
                    else:
                        kind, title, media_id = process_submission(con, record, runtime)
                        response = ('پست خبری منتشر شد.\n' + title + '\nشناسه پست: ' + media_id +
                            '\nارزیابی بازدید طبق سیاست خبر، دو ساعت پس از انتشار انجام می‌شود.')
                        finish(con, token, record, 'published', response, kind=kind, title=title, media_id=media_id)
                        print('Manual news published:', kind, media_id, flush=True)
                except IntakeError as exc:
                    code = re.sub(r'[^A-Za-z0-9]', '', str(exc))[:64] or 'Rejected'
                    finish(con, token, record, 'rejected', str(exc), code=code)
                    print('Manual news declined:', code, flush=True)
                except Exception as exc:
                    state = None
                    for kind in ([record.get('kind')] if record.get('kind') in {'crypto', 'economy'} else ['crypto', 'economy']):
                        try:
                            state = publication_state(kind, record['source_url'])
                        except Exception:
                            continue
                        if state and state.get('status') in {'publishing', 'needs_review', 'published'}:
                            record['kind'] = kind
                            break
                    uncertain = bool(state and state.get('status') in {'publishing', 'needs_review'})
                    already = bool(state and state.get('status') == 'published')
                    if already:
                        title = state.get('title_fa') or 'خبر'
                        finish(con, token, record, 'published', 'پست منتشر شده است؛ نتیجه API ثبت و تکرار ارسال مسدود شد.\n' + title,
                               kind=record.get('kind'), title=title, media_id=state.get('media_id'))
                    elif uncertain:
                        finish(con, token, record, 'needs_review',
                            'نتیجه درخواست انتشار قطعی نیست؛ برای جلوگیری از پست تکراری، ارسال خودکار متوقف شد. وضعیت اینستاگرام را بررسی کنید.',
                            code='UncertainPublish')
                    else:
                        finish(con, token, record, 'rejected',
                            'این خبر منتشر نشد. منبع، دسته‌بندی یا ظرفیت انتشار شرایط لازم را نداشت؛ لینک را بررسی کنید و در صورت نیاز بعداً دوباره بفرستید.',
                            code=type(exc).__name__)
                    print('Manual news processing stopped:', type(exc).__name__, flush=True)
            deliver_notices(token, admins, send_message)
            return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=CONFIG_DEFAULT)
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() == 0:
        parser.error('Run as the existing Instagram publisher user, without sudo.')
    os.umask(0o077)
    runtime = args.runtime.expanduser().resolve()
    sys.path.insert(0, str(runtime))
    sys.path.insert(0, str(runtime / 'selector_trial_runtime'))
    try:
        return run_once(args.config.expanduser(), runtime)
    except IntakeError as exc:
        print('Manual news intake stopped:', str(exc), flush=True)
        return 1
    except Exception as exc:
        print('Manual news intake stopped:', type(exc).__name__, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

