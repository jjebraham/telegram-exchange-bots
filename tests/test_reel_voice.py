import io
import sqlite3
import sys
import tempfile
import types
import unittest
import wave
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import instagram_reel_voice as voice

def wav_bytes(seconds=.5):
    buf=io.BytesIO()
    with wave.open(buf,'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b'\x01\x01'*int(24000*seconds))
    return buf.getvalue()

class Response:
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self,n): return wav_bytes()

class VoiceChecks(unittest.TestCase):
    def test_segments_are_validated_and_accounted_without_key_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            opener=types.SimpleNamespace(open=lambda request,timeout:Response())
            with patch.object(voice,'build_opener',return_value=opener):
                result=voice.synthesize(['عنوان آزمایشی','متن آزمایشی'],root,
                                        key='Abcdef1234567890',voice='dilara',state=root)
            self.assertEqual(len(result),2)
            self.assertEqual(result[0]['duration'],.5)
            with closing(sqlite3.connect(root/'azure-voice-usage.sqlite3')) as con:
                rows=con.execute('SELECT chars FROM usage').fetchall()
            self.assertEqual(len(rows),2)
            self.assertNotIn(b'Abcdef1234567890',(root/'azure-voice-usage.sqlite3').read_bytes())
    def test_limits_fail_before_calling_azure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(voice,'build_opener') as opener:
            with self.assertRaises(ValueError):
                voice.synthesize(['x'*(voice.MAX_TEXT+1)],Path(tmp),
                                 key='Abcdef1234567890',voice='dilara',state=Path(tmp))
            opener.assert_not_called()
    def test_monthly_budget_blocks_extra_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            voice._reserve(voice.MONTHLY_BUDGET,root)
            with self.assertRaises(ValueError): voice._reserve(1,root)

if __name__=='__main__': unittest.main()
