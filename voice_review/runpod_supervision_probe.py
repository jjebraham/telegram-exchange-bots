#!/usr/bin/env python3
"""Verify bounded systemd worker supervision without any Pod or API access."""
import argparse
from pathlib import Path
import subprocess
import sys
import time
import uuid

from runpod_systemd_guard import SupervisionError, validate_current_unit


def validate_with_retry(unit, *, wait=time.sleep, attempts=10):
    for attempt in range(attempts):
        try:
            return validate_current_unit(unit)
        except SupervisionError:
            if attempt + 1 == attempts:
                raise
            wait(.3)
    raise SupervisionError('Worker supervision could not be verified.')


def check(home, *, runner=subprocess.run):
    unit = 'kiani-runpod-api-probe-' + uuid.uuid4().hex + '.service'
    command = ['systemd-run', '--user', '--quiet', '--wait', '--collect', '--unit=' + unit,
               '--property=Type=exec', '--property=RuntimeMaxSec=420s',
               '--property=TimeoutStopSec=10s', '--setenv=HOME=' + str(Path(home).resolve()),
               sys.executable, str(Path(__file__).resolve()), '--check', unit]
    try:
        result = runner(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        raise SupervisionError('Unable to run the bounded worker preflight.') from None
    if result.returncode:
        raise SupervisionError('The bounded worker preflight did not pass.')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check')
    args = parser.parse_args()
    try:
        if args.check:
            validate_with_retry(args.check)
        else:
            check(Path.home())
            print('Bounded systemd worker preflight passed. No Pod or API request was made.')
    except SupervisionError as exc:
        print('Bounded worker preflight stopped:', str(exc), file=sys.stderr)
        raise SystemExit(1)
