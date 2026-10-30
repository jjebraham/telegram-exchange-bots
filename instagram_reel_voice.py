"""Private Azure Persian narration, bounded to the account's free tier."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from xml.sax.saxutils import escape
import wave

CONFIG=Path.home()/'.config/kiani-instagram-manual-news'
STATE=Path.home()/'.local/state/kiani-instagram-trial-reels'
KEY=CONFIG/'azure-speech-key'
VOICE=CONFIG/'azure-speech-voice'
URL='https://eastus.tts.speech.microsoft.com/cognitiveservices/v1'
VOICES={'dilara':'fa-IR-DilaraNeural','farid':'fa-IR-FaridNeural'}
MONTHLY_BUDGET=400_000
MAX_TEXT=1200
MAX_AUDIO=4_000_000

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def _private(path):
    st=path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode & 0o077:
        raise ValueError('Unsafe private narration config')
    return path.read_text(encoding='utf-8').strip()

def configured():
    if not KEY.exists():
        return False
    key=_private(KEY)
    voice=_private(VOICE)
    if not re.fullmatch(r'[A-Za-z0-9]{16,128}',key) or voice not in VOICES:
        raise ValueError('Invalid private narration configuration')
    return True

def _reserve(chars,state=STATE):
    path=Path(state)/'azure-voice-usage.sqlite3'
    if Path(state).is_symlink() or path.is_symlink():
        raise ValueError('Unsafe narration usage state')
    with closing(sqlite3.connect(path,timeout=15)) as con:
        os.chmod(path,0o600)
        con.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, month TEXT NOT NULL, chars INTEGER NOT NULL, created REAL NOT NULL)')
        month=datetime.now(timezone.utc).strftime('%Y-%m')
        con.execute('BEGIN IMMEDIATE')
        total=con.execute('SELECT COALESCE(SUM(chars),0) FROM usage WHERE month=?',(month,)).fetchone()[0]
        if total+chars>MONTHLY_BUDGET:
            raise ValueError('Local monthly narration allowance reached')
        con.execute('INSERT INTO usage(month,chars,created) VALUES(?,?,?)',(month,chars,time.time()))
        con.commit()

def _ssml(text,voice):
    return ("<speak version='1.0' xml:lang='fa-IR'><voice name='"+voice+
            "'><prosody rate='+10%'>"+escape(text)+"</prosody></voice></speak>")

def synthesize(texts, directory, *, key=None, voice=None, state=STATE):
    if not texts or len(texts)>9 or any(not isinstance(t,str) or not t.strip() for t in texts):
        raise ValueError('Invalid narration segments')
    if sum(len(t) for t in texts)>MAX_TEXT:
        raise ValueError('Story is too long for narrated Reel')
    key = key if key is not None else _private(KEY)
    voice = voice if voice is not None else _private(VOICE)
    if voice not in VOICES or not re.fullmatch(r'[A-Za-z0-9]{16,128}',key):
        raise ValueError('Invalid narration credentials')
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Unsafe narration directory')
    result=[]
    for index,text in enumerate(texts):
        ssml=_ssml(text,VOICES[voice])
        _reserve(len(ssml),state)
        req=Request(URL,data=ssml.encode('utf-8'),method='POST',headers={
            'Ocp-Apim-Subscription-Key':key,'Content-Type':'application/ssml+xml',
            'X-Microsoft-OutputFormat':'riff-24khz-16bit-mono-pcm',
            'User-Agent':'KianiExchangeReelNarration/1.0'})
        try:
            with build_opener(NoRedirect()).open(req,timeout=25) as response:
                raw=response.read(MAX_AUDIO+1)
        except HTTPError as exc:
            raise RuntimeError('Azure Speech HTTP '+str(exc.code)) from None
        except Exception:
            raise RuntimeError('Azure narration request failed') from None
        if not 44<len(raw)<=MAX_AUDIO:
            raise ValueError('Invalid narration audio size')
        with wave.open(BytesIO(raw),'rb') as wav:
            if wav.getframerate()!=24000 or wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getcomptype()!='NONE':
                raise ValueError('Unexpected narration audio format')
            duration=wav.getnframes()/wav.getframerate()
            if not 0.2<=duration<=45:
                raise ValueError('Unexpected narration segment duration')
        path=directory/('voice-'+str(index)+'.wav')
        with path.open('xb') as output: output.write(raw)
        path.chmod(0o600)
        result.append({'path':path,'duration':duration})
    print('Narration synthesized:',len(texts),'segments;',sum(len(t) for t in texts),'text characters.',flush=True)
    return result
