"""Protected Runpod API key storage, parsed as data rather than shell code."""
import os
from pathlib import Path
import stat


class SecretError(ValueError):
    pass


def _check_directory(root):
    if root.is_symlink() or not root.is_dir():
        raise SecretError('Unsafe Runpod configuration directory.')
    info = root.stat()
    if hasattr(os, 'getuid') and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise SecretError('Runpod configuration directory must be private and owned by this user.')


def _validate(key):
    if (not isinstance(key, str) or not 8 <= len(key) <= 512 or
            any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise SecretError('Runpod API key has an unsupported format.')
    return key


def read(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return ''
    _check_directory(path.parent)
    if path.is_symlink():
        raise SecretError('Runpod credentials cannot be a symlink.')
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_size > 1024 or
                    hasattr(os, 'getuid') and (info.st_uid != os.getuid() or info.st_mode & 0o077)):
                raise SecretError('Runpod credentials must be private and owned by this user.')
            text = stream.read(1025).decode('ascii')
    except (OSError, UnicodeError):
        raise SecretError('Unable to read Runpod credentials safely.') from None
    if not text.endswith('\n') or text.count('\n') != 1 or not text.startswith('RUNPOD_API_KEY='):
        raise SecretError('Invalid Runpod credentials file.')
    return _validate(text[len('RUNPOD_API_KEY='):-1])


def write(path, key):
    path = Path(path)
    key = _validate(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _check_directory(path.parent)
    existing = read(path)
    if existing:
        if existing != key:
            raise SecretError('A different Runpod key is already configured; preserve it for review.')
        return
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        raise SecretError('Runpod credentials changed concurrently; no overwrite performed.') from None
    try:
        with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as out:
            out.write('RUNPOD_API_KEY=' + key + '\n')
            out.flush()
            os.fsync(out.fileno())
        os.chmod(path, 0o600)
    except OSError:
        raise SecretError('Could not safely write Runpod credentials; check the private file.') from None
