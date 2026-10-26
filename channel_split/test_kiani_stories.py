"""Receipt gating, exact 48-hour expiry and no-duplicate story behavior."""
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image
from telethon.tl import functions, types
from kiani_story_state import SourceReceipt, StoryState, STORY_PERIOD, select_receipt, in_daily_window
from kiani_story_worker import process, preflight, story_canvas, validate_source

NOW = datetime(2026, 10, 27, 9, 11, tzinfo=timezone.utc)  # 12:11 Istanbul
SOURCE = SourceReceipt('2026-10-27', 1234, NOW - timedelta(seconds=50))
CONFIG = {'expected_user_id': 999, 'channel_ids': {'alanchande_com': 111, 'exchangekiani': 222}}


def photo_bytes():
    output = io.BytesIO()
    Image.new('RGB', (600, 680), '#167b52').save(output, 'PNG')
    return output.getvalue()


class FakeClient:
    def __init__(self, *, timeout_once=False, wrong_expiry=False, blocked=None, flood=False, premium=True):
        self.timeout_once, self.wrong_expiry, self.blocked = timeout_once, wrong_expiry, blocked
        self.sent, self.deleted = [], []
        self.active = {111: [], 222: []}
        self.flood, self.premium, self.read_fail = flood, premium, False

    async def is_user_authorized(self):
        return True

    async def get_me(self):
        return NS(id=999, bot=False, premium=self.premium)

    async def get_entity(self, handle):
        key = handle.lstrip('@')
        return NS(id=CONFIG['channel_ids'][key], access_hash=123, broadcast=True, noforwards=False)

    async def get_messages(self, entity, ids):
        return NS(id=ids, date=SOURCE.sent_at, photo=True, noforwards=False)

    async def download_media(self, message, file):
        return photo_bytes()

    async def upload_file(self, path):
        with Image.open(path) as image:
            self.uploaded = image.size
        return types.InputFile(55, 1, 'story.jpg', '0' * 32)

    async def __call__(self, request):
        target = request.peer.channel_id
        if isinstance(request, functions.stories.GetPeerStoriesRequest):
            if self.read_fail:
                raise ConnectionError('simulated read outage')
            return NS(stories=NS(stories=self.active[target]))
        if isinstance(request, functions.stories.CanSendStoryRequest):
            if target == self.blocked:
                raise type('BoostsRequiredError', (Exception,), {})()
            return NS(count_remains=10)
        if isinstance(request, functions.stories.DeleteStoriesRequest):
            self.deleted.append((target, request.id))
            self.active[target] = [story for story in self.active[target] if story.id not in request.id]
            return request.id
        if isinstance(request, functions.stories.SendStoryRequest):
            if self.flood:
                self.flood = False
                raise type('FloodWaitError', (Exception,), {'seconds': 300})()
            self.sent.append(request)
            period = 86400 if self.wrong_expiry else request.period
            stamp = NOW
            area = request.media_areas[0]
            story = types.StoryItem(50 + len(self.sent), stamp, stamp + timedelta(seconds=period),
                                    types.MessageMediaEmpty(),
                                    media_areas=[types.MediaAreaChannelPost(area.coordinates, area.channel.channel_id, area.msg_id)])
            self.active[target].append(story)
            if self.timeout_once:
                self.timeout_once = False
                raise TimeoutError('simulated lost response')
            return NS(updates=[types.UpdateStory(types.PeerChannel(target), story)])
        raise AssertionError('Unexpected API request type')


