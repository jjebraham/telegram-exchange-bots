"""Send reviewed comparison samples to the explicitly configured private channel."""
import hashlib
import json
from pathlib import Path
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

import reel_voice_registry as registry

CHAT_ID = -1004449700544
BOT_NAME = 'enpevobot'
CHAT_TITLE = 'en movie test'


class TelegramError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _request(token, method, *, fields=None, audio=None):
    if not isinstance(token, str) or not token or not all(c.isalnum() or c in ':-_' for c in token):
        raise TelegramError('Telegram bot configuration is invalid.')
    url = 'https://api.telegram.org/bot' + token + '/' + method
    if audio is None:
        body = json.dumps(fields or {}).encode('utf-8')
        content_type = 'application/json'
    else:
        boundary = 'kiani' + secrets.token_hex(16)
        chunks = []
        for key, value in (fields or {}).items():
            chunks.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="' + key +
                           '"\r\n\r\n' + str(value) + '\r\n').encode('utf-8'))
        chunks.append(('--' + boundary + '\r\nContent-Disposition: form-data; name="audio"; '
                       'filename="sample.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode('ascii'))
        chunks.append(audio)
        chunks.append(('\r\n--' + boundary + '--\r\n').encode('ascii'))
        body = b''.join(chunks)
        content_type = 'multipart/form-data; boundary=' + boundary
    request = Request(url, data=body, method='POST', headers={'Content-Type': content_type})
    try:
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            raw = response.read(1_000_001)
    except (HTTPError, URLError, OSError, TimeoutError):
        # Do not expose the request URL: Telegram URLs contain the bot token.
        raise TelegramError('Telegram request failed or its outcome is unknown.') from None
    if len(raw) > 1_000_000:
        raise TelegramError('Telegram response is too large.')
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise TelegramError('Telegram response is invalid.') from None
    if not isinstance(data, dict) or data.get('ok') is not True or not isinstance(data.get('result'), dict):
        raise TelegramError('Telegram did not confirm the request.')
    return data['result']


def verify_destination(token, request=_request):
    bot = request(token, 'getMe')
    if str(bot.get('username', '')).casefold() != BOT_NAME:
        raise TelegramError('Telegram bot identity does not match the requested bot.')
    chat = request(token, 'getChat', fields={'chat_id': CHAT_ID})
    if (chat.get('id') != CHAT_ID or chat.get('type') != 'channel' or
            str(chat.get('title', '')).strip().casefold() != CHAT_TITLE):
        raise TelegramError('Telegram channel identity does not match the requested destination.')


def deliver(con, token, *, request=_request):
    verify_destination(token, request=request)
    con.execute('''CREATE TABLE IF NOT EXISTS sample_deliveries (
        voice_id TEXT NOT NULL, sample_sha256 TEXT NOT NULL, model TEXT NOT NULL,
        chat_id INTEGER NOT NULL, status TEXT NOT NULL, message_id INTEGER,
        updated_at REAL NOT NULL, PRIMARY KEY(voice_id,sample_sha256,model,chat_id))''')
    results = []
    for row in registry.list_voices(con):
        if not row['available'] or not row['sample_path'] or row['sample_model'] != registry.MODEL:
            continue
        path = Path(row['sample_path'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 25_000_000:
            results.append({'name': row['name'], 'status': 'sample_unavailable'})
            continue
        audio = path.read_bytes()
        digest = hashlib.sha256(audio).hexdigest()
        if digest != row['sample_sha256']:
            results.append({'name': row['name'], 'status': 'sample_changed'})
            continue
        identity = (row['voice_id'], digest, registry.MODEL, CHAT_ID)
        con.execute('BEGIN IMMEDIATE')
        try:
            existing = con.execute('''SELECT status FROM sample_deliveries
                WHERE voice_id=? AND sample_sha256=? AND model=? AND chat_id=?''', identity).fetchone()
            if existing:
                con.commit()
                results.append({'name': row['name'], 'status': existing['status']})
                continue
            con.execute('INSERT INTO sample_deliveries VALUES(?,?,?,?,?,?,?)',
                        identity + ('sending', None, time.time()))
            con.commit()
        except BaseException:
            con.rollback()
            raise
        try:
            result = request(token, 'sendAudio', fields={
                'chat_id': CHAT_ID, 'caption': row['name'] + ' | ' + registry.MODEL + ' | 1.5×',
            }, audio=audio)
            message_id = result.get('message_id')
            if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id <= 0:
                raise TelegramError('Telegram did not confirm a message ID.')
        except Exception:
            con.execute('''UPDATE sample_deliveries SET status='unknown',updated_at=?
                WHERE voice_id=? AND sample_sha256=? AND model=? AND chat_id=?''',
                (time.time(),) + identity)
            results.append({'name': row['name'], 'status': 'unknown_needs_review'})
            continue
        con.execute('''UPDATE sample_deliveries SET status='sent',message_id=?,updated_at=?
            WHERE voice_id=? AND sample_sha256=? AND model=? AND chat_id=?''',
            (message_id, time.time()) + identity)
        results.append({'name': row['name'], 'status': 'sent'})
    return results

