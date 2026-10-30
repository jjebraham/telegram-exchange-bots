#!/usr/bin/env python3
"""Validate stock photos, distinct licensed soundtracks and a private render."""
from pathlib import Path
import argparse
import sys
import tempfile

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    runtime=parser.parse_args().runtime.resolve()
    sys.path[:0]=[str(runtime),str(runtime/'selector_trial_runtime')]
    import instagram_trial_reels as reel
    import instagram_trial_music as music
    import instagram_reel_stock as stock
    story={'title_original':'Bitcoin crypto security update',
           'title_fa':'نمونه خبر بازار رمزارز',
           'summary_fa':'این ویدئو یک پیش‌نمایش خصوصی برای بررسی تصاویر است. در ادامه خبر با تصاویر متحرک نمایش داده می‌شود.',
           'source_name':'نمونه', 'story_type':'hard_news', 'stock_category':'crypto'}
    with tempfile.TemporaryDirectory(prefix='kiani-motion-preview-') as tmp:
        root=Path(tmp)
        photos=stock.collect(story,root,origin='admin_direct',limit=2)
        print('Distinct stock photos:',len(photos),flush=True)
        if len(photos)<2:
            raise RuntimeError('Two stock photos are needed for this preview.')
        tracks=[]
        for candidate in music.select_order(story)[:10]:
            try:
                target=root/('track-'+str(len(tracks))+'.ogg')
                info=music.retrieve_track(candidate,target)
                tracks.append((info,target))
                if len(tracks)==2: break
            except Exception as exc:
                print('Track not verified:',type(exc).__name__,flush=True)
                if target.is_file() and not target.is_symlink():
                    target.unlink()
        print('Distinct verified music tracks:',len(tracks),flush=True)
        if len(tracks)<2:
            raise RuntimeError('Two distinct licensed tracks are needed to verify rotation.')
        for info,_ in tracks:
            print('Music:',info['name'],'—',info['artist'],flush=True)
        output=root/'preview.mp4'
        duration=reel.render_video(story,'crypto',output,Path.home()/'kiani-instagram-publisher',
                                   media=photos,music_path=tracks[0][1])
        print('Private preview rendered:',round(duration,2),'seconds,',output.stat().st_size,'bytes',flush=True)
    print('Preflight passed. No DeepSeek or Instagram request was made.',flush=True)

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('Reel motion preflight stopped:',type(exc).__name__,str(exc)[:180],file=sys.stderr)
        raise SystemExit(1)