class StoryReceiptTests(unittest.TestCase):
    def test_only_confirmed_same_day_1210_source_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipts.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE kiani_forward_source_messages(source_key,local_date,sent_at,message_id,source_chat_id)')
                db.executemany('INSERT INTO kiani_forward_source_messages VALUES(?,?,?,?,?)', [
                    ('kiani-rates', SOURCE.local_date, (SOURCE.sent_at - timedelta(hours=1)).isoformat(), 1000, '@ExchangeKiani'),
                    ('kiani-try', SOURCE.local_date, SOURCE.sent_at.isoformat(), 1100, '@ExchangeKiani'),
                    ('kiani-rates', SOURCE.local_date, SOURCE.sent_at.isoformat(), SOURCE.message_id, '@ExchangeKiani')])
            db.close()
            self.assertEqual(select_receipt(path, NOW).message_id, SOURCE.message_id)
            self.assertIsNone(select_receipt(path, NOW.replace(hour=8)))
            self.assertIsNone(select_receipt(path, NOW.replace(minute=31)))
            self.assertIsNone(select_receipt(path, NOW + timedelta(days=1)))
            self.assertFalse(in_daily_window(NOW.replace(hour=10)))

    def test_missing_receipt_does_not_create_a_database_or_reuse_yesterday(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'absent.sqlite3'
            self.assertIsNone(select_receipt(path, NOW))
            self.assertFalse(path.exists())

    def test_stable_random_ids_and_first_source_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StoryState(Path(directory) / 'state.sqlite3')
            state.ensure(SOURCE)
            first = state.jobs(SOURCE.local_date)
            state.ensure(SOURCE)
            self.assertEqual(first, state.jobs(SOURCE.local_date))
            self.assertEqual(len({row['random_id'] for row in first}), 2)
            with self.assertRaises(ValueError):
                state.ensure(SourceReceipt(SOURCE.local_date, 9999, SOURCE.sent_at))

    def test_canvas_keeps_whole_photo_and_uses_vertical_story_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'story.jpg'
            area = story_canvas(photo_bytes(), output)
            with Image.open(output) as image:
                self.assertEqual(image.size, (1080, 1920))
                self.assertLess(max(abs(a - b) for a, b in zip(image.getpixel((540, 960)), (22, 123, 82))), 4)
            self.assertAlmostEqual(area['w'] / area['h'], (600 / 1080) / (680 / 1920), places=2)
            self.assertEqual(area['rotation'], 0)

    def test_wrong_source_time_or_protected_photo_is_rejected(self):
        message = NS(id=SOURCE.message_id, date=SOURCE.sent_at - timedelta(hours=1), photo=True, noforwards=False)
        with self.assertRaises(ValueError):
            validate_source(message, NS(noforwards=False), SOURCE)
        message.date, message.noforwards = SOURCE.sent_at, True
        with self.assertRaises(ValueError):
            validate_source(message, NS(noforwards=False), SOURCE)


class StoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_rejects_nonpremium_for_requested_48_hour_period(self):
        report = await preflight(FakeClient(premium=False), CONFIG)
        self.assertTrue(all(not row['ready'] for row in report.values()))

    async def test_server_flood_wait_is_observed_across_both_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StoryState(Path(directory) / 'state.sqlite3')
            client = FakeClient(flood=True)
            await process(client, CONFIG, SOURCE, state, now=NOW)
            self.assertEqual(len(client.sent), 0)
            await process(client, CONFIG, SOURCE, state, now=NOW + timedelta(seconds=299))
            self.assertEqual(len(client.sent), 0)
            result = await process(client, CONFIG, SOURCE, state, now=NOW + timedelta(seconds=301))
            self.assertEqual(set(result.values()), {'sent'})
            self.assertEqual(len(client.sent), 2)

    async def test_failed_reconciliation_never_turns_uncertain_send_into_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StoryState(Path(directory) / 'state.sqlite3')
            client = FakeClient(timeout_once=True)
            await process(client, CONFIG, SOURCE, state)
            client.read_fail = True
            await process(client, CONFIG, SOURCE, state)
            self.assertEqual(state.jobs(SOURCE.local_date)[0]['status'], 'uncertain')
            self.assertEqual(len(client.sent), 2)

    async def test_both_channels_get_exact_48_hours_and_duplicate_run_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StoryState(Path(directory) / 'state.sqlite3')
            client = FakeClient()
            report = await process(client, CONFIG, SOURCE, state)
            self.assertEqual(set(report.values()), {'sent'})
            self.assertEqual({request.peer.channel_id for request in client.sent}, {111, 222})
            for request in client.sent:
                self.assertEqual(request.period, STORY_PERIOD)
                self.assertFalse(request.pinned)
                self.assertEqual(request.media_areas[0].msg_id, SOURCE.message_id)
                self.assertEqual(request.media_areas[0].channel.channel_id, 222)
                self.assertEqual(len(request.entities), 3)
            self.assertEqual(client.uploaded, (1080, 1920))
            await process(client, CONFIG, SOURCE, state)
            self.assertEqual(len(client.sent), 2)

    async def test_lost_send_response_is_reconciled_without_resending(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StoryState(Path(directory) / 'state.sqlite3')
            client = FakeClient(timeout_once=True)
            first = await process(client, CONFIG, SOURCE, state)
            self.assertIn('uncertain', first.values())
            second = await process(client, CONFIG, SOURCE, state)
            self.assertEqual(set(second.values()), {'sent'})
            self.assertEqual(len(client.sent), 2)

    async def test_unsupported_48_hour_expiry_never_falls_back_to_24_hours(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StoryState(Path(directory) / 'state.sqlite3')
            client = FakeClient(wrong_expiry=True)
            result = await process(client, CONFIG, SOURCE, state)
            self.assertEqual(set(result.values()), {'blocked'})
            self.assertTrue(all(request.period == 172800 for request in client.sent))
            self.assertEqual(len(client.deleted), 2)
            self.assertTrue(all(not stories for stories in client.active.values()))

    async def test_one_channel_boost_failure_does_not_duplicate_the_other(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StoryState(Path(directory) / 'state.sqlite3')
            client = FakeClient(blocked=111)
            result = await process(client, CONFIG, SOURCE, state)
            self.assertEqual(result, {'alanchande_com': 'blocked', 'exchangekiani': 'sent'})
            self.assertEqual(len(client.sent), 1)
            await process(client, CONFIG, SOURCE, state)
            self.assertEqual(len(client.sent), 1)


if __name__ == '__main__':
    unittest.main()
