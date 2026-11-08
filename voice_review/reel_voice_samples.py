"""Create private, comparable ElevenLabs samples; never publish to Instagram."""
import hashlib
import os
from pathlib import Path
import tempfile

import reel_voice_registry as registry
from reel_elevenlabs import VoiceError, synthesize_segment


def generate(con, directory, cache_file, key, *, ffmpeg='ffmpeg', ffprobe='ffprobe', progress=None):
    directory = Path(directory)
    if directory.is_symlink():
        raise registry.RegistryError('Unsafe sample directory.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix':
        os.chmod(directory, 0o700)
    results = []
    for row in registry.list_voices(con):
        if not row['available'] or not row['voice_id']:
            results.append({'name': row['name'], 'status': 'unavailable'})
            continue
        try:
            if progress:
                progress(row['name'])
            output = synthesize_segment(registry.SAMPLE_TEXT, cache_file, key, voice_id=row['voice_id'],
                                        model=registry.MODEL, speed=registry.SPEED, ffmpeg=ffmpeg, ffprobe=ffprobe)
            digest = hashlib.sha256(output['audio']).hexdigest()
            path = directory / (row['voice_id'] + '-' + digest[:16] + '.wav')
            if path.is_symlink():
                raise registry.RegistryError('Unsafe sample path.')
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise registry.RegistryError('Conflicting existing sample.')
            fd, temporary = tempfile.mkstemp(prefix='.sample-', dir=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(output['audio'])
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                if not path.exists():
                    os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            registry.save_sample(con, row['name'], path)
            results.append({'name': row['name'], 'voice_id': row['voice_id'],
                            'status': 'ready', 'cached': output['cached'],
                            'identity_confirmed': bool(row['verified'])})
        except (VoiceError, registry.RegistryError, OSError) as exc:
            # API/network failures can be billable; never retry automatically.
            results.append({'name': row['name'], 'status': 'failed', 'error_type': type(exc).__name__})
    return results

