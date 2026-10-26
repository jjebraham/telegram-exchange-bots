"""Daily channel-story API worker; never publishes without the 12:10 receipt."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from kiani_story_state import ISTANBUL, SOURCE, TARGETS, STORY_PERIOD, SourceReceipt, StoryState, select_receipt

CONFIG = Path.home() / '.config/kiani-stories/config.json'
CAPTION = '@alanchande_com  📺\n@exchangekiani 💱\n@kianiexchangebot 🤖'
PERMANENT = {'BoostsRequiredError', 'ChatAdminRequiredError', 'PremiumAccountRequiredError',
             'StoryPeriodInvalidError', 'ChannelInvalidError', 'PeerIdInvalidError',
             'MediaTypeInvalidError', 'PhotoInvalidDimensionsError', 'MediaAreasInvalidError'}


def private_file(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Story configuration/session must be a regular file')
    if os.name == 'posix' and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('Story configuration/session must be private to its owner')


def load_config(path: Path, *, require_enabled=True) -> dict:
    private_file(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('version') != 1 or not isinstance(data.get('api_id'), int) or data['api_id'] <= 0
            or not re.fullmatch(r'[0-9a-fA-F]{32}', data.get('api_hash', ''))
            or not isinstance(data.get('expected_user_id'), int) or data['expected_user_id'] <= 0
            or set(data.get('channel_ids', {})) != set(TARGETS)
            or any(not isinstance(value, int) or value <= 0 for value in data['channel_ids'].values())):
        raise ValueError('Incomplete approved story-account configuration')
    for name in ('session_path', 'receipt_db', 'state_db'):
        if not Path(data.get(name, '')).is_absolute():
            raise ValueError('Story paths must be absolute')
    private_file(Path(data['session_path']))
    if require_enabled and data.get('enabled') is not True:
        raise ValueError('Channel-story automation is not enabled')
    return data


def new_client(config):
    from telethon import TelegramClient
    return TelegramClient(config['session_path'], config['api_id'], config['api_hash'],
                          device_model='Kiani channel stories', request_retries=0,
                          connection_retries=1, flood_sleep_threshold=0, receive_updates=False)


async def approved_account(client, config):
    if not await client.is_user_authorized():
        raise ValueError('The approved Telegram administrator login is required')
    account = await client.get_me()
    if account.bot or account.id != config['expected_user_id']:
        raise ValueError('Telegram session does not match the approved administrator')
    return account


async def channel(client, config, handle):
    from telethon.tl import types
    entity = await client.get_entity('@' + handle)
    if entity.id != config['channel_ids'][handle] or not entity.broadcast or not entity.access_hash:
        raise ValueError('The channel does not match its approved pinned identity')
    return entity, types.InputPeerChannel(entity.id, entity.access_hash)


async def preflight(client, config):
    from telethon.tl import functions
    account = await approved_account(client, config)
    report = {}
    for target in TARGETS:
        try:
            _, peer = await channel(client, config, target)
            if not getattr(account, 'premium', False):
                raise ValueError('Premium administrator account required for 48-hour stories')
            capacity = await client(functions.stories.CanSendStoryRequest(peer=peer))
            if getattr(capacity, 'count_remains', 0) < 1:
                raise ValueError('No remaining channel story capacity')
            report[target] = {'ready': True}
        except Exception as error:
            report[target] = {'ready': False, 'reason': str(error) if isinstance(error, ValueError) else type(error).__name__}
    return report


def validate_source(message, entity, source: SourceReceipt):
    if not message or message.id != source.message_id or not message.photo or getattr(message, 'noforwards', False) or getattr(entity, 'noforwards', False):
        raise ValueError('The source must be the unprotected photo in the confirmed channel post')
    if not message.date or message.date.tzinfo is None:
        raise ValueError('The source post has no valid Telegram timestamp')
    posted = message.date.astimezone(ISTANBUL)
    start = datetime.fromisoformat(source.local_date + 'T12:10:00').replace(tzinfo=ISTANBUL)
    if not start <= posted < start + timedelta(minutes=12) or abs((posted - source.sent_at).total_seconds()) > 180:
        raise ValueError('The source photo is not the confirmed same-day 12:10 post')


def story_canvas(raw: bytes, output: Path):
    from PIL import Image, ImageOps
    if not raw or len(raw) > 20_000_000:
        raise ValueError('Unexpected source photo size')
    Image.MAX_IMAGE_PIXELS = 25_000_000
    with Image.open(io.BytesIO(raw)) as picture:
        picture = ImageOps.exif_transpose(picture).convert('RGB')
        picture.thumbnail((1000, 1540), Image.Resampling.LANCZOS)
        if min(picture.size) < 100:
            raise ValueError('Source photo is too small for the story')
        width, height = picture.size
        x, y = (1080 - width) // 2, (1920 - height) // 2
        canvas = Image.new('RGB', (1080, 1920), '#edf3ef')
        canvas.paste(picture, (x, y))
        canvas.save(output, format='JPEG', quality=95, subsampling=0, optimize=True)
    return {'x': (x + width / 2) / 1080 * 100, 'y': (y + height / 2) / 1920 * 100,
            'w': width / 1080 * 100, 'h': height / 1920 * 100, 'rotation': 0.0}


def is_source_story(story, source_id: int, source_channel_id: int) -> bool:
    return any(getattr(area, 'channel_id', None) == source_channel_id and getattr(area, 'msg_id', None) == source_id
               for area in (getattr(story, 'media_areas', None) or []))


def correct_expiry(story) -> bool:
    return bool(getattr(story, 'date', None) and getattr(story, 'expire_date', None)
                and (story.expire_date - story.date).total_seconds() == STORY_PERIOD)


async def existing_story(client, peer, source, source_channel_id):
    from telethon.tl import functions
    response = await client(functions.stories.GetPeerStoriesRequest(peer=peer))
    stories = getattr(getattr(response, 'stories', None), 'stories', [])
    matches = [story for story in stories if is_source_story(story, source.message_id, source_channel_id)]
    if len(matches) > 1:
        raise ValueError('Multiple existing stories reference the same daily source')
    return matches[0] if matches else None


def mention_entities():
    from telethon.tl import types
    return [types.MessageEntityMention(len(CAPTION[:match.start()].encode('utf-16-le')) // 2, len(match.group()))
            for match in re.finditer(r'@[A-Za-z0-9_]+', CAPTION)]


def flood_delay(error):
    name = type(error).__name__
    if name in {'FloodWaitError', 'StorySendFloodWeeklyError', 'StorySendFloodMonthlyError'}:
        return max(1, int(getattr(error, 'seconds', 3600)))
    return None


async def process(client, config, source: SourceReceipt, state: StoryState, *, now=None):
    from telethon.tl import functions, types
    state.ensure(source)
    jobs = state.jobs(source.local_date)
    if all(job['status'] in {'sent', 'blocked'} for job in jobs):
        return {job['target']: job['status'] for job in jobs}
    if state.cooling_down(now or datetime.now(timezone.utc)):
        return {job['target']: job['status'] for job in jobs}
    await approved_account(client, config)
    source_entity, _ = await channel(client, config, SOURCE)
    message = await client.get_messages(source_entity, ids=source.message_id)
    validate_source(message, source_entity, source)
    report = {}
    with tempfile.TemporaryDirectory(prefix='kiani-story-') as directory:
        photo = Path(directory) / 'story.jpg'
        raw = await client.download_media(message, file=bytes)
        coordinates = story_canvas(raw, photo)
        for job in jobs:
            target = job['target']
            if job['status'] in {'sent', 'blocked'}:
                report[target] = job['status']
                continue
            try:
                _, peer = await channel(client, config, target)
                prior = await existing_story(client, peer, source, source_entity.id)
                if prior:
                    status = 'sent' if correct_expiry(prior) else 'blocked'
                    state.mark(source.local_date, target, status, story_id=prior.id,
                               reason='' if status == 'sent' else 'Existing story does not have 48-hour expiry')
                    report[target] = status
                    continue
                if job['status'] in {'attempting', 'uncertain'}:
                    state.mark(source.local_date, target, 'uncertain', reason='Previous send unconfirmed; no automatic resend')
                    report[target] = 'uncertain'
                    continue
                capacity = await client(functions.stories.CanSendStoryRequest(peer=peer))
                if getattr(capacity, 'count_remains', 0) < 1:
                    state.mark(source.local_date, target, 'blocked', reason='No remaining channel story capacity')
                    report[target] = 'blocked'
                    continue
                uploaded = await client.upload_file(str(photo))
            except Exception as error:
                name = type(error).__name__
                status = 'blocked' if name in PERMANENT else ('uncertain' if job['status'] in {'attempting', 'uncertain'} else 'retry')
                state.mark(source.local_date, target, status, reason=name)
                report[target] = status
                if flood_delay(error):
                    state.defer(flood_delay(error), now or datetime.now(timezone.utc))
                    return {row['target']: row['status'] for row in state.jobs(source.local_date)}
                continue
            request = functions.stories.SendStoryRequest(
                peer=peer, media=types.InputMediaUploadedPhoto(file=uploaded),
                privacy_rules=[types.InputPrivacyValueAllowAll()], random_id=job['random_id'],
                period=STORY_PERIOD, pinned=False, caption=CAPTION, entities=mention_entities(),
                media_areas=[types.InputMediaAreaChannelPost(
                    coordinates=types.MediaAreaCoordinates(**coordinates),
                    channel=types.InputChannel(source_entity.id, source_entity.access_hash), msg_id=source.message_id)])
            state.mark(source.local_date, target, 'attempting')
            try:
                result = await client(request)
            except Exception as error:
                name = type(error).__name__
                delay = flood_delay(error)
                status = 'blocked' if name in PERMANENT else ('retry' if delay else 'uncertain')
                state.mark(source.local_date, target, status, reason=name)
                report[target] = status
                if delay:
                    state.defer(delay, now or datetime.now(timezone.utc))
                    return {row['target']: row['status'] for row in state.jobs(source.local_date)}
                continue
            try:
                strong = [item.story for item in getattr(result, 'updates', [])
                          if isinstance(item, types.UpdateStory) and getattr(item.peer, 'channel_id', None) == peer.channel_id]
                created = strong[0] if len(strong) == 1 and is_source_story(strong[0], source.message_id, source_entity.id) else None
                story = strong[0] if len(strong) == 1 else await existing_story(client, peer, source, source_entity.id)
                if story and not is_source_story(story, source.message_id, source_entity.id):
                    story = await existing_story(client, peer, source, source_entity.id)
                if not story:
                    raise ValueError('Telegram did not confirm the created story')
                if not correct_expiry(story):
                    # Delete only a story unambiguously returned by this request.
                    if story is created:
                        await client(functions.stories.DeleteStoriesRequest(peer=peer, id=[story.id]))
                    state.mark(source.local_date, target, 'blocked', story_id=story.id,
                               reason='Telegram did not return the requested 48-hour expiry')
                    report[target] = 'blocked'
                    continue
                state.mark(source.local_date, target, 'sent', story_id=story.id)
                report[target] = 'sent'
            except Exception as error:
                state.mark(source.local_date, target, 'uncertain', reason=type(error).__name__)
                report[target] = 'uncertain'
    return report


async def main_async(args):
    config = load_config(args.config, require_enabled=args.action != 'preflight')
    if args.action == 'run':
        source = select_receipt(Path(config['receipt_db']), datetime.now(timezone.utc))
        if source is None:
            print('SKIP: no confirmed same-day 12:10 Kiani photo receipt in the daily window')
            return 0
        state = StoryState(Path(config['state_db']))
        state.ensure(source)
        jobs = state.jobs(source.local_date)
        if all(job['status'] in {'sent', 'blocked'} for job in jobs) or state.cooling_down(datetime.now(timezone.utc)):
            print(json.dumps({job['target']: job['status'] for job in jobs}))
            return 0
    client = new_client(config)
    try:
        await client.connect()
        if args.action == 'preflight':
            report = await preflight(client, config)
        else:
            report = await process(client, config, source, state)
        print(json.dumps(report, indent=2))
        if args.action == 'preflight':
            return 0 if all(row['ready'] for row in report.values()) else 1
        return 0 if all(status == 'sent' for status in report.values()) else 1
    except Exception as error:
        delay = flood_delay(error)
        if args.action == 'run' and delay:
            state.defer(delay, datetime.now(timezone.utc))
            print('STORY WORKER WAIT:', type(error).__name__, delay)
            return 1
        raise
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['preflight', 'run'])
    parser.add_argument('--config', type=Path, default=CONFIG)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'run':
        import fcntl
        directory = Path.home() / '.local/state/kiani-stories'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (directory / 'worker.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('SKIP: story worker already active')
                return 0
            return asyncio.run(main_async(args))
    return asyncio.run(main_async(args))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # API/session secrets must not appear in service logs or chat output.
        print('STORY WORKER STOPPED:', type(error).__name__, file=__import__('sys').stderr)
        raise SystemExit(1) from None
