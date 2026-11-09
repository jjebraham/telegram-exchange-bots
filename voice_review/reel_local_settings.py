"""Optional private local-render settings. Defaults leave narration disabled."""
import os
from pathlib import Path
import stat
import tempfile

ALLOWED = {
    'REEL_ELEVENLABS_ENABLED', 'ELEVENLABS_MODEL', 'REEL_NARRATION_SPEED',
    'REEL_MUSIC_VOLUME', 'REEL_AUDIO_DUCKING_ENABLED', 'REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT',
    'REEL_PRONUNCIATION_ENABLED',
}


def path():
    return Path.home() / '.config/kiani-instagram-voice-review/local-render.env'


def read(location=None):
    location = Path(location or path())
    if not location.exists() and not location.is_symlink():
        return {}
    if location.is_symlink() or location.parent.is_symlink() or not location.is_file() or location.stat().st_size > 4096:
        raise ValueError('Unsafe local narration settings.')
    if os.name == 'posix':
        info = location.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('Local narration settings must be private and owned by the publisher.')
    result = {}
    for line in location.read_text(encoding='ascii').splitlines():
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        if not separator or name not in ALLOWED or name in result:
            raise ValueError('Invalid local narration setting.')
        result[name] = value
    for name in ('REEL_ELEVENLABS_ENABLED', 'REEL_AUDIO_DUCKING_ENABLED', 'REEL_PRONUNCIATION_ENABLED'):
        if name in result and result[name] not in ('true', 'false'):
            raise ValueError('Invalid narration feature flag.')
    if result.get('ELEVENLABS_MODEL', 'eleven_v4') != 'eleven_v4' or result.get('REEL_NARRATION_SPEED', '1.5') != '1.5':
        raise ValueError('Unreviewed narration model or speed.')
    if result.get('REEL_MUSIC_VOLUME', '0.20') != '0.20':
        raise ValueError('The reviewed music level is 20%.')
    if 'REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT' in result:
        raw = result['REEL_ELEVENLABS_MONTHLY_CHAR_LIMIT']
        if not raw.isdigit() or not 1 <= int(raw) <= 100_000_000:
            raise ValueError('Invalid monthly narration character cap.')
    return result


def load():
    for name, value in read().items():
        os.environ.setdefault(name, value)


def configure(enabled, location=None):
    """Persist an explicit flag; retain any chosen character cap and backup."""
    if not isinstance(enabled, bool):
        raise ValueError('An explicit narration enable/disable decision is required.')
    location = Path(location or path())
    old = read(location)
    location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix' and (location.parent.stat().st_uid != os.getuid() or location.parent.stat().st_mode & 0o077):
        raise ValueError('Local narration settings directory must be private.')
    backup = None
    if location.exists():
        fd, name = tempfile.mkstemp(prefix='local-render-backup-', suffix='.env', dir=location.parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(location.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        backup = Path(name)
    values = dict(old, REEL_ELEVENLABS_ENABLED='true' if enabled else 'false',
                  ELEVENLABS_MODEL='eleven_v4', REEL_NARRATION_SPEED='1.5',
                  REEL_MUSIC_VOLUME='0.20', REEL_AUDIO_DUCKING_ENABLED='true')
    fd, temporary = tempfile.mkstemp(prefix='.local-render-', dir=location.parent)
    try:
        with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as stream:
            stream.write('# Private local narration settings, parsed as data.\n')
            stream.write(''.join(name + '=' + value + '\n' for name, value in sorted(values.items())))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        if location.is_symlink():
            raise ValueError('Unsafe narration settings destination.')
        os.replace(temporary, location)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup
