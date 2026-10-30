#!/usr/bin/env python3
"""Render an existing failed story with private synthetic timing; no API calls."""
import argparse
import sqlite3
import sys
import tempfile
import wave
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    runtime=parser.parse_args().runtime.resolve()
    sys.path[:0]=[str(runtime),str(runtime/'selector_trial_runtime')]
    import instagram_trial_reels as reel
    from PIL import Image
    db=Path.home()/'.local/state/kiani-instagram-trial-reels/trial_reels.sqlite3'
    with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as con:
        con.row_factory=sqlite3.Row
        row=con.execute("""SELECT title_fa, summary_fa FROM trial_reels
            WHERE status='failed' AND (source_url LIKE '%mexc-pulls-out-of-four-countries%'
                 OR source_url LIKE '%binance-hackers-raced-to-move-billions%')
            ORDER BY created_at DESC LIMIT 1""").fetchone()
    if not row:
        raise RuntimeError('A previously failed example could not be found.')
    story={'title_fa':row['title_fa'],'summary_fa':row['summary_fa'],
           'source_name':'پیش‌نمایش خصوصی','story_type':'hard_news'}
    chunks=reel._chunks(story['summary_fa'])
    if not 1<=len(chunks)<=8:
        raise RuntimeError('The saved story does not fit the existing text-card limit.')
    print('Testing previously failed story:',len(chunks),'text cards; synthetic audio; no model calls.',flush=True)
    with tempfile.TemporaryDirectory(prefix='kiani-long-reel-',dir=reel.STATE) as tmp:
        root=Path(tmp); narration=[]
        for i in range(len(chunks)+1):
            seconds=4.0 if i==0 else 72.0/len(chunks)
            path=root/('voice-'+str(i)+'.wav')
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes(b'\x00\x00'*round(24000*seconds))
            narration.append({'path':path,'duration':seconds})
        media=[]
        for i,color in enumerate(('#2b4651','#527c83')):
            path=root/('image-'+str(i)+'.jpg')
            Image.new('RGB',(888,500),color).save(path)
            media.append({'path':path,'kind':'illustrative'})
        output=root/'long-preview.mp4'
        duration=reel.render_video(story,'crypto',output,Path.home()/'kiani-instagram-publisher',
                                   media=media,narration=narration)
        if not 60<duration<=reel.MAX_REEL_SECONDS:
            raise RuntimeError('The preview did not verify a Reel longer than one minute.')
        print('Private long narrated Reel verified:',round(duration,2),'seconds;',output.stat().st_size,'bytes.',flush=True)
    print('Preflight passed. No Azure, DeepSeek, or Instagram request was made.',flush=True)

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Long Reel preflight stopped:',type(exc).__name__,str(exc)[:180],file=sys.stderr)
        raise SystemExit(1)
