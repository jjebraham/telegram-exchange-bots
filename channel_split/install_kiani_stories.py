"""Install only the dedicated story files and login-gated systemd timer."""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

FILES = ('kiani_story_state.py', 'kiani_story_worker.py', 'setup_kiani_stories.py',
         'requirements-stories.txt', 'KIANI_CHANNEL_STORIES.md')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-dir', type=Path, required=True)
    parser.add_argument('--venv', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'posix' or os.geteuid() == 0:
        raise ValueError('Run as the existing non-root publishing account; sudo is used only for units')
    project, venv = args.project_dir.resolve(), args.venv.resolve()
    home, user = Path.home().resolve(), getpass.getuser()
    for value in (str(home), str(project), str(venv), user):
        if not re.fullmatch(r'[A-Za-z0-9_./-]+', value):
            raise ValueError('Unsupported service path or account name')
    if not project.is_relative_to(home) or not (project / 'publish_channels.py').is_file():
        raise ValueError('Expected an existing publisher under the publishing account home')
    if not (venv / 'bin/python').is_file():
        raise ValueError('Install the dedicated story requirements before installing the timer')
    subprocess.run(['sudo', '-n', 'true'], check=True)
    source = Path(__file__).resolve().parent
    unit_path = Path('/etc/systemd/system')
    service = (source / 'systemd/kiani-channel-stories.service.in').read_text()
    for key, value in {'HOME': home, 'USER': user, 'PROJECT': project, 'VENV': venv}.items():
        service = service.replace('@' + key + '@', str(value))
    timer = (source / 'systemd/kiani-channel-stories.timer').read_text()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = home / 'kiani-image-backups' / ('channel-stories-' + stamp)
    backup.mkdir(parents=True, mode=0o700)
    previous = {}
    for name in FILES:
        path = project / name
        previous[str(path)] = path.exists()
        if path.exists():
            shutil.copy2(path, backup / name)
    for name in ('kiani-channel-stories.service', 'kiani-channel-stories.timer'):
        path = unit_path / name
        previous[str(path)] = path.exists()
        if path.exists():
            subprocess.run(['sudo', '-n', 'cp', '--preserve=mode,timestamps', str(path), str(backup / name)], check=True)
    (backup / 'manifest.json').write_text(json.dumps(previous, indent=2) + '\n')
    for relative in ('.config/kiani-stories', '.local/share/kiani-stories', '.local/state/kiani-stories'):
        directory = home / relative
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    for name in FILES:
        fd, temporary = tempfile.mkstemp(prefix='.story-install-', dir=project)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write((source / name).read_bytes())
            os.chmod(temporary, 0o644)
            os.replace(temporary, project / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    with tempfile.TemporaryDirectory(prefix='kiani-story-units-') as directory:
        for name, content in (('kiani-channel-stories.service', service), ('kiani-channel-stories.timer', timer)):
            path = Path(directory) / name
            path.write_text(content)
            subprocess.run(['sudo', '-n', 'install', '-m', '644', str(path), str(unit_path / name)], check=True)
    subprocess.run(['sudo', '-n', 'systemctl', 'daemon-reload'], check=True)
    subprocess.run(['sudo', '-n', 'systemd-analyze', 'verify',
                    str(unit_path / 'kiani-channel-stories.service'),
                    str(unit_path / 'kiani-channel-stories.timer')], check=True)
    subprocess.run(['sudo', '-n', 'systemctl', 'enable', '--now', 'kiani-channel-stories.timer'], check=True)
    print(json.dumps({'installed': list(FILES), 'backup': str(backup),
                      'timer': 'kiani-channel-stories.timer',
                      'login_ready': (home / '.config/kiani-stories/ready').exists(),
                      'story_published': False}, indent=2))


if __name__ == '__main__':
    main()
