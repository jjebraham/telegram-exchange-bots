"""Private preview client for ElevenLabs; never publishes or reads credentials from disk."""
from base64 import b64decode
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from reel_narration_timing import TimingError, apply_diacritics, build_script, word_starts


class VoiceError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _probe(path, ffprobe):
    try:
        response = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'json', str(path)], check=True, capture_output=True, timeout=30)
        duration = float(json.loads(response.stdout)['format']['duration'])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        raise VoiceError('Narration audio could not be verified.') from None
    if not 0.1 <= duration <= 300:
        raise VoiceError('Narration audio duration is outside the supported range.')
    return duration


def _generate(script, key, voice_id, model, timeout):
    payload = json.dumps({'text': script, 'model_id': model, 'language_code': 'fa'},
                         ensure_ascii=False).encode('utf-8')
    request = Request('https://api.elevenlabs.io/v1/text-to-speech/' + voice_id + '/with-timestamps',
                      data=payload, headers={'xi-api-key': key, 'Content-Type': 'application/json',
                                            'Accept': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(20_000_001)
    except HTTPError as exc:
        raise VoiceError('ElevenLabs request failed (HTTP ' + str(exc.code) + ').') from None
    except (URLError, TimeoutError, OSError):
        # Do not automatically retry an uncertain, potentially billable request.
        raise VoiceError('ElevenLabs request outcome is unavailable; review before retrying.') from None
    if len(raw) > 20_000_000:
        raise VoiceError('ElevenLabs response exceeds the size limit.')
    try:
        result = json.loads(raw)
        audio = b64decode(result['audio_base64'], validate=True)
        alignment = result['alignment']
    except (ValueError, TypeError, KeyError):
        raise VoiceError('ElevenLabs response is incomplete.') from None
    if not 100 <= len(audio) <= 12_000_000:
        raise VoiceError('ElevenLabs audio has an invalid size.')
    return audio, alignment


def synthesize_segment(display_text, cache_file, key, *, voice_id='TX3LPaxmHKxFdv7VOQHJ',
                       model='eleven_v4', speed=1.5, ffmpeg='ffmpeg', ffprobe='ffprobe', timeout=60,
                       spoken_script=None):
    """Return PCM WAV bytes and word start times; cache successful, verified results."""
    if not key or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', voice_id) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', model):
        raise VoiceError('Voice configuration is invalid.')
    try:
        script, tokens = build_script(display_text)
        if spoken_script is not None:
            script, tokens = apply_diacritics(script, tokens, spoken_script)
    except TimingError as exc:
        raise VoiceError(str(exc)) from None
    if len(script) > (10000 if model == 'eleven_v4' else 5000):
        raise VoiceError('Narration text exceeds the model limit.')
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not 0.5 <= speed <= 2:
        raise VoiceError('Narration speed is unsupported.')
    cache_file = Path(cache_file)
    if cache_file.is_symlink() or cache_file.parent.is_symlink():
        raise VoiceError('Unsafe narration cache path.')
    cache_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix':
        os.chmod(cache_file.parent, 0o700)
    identity = json.dumps({'schema': 2, 'script': script, 'display': [t.text for t in tokens], 'voice': voice_id, 'model': model,
                           'language': 'fa', 'speed': speed}, sort_keys=True, ensure_ascii=False)
    cache_key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    fd = os.open(str(cache_file), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    os.close(fd)
    if os.name == 'posix':
        os.chmod(cache_file, 0o600)
    con = sqlite3.connect(str(cache_file), timeout=120, isolation_level=None)
    try:
        import reel_narration_usage as usage
        usage.schema(con)
        con.execute('CREATE TABLE IF NOT EXISTS narration (cache_key TEXT PRIMARY KEY, audio BLOB NOT NULL, timings TEXT NOT NULL, sha256 TEXT NOT NULL)')
        # Commit a durable reservation before a billable call. A crash or lost
        # response cannot silently request and charge for the same text again.
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT audio,timings,sha256 FROM narration WHERE cache_key=?', (cache_key,)).fetchone()
        if row:
            audio, timings_json, checksum = row
            if hashlib.sha256(audio + timings_json.encode('utf-8')).hexdigest() != checksum:
                raise VoiceError('Cached narration checksum failed.')
            starts = json.loads(timings_json)
            if not isinstance(starts, list) or len(starts) != len(tokens):
                raise VoiceError('Cached narration timing is invalid.')
            con.commit()
            return {'audio': audio, 'starts': starts, 'cached': True, 'script': script,
                    'submitted_characters': 0, 'cache_key': cache_key}
        saved = usage.reserve(con, cache_key, voice_id, model, len(script))
        con.commit()
        newly_requested = saved is None
        if newly_requested:
            try:
                source, alignment = _generate(script, key, voice_id, model, timeout)
            except BaseException:
                con.execute("UPDATE narration_requests SET status='uncertain' WHERE cache_key=?", (cache_key,))
                raise
            con.execute("UPDATE narration_requests SET status='received',response_audio=?,response_alignment=? WHERE cache_key=?",
                        (source, json.dumps(alignment, ensure_ascii=False), cache_key))
        else:
            source, alignment = saved
        with tempfile.TemporaryDirectory(prefix='kiani-elevenlabs-') as temporary:
            root = Path(temporary)
            source_path, wav_path = root / 'source.audio', root / 'voice.wav'
            source_path.write_bytes(source)
            source_duration = _probe(source_path, ffprobe)
            try:
                starts = word_starts(script, tokens, alignment, source_duration, speed)
            except TimingError as exc:
                raise VoiceError(str(exc)) from None
            try:
                subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(source_path), '-af',
                                'atempo=' + str(speed), '-ar', '24000', '-ac', '1',
                                '-c:a', 'pcm_s16le', str(wav_path)], check=True, capture_output=True, timeout=120)
            except (OSError, subprocess.SubprocessError):
                raise VoiceError('Narration speed conversion failed.') from None
            duration = _probe(wav_path, ffprobe)
            if abs(duration - source_duration / speed) > max(.25, source_duration * .05):
                raise VoiceError('Accelerated narration duration did not match its timing.')
            if starts and starts[-1] > duration + .1:
                raise VoiceError('Narration timing extends beyond accelerated audio.')
            audio = wav_path.read_bytes()
        timings_json = json.dumps(starts)
        checksum = hashlib.sha256(audio + timings_json.encode('utf-8')).hexdigest()
        con.execute('BEGIN IMMEDIATE')
        con.execute('INSERT OR IGNORE INTO narration VALUES (?,?,?,?)', (cache_key, audio, timings_json, checksum))
        con.execute("UPDATE narration_requests SET status='verified',response_audio=NULL,response_alignment=NULL WHERE cache_key=?", (cache_key,))
        con.commit()
        return {'audio': audio, 'starts': starts, 'cached': not newly_requested, 'script': script,
                'submitted_characters': len(script) if newly_requested else 0, 'cache_key': cache_key}
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()
