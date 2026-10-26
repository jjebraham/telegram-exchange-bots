"""One-time private, interactive administrator login; never run through chat."""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from getpass import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from kiani_story_state import TARGETS
from kiani_story_worker import CONFIG, load_config, new_client, preflight, private_file


class SetupError(Exception):
    """A setup message written by this module, safe to display without secrets."""


def error_hint(error):
    if isinstance(error, SetupError):
        return str(error)
    name = type(error).__name__
    hints = {
        'ApiIdInvalidError': 'Telegram rejected the API application details. Check your API ID/hash privately.',
        'PhoneNumberInvalidError': 'Enter the administrator phone number in international format, starting with +.',
        'PhoneNumberBannedError': 'Telegram does not allow this phone number to log in.',
        'PhoneCodeExpiredError': 'The login code expired. Rerun setup and use the new code privately.',
        'PhoneCodeInvalidError': 'Telegram rejected the login code. Rerun setup and enter the new code privately.',
        'PasswordHashInvalidError': 'Telegram rejected the two-step password. Check it privately.',
        'PhoneMigrateError': 'Telegram redirected the login. Rerun setup to continue on the selected server.',
        'NetworkMigrateError': 'Telegram redirected the connection. Rerun setup to continue.',
        'UserMigrateError': 'Telegram redirected the account. Rerun setup to continue.',
        'TimeoutError': 'The Telegram connection timed out. Rerun setup when the connection is available.',
        'ConnectionError': 'The Telegram connection failed. Rerun setup when the connection is available.',
    }
    seconds = getattr(error, 'seconds', None)
    if name in {'FloodWaitError', 'FloodPremiumWaitError'} and isinstance(seconds, int):
        return f'Telegram requires a wait of {max(1, seconds)} seconds before another login attempt.'
    return hints.get(name, 'Setup could not finish. Share only the error label shown above, without login details.')


def write_private(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.story-config-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def prepare_account_switch(config_path: Path, old: dict, session_folder: Path) -> dict:
    """Archive only this worker's login; retain channel pins and delivery history."""
    session = session_folder / 'admin.session'
    if not old:
        if session.exists():
            raise SetupError('A dedicated session exists without its approved configuration')
        return {}
    if Path(old.get('session_path', '')).absolute() != session.absolute():
        raise SetupError('Account switch expected the dedicated story session path')
    paths = [session.with_name(session.name + suffix) for suffix in ('', '-journal', '-wal', '-shm')]
    paths = [path for path in paths if path.exists()]
    paths.append(config_path)
    for path in paths:
        private_file(path)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = config_path.parent / ('previous-account-' + stamp)
    backup.mkdir(mode=0o700)
    for path in paths:
        os.replace(path, backup / path.name)
    print('Previous account login saved privately. Enter the replacement account details below.')
    return {key: old[key] for key in ('channel_ids', 'state_db') if key in old}


@contextmanager
def setup_lock():
    import fcntl
    folder = Path.home() / '.local/state/kiani-stories'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / 'worker.lock').open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError('The story worker or another setup is active. Retry after it finishes.') from None
        yield


async def setup(args):
    if not args.check and not sys.stdin.isatty():
        raise SetupError('Run this login directly in your private server terminal')
    ready = CONFIG.with_name('ready')
    if ready.exists():
        ready.unlink()
    if args.check:
        config = load_config(CONFIG, require_enabled=False)
    else:
        old = {}
        if CONFIG.exists():
            private_file(CONFIG)
            old = json.loads(CONFIG.read_text(encoding='utf-8'))
        session_folder = Path.home() / '.local/share/kiani-stories'
        session_folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if args.switch_account:
            old = prepare_account_switch(CONFIG, old, session_folder)
        print('Use the Telegram administrator account for both channels.')
        print('API application details are available privately at https://my.telegram.org/apps')
        api_id_text = str(old.get('api_id') or input('Telegram API ID: ').strip())
        if not api_id_text.isascii() or not api_id_text.isdecimal():
            raise SetupError('The Telegram API ID must contain digits only.')
        api_id = int(api_id_text)
        api_hash = old.get('api_hash') or getpass('Telegram API hash (hidden): ').strip()
        if not isinstance(api_id, int) or api_id <= 0 or not re.fullmatch(r'[0-9a-fA-F]{32}', api_hash):
            raise SetupError('Valid Telegram application details are required')
        session_path = session_folder / 'admin.session'
        # An unrelated pre-existing account session is never selected implicitly.
        if session_path.exists() and not old:
            raise SetupError('A dedicated session already exists without its approved configuration')
        from publish_channels import _load_local_env, _kiani_forward_db_path
        _load_local_env()
        config = {'version': 1, 'api_id': api_id, 'api_hash': api_hash,
                  'session_path': str(session_path), 'expected_user_id': old.get('expected_user_id', 0),
                  'receipt_db': str(_kiani_forward_db_path().resolve()),
                  'state_db': old.get('state_db') or str(Path.home() / '.local/state/kiani-stories/delivery.sqlite3'),
                  'channel_ids': old.get('channel_ids', {}), 'enabled': False}
        write_private(CONFIG, config)
    client = new_client(config, interactive=not args.check)
    try:
        await client.connect()
        if not args.check:
            await client.start(phone=lambda: input('Administrator phone number: ').strip(),
                               code_callback=lambda: getpass('Telegram login code (hidden): ').strip(),
                               password=lambda: getpass('Telegram two-step password, if requested (hidden): '))
            me = await client.get_me()
            if me.bot or (config['expected_user_id'] and config['expected_user_id'] != me.id):
                raise SetupError('The account does not match the approved administrator')
            config['expected_user_id'] = me.id
            pinned = {}
            for handle in TARGETS:
                entity = await client.get_entity('@' + handle)
                if not entity.broadcast:
                    raise SetupError('Expected the two public broadcast channels')
                if config['channel_ids'].get(handle, entity.id) != entity.id:
                    raise SetupError('Channel identity changed; keep the existing approved channel pins')
                pinned[handle] = entity.id
            config['channel_ids'] = pinned
        report = await preflight(client, config)
        config['enabled'] = all(value['ready'] for value in report.values())
        config['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
        write_private(CONFIG, config)
        if config['enabled']:
            write_private(ready, {'checked_at_utc': config['checked_at_utc']})
            print('READY: the next successful 12:10 Istanbul post can be shared to both channel stories.')
            print('Requested expiry: exactly 48 hours. No story has been posted during setup.')
        else:
            if ready.exists():
                ready.unlink()
            print('NOT ENABLED: channel story permission/boost checks must pass first.')
        print(json.dumps(report, indent=2))
    finally:
        await client.disconnect()
        path = Path(config['session_path'])
        if path.exists():
            os.chmod(path, 0o600)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Recheck the existing approved login without a new login')
    mode.add_argument('--switch-account', action='store_true',
                      help='Pause stories, privately archive the previous login, and request new API details and account login')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        with setup_lock():
            asyncio.run(setup(args))
    except Exception as error:
        print('SETUP STOPPED:', type(error).__name__)
        print(error_hint(error))
        print('Keep API hashes, login codes and session files in your private terminal; do not paste them into chat.')
        raise SystemExit(1) from None
