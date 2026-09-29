from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'channel_split'))
from hawala_x_snapshot import CODES, write_snapshot
from prepare_hawala_x_bridge import transform
from x_channel_daily import collect
from x_channel_formats import render

SOURCE = (ROOT/'tests/fixtures/hawala_slot_source.txt').read_text(encoding='utf-8')


class HawalaBridgeTests(unittest.TestCase):
    def module(self, path, dry=False, success=True):
        # Run the actual uploaded scheduler, with only IO and time substituted.
        now = datetime(2026, 9, 25, 19, 45, tzinfo=timezone(timedelta(hours=3, minutes=30)))
        module = {'datetime':SimpleNamespace(now=lambda tz:now), 'TEHRAN':now.tzinfo,
                  'timedelta':timedelta, 'WORK_START_HOUR':9,'WORK_END_HOUR':22,
                  'POST_MINUTE':45,'GRACE_MINUTES':2, 'DRY_RUN':dry,
                  'slot_was_posted':Mock(return_value=False),
                  'mark_slot_posted':Mock(return_value=True), 'fire_alert':Mock(),
                  'logger':Mock(), 'post_message':Mock(return_value=success),
                  'build_hawala_message':Mock(side_effect=lambda rates:dict(rates))}
        import os
        module['os'] = os
        rates = {code:200000 for code in CODES}
        module['calculate_hawala_rates'] = Mock(return_value=rates)
        exec(compile(transform(SOURCE), '<inspected-hawala-slot>', 'exec'), module)
        return module, rates, now

    def test_live_pricing_result_exported_exactly_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'snapshot.json'
            module, rates, now = self.module(path)
            # Emulate runtime's late-bound calculate wrapper: different live
            # values are returned, and the hook must use that exact returned map.
            dynamic_rates = dict(rates, TRY=4710, USD=229700)
            module['calculate_hawala_rates'] = Mock(return_value=dynamic_rates)
            with patch.dict('os.environ', {'X_HAWALA_SNAPSHOT':str(path)}):
                module['process_current_slot']()
            data = json.loads(path.read_text())
            self.assertEqual(data['rates'], dynamic_rates)
            self.assertEqual(module['post_message'].call_args.args[0], dynamic_rates)
            self.assertEqual(datetime.fromisoformat(data['generated_at']), now)
            module['mark_slot_posted'].assert_called_once()

    def test_no_snapshot_for_dry_run_failed_send_missing_rates_or_posted_slot(self):
        for case in ('dry','failed','missing','posted','disabled'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'snapshot.json'
                module, _, _ = self.module(path, dry=case=='dry', success=case!='failed')
                if case=='missing': module['calculate_hawala_rates'].return_value=None
                if case=='posted': module['slot_was_posted'].return_value=True
                with patch.dict('os.environ', {'X_HAWALA_SNAPSHOT':'' if case=='disabled' else str(path)}):
                    module['process_current_slot']()
                self.assertFalse(path.exists())

    def test_export_failure_does_not_undo_successful_telegram_slot(self):
        module, _, _ = self.module('unused')
        with patch.dict('os.environ', {'X_HAWALA_SNAPSHOT':'unused'}), \
             patch('hawala_x_snapshot.write_snapshot', side_effect=OSError('disk full')):
            module['process_current_slot']()
        module['post_message'].assert_called_once()
        module['mark_slot_posted'].assert_called_once()
        module['logger'].exception.assert_called_once()

    def test_patch_preserves_other_code_and_refuses_unknown_scheduler(self):
        prefix = '# unrelated production customization\n'
        suffix = '\ndef other_function():\n    return 42\n'
        result=transform(prefix+SOURCE+suffix)
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        with self.assertRaises(ValueError): transform(SOURCE.replace('rates = calculate_hawala_rates()', 'rates = another_calculation()'))
        with self.assertRaises(ValueError): transform(result)

    def test_atomic_validation_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'snapshot.json'
            rates={code:200000 for code in CODES}
            now=datetime.now(timezone.utc)
            write_snapshot(rates,now,path)
            original=path.read_bytes()
            for bad in (0,-1,Decimal('NaN'),Decimal('0.5')):
                with self.assertRaises(ValueError): write_snapshot(dict(rates,TRY=bad),now,path)
                self.assertEqual(path.read_bytes(),original)
            with patch('hawala_x_snapshot.os.replace',side_effect=OSError('full')):
                with self.assertRaises(OSError): write_snapshot(rates,now,path)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(list(Path(tmp).glob('.hawala-x-*')),[])

    def test_fresh_snapshot_reaches_compact_x_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'snapshot.json'
            write_snapshot({code:200000 for code in CODES},datetime.now(timezone.utc),path)
            text=render('kiani-hawala',collect('kiani-hawala',str(path)))
            self.assertIn('TRY 200,000',text)
            self.assertTrue(text.endswith('حواله روی خط واتسپ'))
            self.assertNotIn('https://',text)


if __name__ == '__main__':
    unittest.main()
