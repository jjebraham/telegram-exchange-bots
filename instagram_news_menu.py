"""Durable, admin-bound format selection for a Telegram news link."""
import secrets
import time

EXPIRY_SECONDS = 30 * 60
FORMATS = {'reel': 'direct_reel', 'trial': 'trial', 'post': 'single',
           'slides': 'feed', 'story': 'story'}
LENGTHS = {'short', 'long'}


def init(con):
    con.execute('''CREATE TABLE IF NOT EXISTS news_menu (
        token TEXT PRIMARY KEY, update_id INTEGER NOT NULL UNIQUE,
        admin_id TEXT NOT NULL, chat_id TEXT NOT NULL, message_id INTEGER NOT NULL,
        source_url TEXT NOT NULL, source_key TEXT NOT NULL, created_at REAL NOT NULL,
        stage TEXT NOT NULL, request_type TEXT, reel_length TEXT,
        prompted_stage TEXT NOT NULL DEFAULT '')''')


def create(con, *, update_id, admin_id, chat_id, message_id, source_url,
           source_key, now=None):
    now = time.time() if now is None else now
    old = con.execute('SELECT token FROM news_menu WHERE update_id=?', (update_id,)).fetchone()
    if old:
        return old[0]
    token = secrets.token_urlsafe(12)
    con.execute('''INSERT INTO news_menu
        (token,update_id,admin_id,chat_id,message_id,source_url,source_key,created_at,stage)
        VALUES (?,?,?,?,?,?,?,?, 'format')''',
        (token, update_id, str(admin_id), str(chat_id), message_id, source_url, source_key, now))
    return token


def format_keyboard(token):
    def button(text, value):
        return {'text': text, 'callback_data': 'nm:' + token + ':' + value}
    return {'inline_keyboard': [
        [button('🎬 ریل', 'reel'), button('🧪 ریل آزمایشی', 'trial')],
        [button('🖼 پست تکی', 'post'), button('📑 پست چنداسلایدی', 'slides')],
        [button('📱 استوری', 'story'), button('✖️ انصراف', 'cancel')]]}


def length_keyboard(token):
    return {'inline_keyboard': [[
        {'text': '⚡ کوتاه: ۱۵ تا ۳۰ ثانیه', 'callback_data': 'nm:' + token + ':short'},
        {'text': '📖 بلند: تا ۹۰ ثانیه', 'callback_data': 'nm:' + token + ':long'}],
        [{'text': '✖️ انصراف', 'callback_data': 'nm:' + token + ':cancel'}]]}


def select(con, *, token, value, admin_id, chat_id, now=None):
    """Return a state transition; caller must commit selection and enqueue together."""
    now = time.time() if now is None else now
    row = con.execute('SELECT * FROM news_menu WHERE token=?', (token,)).fetchone()
    if row is None:
        return 'unknown', None
    row = dict(row)
    if row['admin_id'] != str(admin_id) or row['chat_id'] != str(chat_id):
        return 'forbidden', None
    if row['stage'] in {'ready', 'cancelled', 'expired'}:
        return 'already_' + row['stage'], row
    if now < row['created_at'] or now - row['created_at'] > EXPIRY_SECONDS:
        con.execute("UPDATE news_menu SET stage='expired' WHERE token=?", (token,))
        return 'expired', row
    if value == 'cancel':
        con.execute("UPDATE news_menu SET stage='cancelled' WHERE token=?", (token,))
        return 'cancelled', row
    if row['stage'] == 'format' and value in FORMATS:
        request_type = FORMATS[value]
        stage = 'length' if value in {'reel', 'trial'} else 'ready'
        con.execute('UPDATE news_menu SET stage=?,request_type=? WHERE token=?',
                    (stage, request_type, token))
        row.update(stage=stage, request_type=request_type)
        return stage, row
    if row['stage'] == 'length' and value in LENGTHS:
        con.execute("UPDATE news_menu SET stage='ready',reel_length=? WHERE token=?",
                    (value, token))
        row.update(stage='ready', reel_length=value)
        return 'ready', row
    return 'invalid', row
