"""Read a private credentials.env as data, never as a shell script."""
import os
from pathlib import Path
import re
import stat
import tempfile

NAMES = ('ELEVENLABS_API_KEY', 'KIANI_VOICE_TEST_BOT_TOKEN')


class CredentialError(ValueError):
    pass


def default_path():
    return Path.home() / '.config/kiani-instagram-voice-review/credentials.env'


def _validate(name, value):
    if name not in NAMES or not isinstance(value, str) or len(value) > 300:
        raise CredentialError('Credential configuration is invalid.')
    if value and not re.fullmatch(r'[A-Za-z0-9_:-]+', value):
        raise CredentialError('A credential contains unsupported characters.')
    if value and name == 'KIANI_VOICE_TEST_BOT_TOKEN' and not re.fullmatch(r'[0-9]{5,16}:[A-Za-z0-9_-]{20,100}', value):
        raise CredentialError('The test bot token format is invalid.')
    return value


def _check_directory(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise CredentialError('The private credentials directory is unsafe.')
    if os.name == 'posix':
        info = directory.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise CredentialError('The credentials directory must be private and owned by this user.')


def read(path=None):
    path = Path(path or default_path())
    if not path.exists() and not path.is_symlink():
        return {}
    _check_directory(path.parent)
    if path.is_symlink():
        raise CredentialError('The credentials file cannot be a symlink.')
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > 4096 or
                    os.name == 'posix' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077)):
                raise CredentialError('The credentials file must be private and owned by this user.')
            raw = stream.read(4097)
        text = raw.decode('ascii')
    except (OSError, UnicodeError):
        raise CredentialError('The private credentials file could not be read.') from None
    values = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise CredentialError('The credentials file is not valid KEY=value data.')
        name, value = line.split('=', 1)
        if name in values:
            raise CredentialError('The credentials file contains a duplicate key.')
        values[name] = _validate(name, value)
    return values


def get_secret(name, path=None):
    if name not in NAMES:
        raise CredentialError('Unsupported credential name.')
    environment = os.environ.get(name, '')
    if environment:
        return _validate(name, environment)
    return read(path).get(name, '')


def write(updates, path=None):
    path = Path(path or default_path())
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    _check_directory(path.parent)
    values = read(path)
    for name, value in updates.items():
        values[name] = _validate(name, value)
    content = '# Private Kiani Reel credentials. Parsed as data; do not source this file.\n'
    content += ''.join(name + '=' + values.get(name, '') + '\n' for name in NAMES)
    fd, temporary = tempfile.mkstemp(prefix='.credentials-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as stream:
            os.fchmod(stream.fileno(), 0o600) if hasattr(os, 'fchmod') else None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise CredentialError('The credentials file cannot be a symlink.')
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path

