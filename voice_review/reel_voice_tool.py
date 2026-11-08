#!/usr/bin/env python3
"""Private voice discovery, sample review and Telegram comparison utility."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import warnings

import reel_voice_discovery as discovery
import reel_voice_credentials as credentials
import reel_voice_registry as registry
import reel_voice_review as review
import reel_voice_samples as samples
import reel_voice_telegram as telegram


def secret(name, prompt):
    value = credentials.get_secret(name)
    if value:
        return value
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        return getpass.getpass(prompt).strip()


def print_discovery(result):
    for row in result:
        print(row['name'])
        print('  Configured ID:', row['configured_id'] or 'not yet established')
        print('  Available in this account:', json.dumps(row['account_matches'], ensure_ascii=False))
        print('  Shared-library name matches:', json.dumps(row['shared_matches'], ensure_ascii=False))
        if row.get('shared_error'):
            print('  Shared-library check:', row['shared_error'])
        if row.get('shared_search_incomplete'):
            print('  Shared-library search was incomplete.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path,
                        default=Path.home() / '.local/state/kiani-instagram-voice-review')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('discover', help='Read-only voice ID lookup; no synthesis.')
    sub.add_parser('configure-secrets', help='Create or update a private credentials.env file.')
    sub.add_parser('samples', help='Generate available voices; ElevenLabs charges may apply.')
    sub.add_parser('compare', help='Check private channel, generate samples and send them.')
    sub.add_parser('send', help='Send prepared samples to the specified private channel.')
    sub.add_parser('show', help='List voice availability and review status.')
    sub.add_parser('review-export', help='Write editable review.json.')
    sub.add_parser('review-apply', help='Apply explicit human decisions from review.json.')
    human = sub.add_parser('review', help='Score and approve voices interactively in this terminal.')
    human.add_argument('names', nargs='*', default=['Sahar', 'Aylin', 'Shahram', 'Adrian'])
    sub.add_parser('usage', help='Read local submitted-character accounting; no API requests.')
    confirm = sub.add_parser('confirm', help='Confirm an available account voice ID.')
    confirm.add_argument('name')
    confirm.add_argument('voice_id')
    add = sub.add_parser('add', help='Add a test-only candidate.')
    add.add_argument('name')
    add.add_argument('--voice-id')
    remove = sub.add_parser('remove', help='Remove a candidate; selection history remains.')
    remove.add_argument('name')
    args = parser.parse_args()
    if args.action == 'configure-secrets':
        credentials.read()
        updates = {}
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            for name, label in (('ELEVENLABS_API_KEY', 'ElevenLabs API key'),
                                ('KIANI_VOICE_TEST_BOT_TOKEN', 'Private test bot token')):
                value = getpass.getpass(label + ' (hidden; Enter to keep or skip): ').strip()
                if value:
                    updates[name] = value
        path = credentials.write(updates)
        print('Private credentials file:', path)
        print('Narration remains disabled in production; no network request was made.')
        return
    if args.action == 'discover':
        key = secret('ELEVENLABS_API_KEY', 'ElevenLabs API key (hidden): ')
        print_discovery(discovery.inspect(key))
        print('Read-only lookup complete. Name matches require human confirmation.')
        return
    if args.action == 'usage':
        from reel_narration_usage import report
        for label, path in (
                ('Reels and previews', Path.home() / '.local/state/kiani-instagram-trial-reels/narration-cache.sqlite3'),
                ('Comparison samples', args.state_dir / 'narration-cache.sqlite3')):
            print(label + ':', json.dumps(report(path), ensure_ascii=False))
        print('Earlier API use is not reconstructed. Actual credits and charges must be checked in ElevenLabs.')
        return
    state = args.state_dir.expanduser()
    con = registry.connect(state / 'voices.sqlite3')
    try:
        registry.seed(con)
        if args.action in ('samples', 'compare'):
            key = secret('ELEVENLABS_API_KEY', 'ElevenLabs API key (hidden): ')
            token = None
            if args.action == 'compare':
                token = secret('KIANI_VOICE_TEST_BOT_TOKEN', 'Private test bot token (hidden): ')
                telegram.verify_destination(token)
                print('Private Telegram bot and channel verified.', flush=True)
                print('Checking account and shared-library voice IDs...', flush=True)
                print_discovery(discovery.inspect(key))
            account = discovery.account_voices(key)
            registry.refresh_access(con, account)
            results = samples.generate(con, state / 'samples', state / 'narration-cache.sqlite3', key,
                                       progress=lambda name: print('Preparing:', name, flush=True))
            print(json.dumps(results, ensure_ascii=False, indent=2))
            print('Sample generation attempted; ElevenLabs may charge for API requests.')
            if args.action == 'compare':
                print(json.dumps(telegram.deliver(con, token), ensure_ascii=False, indent=2))
                backup = review.export_sheet(con, state / 'review.json')
                if backup:
                    print('Previous review sheet backup:', backup)
                print('Editable review sheet:', state / 'review.json')
        elif args.action == 'send':
            token = secret('KIANI_VOICE_TEST_BOT_TOKEN', 'Private test bot token (hidden): ')
            print(json.dumps(telegram.deliver(con, token), ensure_ascii=False, indent=2))
            print('An uncertain delivery is not retried automatically.')
        elif args.action == 'show':
            for row in registry.list_voices(con):
                print(row['name'], '| ID:', row['voice_id'] or 'unknown', '| account:', bool(row['available']),
                      '| verified:', bool(row['verified']), '| score:', row['score'],
                      '| approved:', bool(row['approved']), '| enabled:', bool(row['enabled']))
        elif args.action == 'review-export':
            backup = review.export_sheet(con, state / 'review.json')
            if backup:
                print('Previous review sheet backup:', backup)
            print('Editable review sheet:', state / 'review.json')
        elif args.action == 'review-apply':
            print('Applied reviews:', review.apply_sheet(con, state / 'review.json'))
        elif args.action == 'review':
            rows = {row['name'].casefold(): row for row in registry.list_voices(con)}
            for name in args.names:
                row = rows.get(name.casefold())
                if not row or not row['available'] or not row['verified'] or not row['sample_path']:
                    print(name + ': unavailable, unverified or no comparison sample; kept inactive.')
                    continue
                print('\n' + row['name'] + ' | ' + registry.MODEL + ' | 1.5x')
                print('Comparison audio:', row['sample_path'])
                values = {}
                for criterion in registry.CRITERIA:
                    while True:
                        raw = input(criterion + ' score (0-10): ').strip()
                        try:
                            number = float(raw)
                            import math
                            if not math.isfinite(number) or not 0 <= number <= 10:
                                raise ValueError()
                            values[criterion] = number
                            break
                        except ValueError:
                            print('Enter a number between 0 and 10.')
                serious = input('Any serious Persian pronunciation error? [yes/no]: ').strip().lower()
                if serious not in ('yes', 'no'):
                    raise registry.RegistryError('An explicit yes/no pronunciation decision is required.')
                notes = input('Pronunciation/review notes (Enter to leave empty): ').strip()
                total = registry.score(values)
                print('Weighted score:', total, '/100')
                approve = False
                if total >= 80 and serious == 'no':
                    approve = input('Approve AND enable this voice for production? [yes/no]: ').strip().lower() == 'yes'
                registry.review(con, row['name'], values, notes, serious_error=serious == 'yes',
                                approved=approve, enabled=approve)
                print(row['name'] + ': ' + ('approved and enabled' if approve else 'test only; inactive'))
            print('Human voice reviews saved. Instagram publishing settings were not changed.')
        elif args.action == 'confirm':
            registry.confirm_voice_id(con, args.name, args.voice_id)
            print('Voice ID confirmed; production approval is still required.')
        elif args.action == 'add':
            registry.register(con, args.name, args.voice_id)
            print('Candidate added inactive.')
        elif args.action == 'remove':
            registry.remove(con, args.name)
            print('Candidate removed; historical selections are preserved.')
    finally:
        con.close()


if __name__ == '__main__':
    try:
        main()
    except (registry.RegistryError, discovery.DiscoveryError, telegram.TelegramError, credentials.CredentialError) as exc:
        print('Voice utility stopped:', str(exc), file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, getpass.GetPassWarning) as exc:
        print('Voice utility stopped:', type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
