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
import reel_voice_registry as registry
import reel_voice_review as review
import reel_voice_samples as samples
import reel_voice_telegram as telegram


def secret(name, prompt):
    value = os.environ.get(name, '').strip()
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
    sub.add_parser('samples', help='Generate available voices; ElevenLabs charges may apply.')
    sub.add_parser('compare', help='Check private channel, generate samples and send them.')
    sub.add_parser('send', help='Send prepared samples to the specified private channel.')
    sub.add_parser('show', help='List voice availability and review status.')
    sub.add_parser('review-export', help='Write editable review.json.')
    sub.add_parser('review-apply', help='Apply explicit human decisions from review.json.')
    confirm = sub.add_parser('confirm', help='Confirm an available account voice ID.')
    confirm.add_argument('name')
    confirm.add_argument('voice_id')
    add = sub.add_parser('add', help='Add a test-only candidate.')
    add.add_argument('name')
    add.add_argument('--voice-id')
    remove = sub.add_parser('remove', help='Remove a candidate; selection history remains.')
    remove.add_argument('name')
    args = parser.parse_args()
    if args.action == 'discover':
        key = secret('ELEVENLABS_API_KEY', 'ElevenLabs API key (hidden): ')
        print_discovery(discovery.inspect(key))
        print('Read-only lookup complete. Name matches require human confirmation.')
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
    except (registry.RegistryError, discovery.DiscoveryError, telegram.TelegramError) as exc:
        print('Voice utility stopped:', str(exc), file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, getpass.GetPassWarning) as exc:
        print('Voice utility stopped:', type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)

