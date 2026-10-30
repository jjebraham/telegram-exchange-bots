#!/usr/bin/env python3
"""Privately configure Azure Speech and verify an unposted narrated Reel."""
from pathlib import Path
import argparse
import getpass
import os
import re
import sys
import tempfile
import warnings

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    runtime=parser.parse_args().runtime.resolve()
    sys.path[:0]=[str(runtime),str(runtime/'selector_trial_runtime')]
    import instagram_reel_voice as speech
    import instagram_trial_reels as reel
    from PIL import Image
    warnings.simplefilter('error',getpass.GetPassWarning)
    if speech.CONFIG.is_symlink() or not speech.CONFIG.is_dir() or speech.CONFIG.stat().st_uid!=os.getuid() or speech.CONFIG.stat().st_mode & 0o077:
        raise RuntimeError('Private bot configuration needs review.')
    existing=speech.configured()
    if existing:
        key=speech._private(speech.KEY)
        voice=speech._private(speech.VOICE)
        print('Existing private Azure Speech configuration found.',flush=True)
    else:
        if speech.KEY.exists() or speech.VOICE.exists() or speech.KEY.is_symlink() or speech.VOICE.is_symlink():
            raise RuntimeError('A partial Azure configuration needs review.')
        print('Choose voice: 1 = Dilara (female), 2 = Farid (male).',flush=True)
        choice=input('Voice [1]: ').strip() or '1'
        if choice not in {'1','2'}:
            raise RuntimeError('Choose 1 or 2.')
        voice='dilara' if choice=='1' else 'farid'
        key=getpass.getpass('Azure Speech key (hidden): ').strip()
        if not re.fullmatch(r'[A-Za-z0-9]{16,128}',key):
            raise RuntimeError('Azure Speech key format is invalid.')
    story={'title_fa':'نمونه خبر بازار رمزارز',
           'summary_fa':'این ویدئو یک نمونه خصوصی است. خبر با صدای فارسی و تصاویر متحرک نمایش داده می‌شود.',
           'source_name':'پیش‌نمایش', 'story_type':'hard_news'}
    with tempfile.TemporaryDirectory(prefix='kiani-voice-render-',dir=speech.STATE) as tmp:
        root=Path(tmp)
        texts=[story['title_fa']]+reel._chunks(story['summary_fa'])
        segments=speech.synthesize(texts,root,key=key,voice=voice)
        media=[]
        for i,color in enumerate(('#2b4651','#527c83')):
            path=root/('image-'+str(i)+'.jpg')
            Image.new('RGB',(888,500),color).save(path)
            media.append({'path':path,'kind':'illustrative'})
        output=root/'preview.mp4'
        seconds=reel.render_video(story,'crypto',output,Path.home()/'kiani-instagram-publisher',
                                  media=media,narration=segments)
        print('Private narrated Reel rendered:',round(seconds,2),'seconds;',output.stat().st_size,'bytes.',flush=True)
    if not existing:
        created=[]
        try:
            for path,value in ((speech.VOICE,voice),(speech.KEY,key)):
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                created.append(path)
                with os.fdopen(fd,'w',encoding='utf-8') as out: out.write(value+'\n')
        except BaseException:
            for path in created:
                if path.is_file() and not path.is_symlink(): path.unlink()
            raise
        print('Azure key and voice saved privately.',flush=True)
    print('Narration voice:',voice,'| Region: East US.',flush=True)
    print('Preflight passed. No Instagram or DeepSeek request was made.',flush=True)

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Narration setup stopped:',type(exc).__name__,str(exc)[:180],file=sys.stderr)
        raise SystemExit(1)
