"""Export and apply an explicitly human-edited comparison review sheet."""
import json
import os
from pathlib import Path
import tempfile

import reel_voice_registry as registry


def export_sheet(con, destination):
    destination = Path(destination)
    if destination.is_symlink() or destination.parent.is_symlink():
        raise registry.RegistryError('Unsafe review sheet path.')
    entries = []
    for voice in registry.list_voices(con):
        scored = voice['scores'] is not None
        entries.append({
            'name': voice['name'], 'voice_id': voice['voice_id'],
            'available': bool(voice['available']), 'verified': bool(voice['verified']),
            'sample_path': voice['sample_path'], 'sample_sha256': voice['sample_sha256'],
            'scores': json.loads(voice['scores']) if scored else {key: None for key in registry.CRITERIA},
            'notes': voice['notes'], 'serious_error': bool(voice['serious_error']) if scored else None,
            'approved': bool(voice['approved']), 'enabled': bool(voice['enabled']),
            'rating_status': voice['rating_status'], 'evaluation_enabled': bool(voice['evaluation_enabled']),
        })
    result = {'model': registry.MODEL, 'speed': registry.SPEED, 'sample_text': registry.SAMPLE_TEXT,
              'instructions': 'Scores are provisional by default. Final reviews require rating_status=final and explicit approval. Evaluation enrollment uses the separate enroll-evaluation command.',
              'voices': entries}
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = None
    if destination.exists():
        if not destination.is_file() or destination.stat().st_size > 1_000_000:
            raise registry.RegistryError('Existing review sheet cannot be backed up safely.')
        old = destination.read_bytes()
        backup_fd, backup_name = tempfile.mkstemp(prefix='review-backup-', suffix='.json', dir=str(destination.parent))
        with os.fdopen(backup_fd, 'wb') as out:
            out.write(old)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(backup_name, 0o600)
        backup = Path(backup_name)
    fd, temporary = tempfile.mkstemp(prefix='.voice-review-', dir=str(destination.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup


def apply_sheet(con, source):
    source = Path(source)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 1_000_000:
        raise registry.RegistryError('Review sheet is missing or unsafe.')
    data = json.loads(source.read_text(encoding='utf-8'))
    if (data.get('model') != registry.MODEL or data.get('speed') != registry.SPEED or
            data.get('sample_text') != registry.SAMPLE_TEXT or not isinstance(data.get('voices'), list)):
        raise registry.RegistryError('Review sheet does not match the comparison settings.')
    seen = set()
    con.execute('BEGIN IMMEDIATE')
    try:
        updated = 0
        for entry in data['voices']:
            if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
                raise registry.RegistryError('Invalid review entry.')
            name = entry['name']
            if name.casefold() in seen:
                raise registry.RegistryError('Duplicate voice in review sheet.')
            seen.add(name.casefold())
            row = con.execute('SELECT * FROM voices WHERE name=?', (name,)).fetchone()
            if not row or row['voice_id'] != entry.get('voice_id') or row['sample_sha256'] != entry.get('sample_sha256'):
                raise registry.RegistryError('Voice identity or sample changed since export.')
            scores = entry.get('scores')
            if isinstance(scores, dict) and set(scores) == set(registry.CRITERIA) and all(v is None for v in scores.values()):
                if entry.get('approved') or entry.get('rating_status', 'final') == 'final' and entry.get('enabled'):
                    raise registry.RegistryError('Unscored voices cannot be approved or enabled.')
                continue
            status = entry.get('rating_status', 'final')
            if status not in ('final', 'provisional'):
                raise registry.RegistryError('Invalid rating status.')
            # Exported experimental enablement is informational, not permission
            # to create or remove evaluation enrollment through the review sheet.
            registry.review(con, name, scores, entry.get('notes', ''),
                            serious_error=entry.get('serious_error'), approved=entry.get('approved'),
                            enabled=entry.get('enabled') if status == 'final' else False, final=status == 'final')
            updated += 1
        con.commit()
        return updated
    except BaseException:
        con.rollback()
        raise
