"""Validate that a test worker is supervised by its bounded systemd unit."""
import os
import re
import subprocess


class SupervisionError(RuntimeError):
    pass


def duration_seconds(text):
    if not isinstance(text, str):
        raise SupervisionError('Invalid systemd duration.')
    text = text.strip()
    if re.fullmatch(r'\d+', text):
        return int(text) / 1000000  # RuntimeMaxUSec is in microseconds.
    pattern = re.compile(r'(\d+(?:\.\d+)?)\s*(us|ms|min|h|s)')
    matches = list(pattern.finditer(text))
    if not matches or pattern.sub('', text).strip():
        raise SupervisionError('Unrecognized systemd duration.')
    scale = {'us': .000001, 'ms': .001, 's': 1, 'min': 60, 'h': 3600}
    return sum(float(m.group(1)) * scale[m.group(2)] for m in matches)


def validate_properties(text, pid, *, maximum_seconds=420):
    values = {}
    for line in str(text).splitlines():
        key, separator, value = line.partition('=')
        if separator and key in {'MainPID', 'ActiveState', 'RuntimeMaxUSec'}:
            if key in values:
                raise SupervisionError('Duplicate systemd property.')
            values[key] = value.strip()
    if values.get('ActiveState') != 'active' or values.get('MainPID') != str(pid):
        raise SupervisionError('The current worker is not the supervised main process.')
    duration = duration_seconds(values.get('RuntimeMaxUSec'))
    if not 0 < duration <= maximum_seconds:
        raise SupervisionError('The worker does not have a safe runtime limit.')
    return True


def validate_current_unit(unit, *, runner=subprocess.run):
    if not isinstance(unit, str) or not re.fullmatch(r'kiani-runpod-api-probe-[a-f0-9]{32}\.service', unit):
        raise SupervisionError('Invalid probe unit.')
    try:
        result = runner(['systemctl', '--user', 'show', unit, '-p', 'MainPID', '-p', 'ActiveState',
                         '-p', 'RuntimeMaxUSec'], capture_output=True, text=True, timeout=8,
                        stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        raise SupervisionError('Unable to verify systemd supervision.') from None
    if result.returncode:
        raise SupervisionError('Unable to verify systemd supervision.')
    return validate_properties(result.stdout, os.getpid())
