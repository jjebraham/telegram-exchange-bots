"""Calculate a fresh Hawala snapshot using the running bot's approved pipeline."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

CODES = ('USD', 'EUR', 'GBP', 'CAD', 'AUD', 'SEK', 'TRY')


class HawalaSourceError(RuntimeError):
    pass


class DiscardOutput:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def running_calculator(root):
    """Reuse the existing interpreter and private environment, without logging it."""
    root = Path(root).expanduser()
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
        raise HawalaSourceError('The existing Hawala runtime directory is unavailable')
    root = root.resolve()
    runtime = root / 'hawala_runtime.py'
    for name in ('hawala_runtime.py', 'hawala_bot.py', 'pricing_client.py'):
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
            raise HawalaSourceError('The existing Hawala calculator files are unavailable')
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            args = [part.decode(errors='strict') for part in (proc / 'cmdline').read_bytes().split(b'\0') if part]
            if not args:
                continue
            cwd = Path(os.readlink(proc / 'cwd'))
            matches = [Path(arg) if Path(arg).is_absolute() else cwd / arg for arg in args if arg.endswith('.py')]
            if runtime not in [path.resolve() for path in matches]:
                continue
            environment = {}
            for item in (proc / 'environ').read_bytes().split(b'\0'):
                if b'=' in item:
                    key, value = item.split(b'=', 1)
                    environment[key.decode()] = value.decode()
            executable = args[0] if Path(args[0]).is_absolute() else shutil.which(args[0], path=environment.get('PATH'))
            if not executable or not Path(executable).is_file() or not Path(executable).name.startswith('python'):
                raise HawalaSourceError('The running Hawala interpreter could not be resolved')
            found.append((executable, environment))
        except (OSError, UnicodeError, ValueError):
            continue
    if len(found) != 1:
        raise HawalaSourceError('Expected one running Hawala runtime owned by the publisher user')
    return root, found[0][0], found[0][1]


def validate(payload):
    if not isinstance(payload, dict) or payload.get('source') != 'kiani-hawala' or payload.get('calculation_mode') != 'readonly':
        raise HawalaSourceError('The Hawala calculator did not return a verified calculation')
    rates = payload.get('rates')
    if not isinstance(rates, dict) or set(rates) != set(CODES):
        raise HawalaSourceError('The Hawala calculator must return all seven currencies')
    if any(type(rates[code]) is not int or rates[code] <= 0 for code in CODES):
        raise HawalaSourceError('The Hawala calculator returned an invalid Toman quote')
    try:
        stamp = datetime.fromisoformat(payload['generated_at'])
        if stamp.tzinfo is None:
            raise ValueError()
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        if not -60 <= age <= 900:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise HawalaSourceError('The calculated Hawala snapshot is not fresh') from None
    return payload


def fresh_snapshot(root=None):
    root = root or os.getenv('INSTAGRAM_HAWALA_RUNTIME_ROOT', str(Path.home() / 'kiani-hawala-bot'))
    try:
        root, executable, environment = running_calculator(root)
    except (OSError, UnicodeError, ValueError):
        raise HawalaSourceError('The running Hawala calculator could not be located') from None
    environment.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    try:
        result = subprocess.run(
            [executable, str(Path(__file__).resolve()), '--calculator-child', '--root', str(root)],
            cwd=root, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=180,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise HawalaSourceError('The read-only Hawala calculation could not finish') from None
    # Never relay private bot/library stderr or exception messages.
    if result.returncode or len(result.stdout) > 20_000:
        raise HawalaSourceError('The read-only Hawala calculation failed; no rates substituted')
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise HawalaSourceError('The read-only Hawala calculation returned invalid JSON') from None
    return validate(payload)


def calculator_child(root):
    logging.disable(logging.CRITICAL)
    started = datetime.now(timezone.utc)
    with redirect_stdout(DiscardOutput()), redirect_stderr(DiscardOutput()):
        sys.path.insert(0, str(Path(root).resolve()))
        import telebot.apihelper

        def forbidden_telegram_request(*args, **kwargs):
            raise HawalaSourceError('Telegram requests are disabled in the read-only calculator')

        # Enforce isolation from Telegram even if the bot adds an error alert.
        telebot.apihelper._make_request = forbidden_telegram_request
        bot = importlib.import_module('hawala_bot')
        runtime = importlib.import_module('hawala_runtime')
        runtime.install_dynamic_pricing(bot)
        # This is a new process. Explicitly require a newly fetched FX response;
        # the long-lived bot's stale in-memory fallback is not used here.
        bot._fx_crosses_cache = None
        bot._fx_crosses_cache_fetched_at = None
        rates = bot.calculate_hawala_rates()
    if rates is None:
        raise HawalaSourceError('The existing calculator could not obtain all required live inputs')
    payload = dict(source='kiani-hawala', calculation_mode='readonly',
                   calculator='hawala_runtime.install_dynamic_pricing',
                   calculation_started_at=started.isoformat(),
                   generated_at=datetime.now(timezone.utc).isoformat(), rates=rates)
    return validate(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calculator-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--check', action='store_true', help='Calculate fresh quotes without sending any post')
    args = parser.parse_args()
    if not args.calculator_child and not args.check:
        parser.error('Use --check for the read-only calculation')
    payload = calculator_child(args.root) if args.calculator_child else fresh_snapshot(args.root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__}))
        raise SystemExit(1)
