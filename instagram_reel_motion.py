"""Render Persian word reveals and locally generated typing sounds without AI calls."""
from pathlib import Path
import math
import random
import struct
import subprocess
import tempfile
import wave
from PIL import Image, ImageDraw, ImageOps

def render(t, title, source, kind, story_type, chunks, destination, asset_root, media, music_path, ffmpeg):
    pages=len(chunks)+2
    words=sum(len(s.split()) for s in chunks)
    extra_count=min(max(len(media)-1,0),len(chunks))
    step=min(.14,(52-4.5-3-1.2*extra_count-2.0*len(chunks))/max(words,1))
    if step<.045: raise t.TrialReelError('Story is too long for a legible animated Reel.')
    with tempfile.TemporaryDirectory(prefix='kiani-motion-',dir=t.STATE) as tmp:
        root=Path(tmp); entries=[]; clicks=[]; elapsed=0.0
        def add(image,seconds,click=False):
            nonlocal elapsed
            p=root/f'f{len(entries):04d}.jpg'
            image.save(p,format='JPEG',quality=90)
            entries.append((p,seconds))
            if click: clicks.append(elapsed)
            elapsed+=seconds

        cover=t._frame(title,source,kind,1,pages,asset_root,story_type)
        if media:
            for index in range(3):
                item=media[index%len(media)]
                with Image.open(item['path']) as pic:
                    pic.verify()
                with Image.open(item['path']) as pic:
                    if pic.width*pic.height>40000000: raise t.TrialReelError('Illustrative image is too large.')
                    enlarged=ImageOps.fit(pic.convert('RGB'),(1110,625),Image.Resampling.LANCZOS)
                    x=round((1110-888)*(.25,.5,.75)[index]); y=(625-500)//2
                    photo=enlarged.crop((x,y,x+888,y+500))
                img=cover.copy(); img.paste(photo,(96,315))
                d=ImageDraw.Draw(img)
                d.rounded_rectangle((96,815,984,1300),radius=38,fill=t.INK)
                font=t._font(asset_root,56,True); rows=t._wrap(d,title,font,740)
                if len(rows)>4: font=t._font(asset_root,48,True); rows=t._wrap(d,title,font,740)
                if len(rows)>5: raise t.TrialReelError('The headline is too long for the Reel cover.')
                for i,row in enumerate(rows): d.text((930,855+i*int(font.size*1.42)),t._rtl(row),font=font,fill='white',anchor='rt')
                d.rounded_rectangle((110,335,340,395),radius=20,fill=t.INK)
                label='تصویر خبر' if item.get('kind')=='publisher' else 'تصویر نمادین'
                d.text((225,365),t._rtl(label),font=t._font(asset_root,23,True),fill='white',anchor='mm')
                add(img,1.5)
        else:
            add(cover,4.5)
        for page,body in enumerate(chunks,2):
            if page-2 < extra_count:
                item=media[page-1]
                with Image.open(item['path']) as photo:
                    if photo.width*photo.height>40000000: raise t.TrialReelError('Illustrative image is too large.')
                    image=ImageOps.fit(photo.convert('RGB'),(888,600),Image.Resampling.LANCZOS)
                interlude=t._frame(title,'',kind,page,pages,asset_root,story_type)
                interlude.paste(image,(96,420))
                d=ImageDraw.Draw(interlude)
                d.rounded_rectangle((110,440,340,500),radius=20,fill=t.INK)
                d.text((225,470),t._rtl('تصویر نمادین'),font=t._font(asset_root,23,True),fill='white',anchor='mm')
                add(interlude,1.2)
            blank=t._frame(title,'',kind,page,pages,asset_root,story_type)
            draw=ImageDraw.Draw(blank); font=t._font(asset_root,56)
            rows=t._wrap(draw,body,font,780)
            if len(rows)>7: font=t._font(asset_root,48); rows=t._wrap(draw,body,font,780)
            if len(rows)>8: raise t.TrialReelError('A story segment does not fit.')
            top=(1920-len(rows)*int(font.size*1.72))//2
            for revealed in range(1,sum(len(row.split()) for row in rows)+1):
                img=blank.copy(); d=ImageDraw.Draw(img); remaining=revealed
                for index,row in enumerate(rows):
                    part=row.split(); count=min(len(part),remaining)
                    if count: d.text((930,top+index*int(font.size*1.72)),t._rtl(' '.join(part[:count])),font=font,fill=t.INK,anchor='rt')
                    remaining-=count
                add(img,step,True)
            add(img,2.0)
        add(t._frame(title,source,kind,pages,pages,asset_root,story_type),3)
        if not 12<=elapsed<=60: raise t.TrialReelError('Animated duration is outside Reel limits.')
        playlist=root/'frames.txt'
        with playlist.open('w',encoding='utf-8') as out:
            for path,seconds in entries:
                out.write("file '"+path.as_posix().replace("'", "'\\''")+"'\n")
                out.write(f'duration {seconds:.5f}\n')
            out.write("file '"+entries[-1][0].as_posix().replace("'", "'\\''")+"'\n")
        rate=48000; rng=random.Random(45); signal=[0.0]*int((elapsed+.1)*rate)
        for start in clicks:
            for n in range(int(.025*rate)):
                index=int(start*rate)+n
                if index<len(signal): signal[index]+=.12*math.exp(-n/(rate*.0055))*(.65*rng.uniform(-1,1)+.35*math.sin(2*math.pi*2200*n/rate))
        sound=root/'keys.wav'
        with wave.open(str(sound),'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
            out.writeframes(b''.join(struct.pack('<h',int(max(-1,min(1,s))*32767)) for s in signal))
        cmd=[ffmpeg,'-y','-hide_banner','-loglevel','error','-threads','2','-f','concat','-safe','0','-i',str(playlist)]
        if music_path:
            if Path(music_path).is_symlink() or not Path(music_path).is_file(): raise t.TrialReelError('Verified music unavailable.')
            cmd+=['-stream_loop','-1','-i',str(music_path)]
        else: cmd+=['-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000']
        cmd+=['-i',str(sound),'-filter_complex',f'[1:a]volume=0.22,afade=t=in:st=0:d=0.8,afade=t=out:st={max(0,elapsed-1):.2f}:d=1[m];[2:a]volume=.7[k];[m][k]amix=inputs=2:duration=first:normalize=0[a]',
              '-map','0:v:0','-map','[a]','-t',f'{elapsed:.3f}','-r','30','-vf','scale=in_range=full:out_range=tv,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','25','-profile:v','high','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-ar','48000','-ac','2','-movflags','+faststart',str(destination)]
        try: subprocess.run(cmd,capture_output=True,timeout=300,check=True)
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired,OSError): raise t.TrialReelError('Animated Reel rendering failed.') from None

