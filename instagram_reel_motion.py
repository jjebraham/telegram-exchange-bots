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
    step=min(.14,(52-4.6-3-2.0*len(chunks))/max(words,1))
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
        title_words = title.split()
        hook_frames = 60
        hook_seconds = 4.0
        previous_revealed = 0

        if media:
            opening = []
            for item in media[:2]:
                with Image.open(item['path']) as check:
                    check.verify()
                with Image.open(item['path']) as image:
                    if image.width * image.height > 40_000_000:
                        raise t.TrialReelError('Article image is too large.')
                    original = image.convert('RGB')
                    original.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                    opening.append((item, original))
            if opening:
                item, original = opening[0]
                if original.width * original.height > 40_000_000:
                    raise t.TrialReelError('Article image is too large.')
                original = original.convert('RGB')
                title_font = t._font(asset_root, 56, True)
                title_rows = t._wrap(ImageDraw.Draw(cover), title, title_font, 740)
                if len(title_rows) > 4:
                    title_font = t._font(asset_root, 48, True)
                    title_rows = t._wrap(ImageDraw.Draw(cover), title, title_font, 740)
                if len(title_rows) > 5:
                    raise t.TrialReelError('The headline is too long for the Reel cover.')

                for index in range(hook_frames):
                    phase = index / max(hook_frames - 1, 1)
                    photo_index = 1 if len(opening) > 1 and index >= 24 else 0
                    item, original = opening[photo_index]
                    photo_phase = ((index - 24) / max(hook_frames - 25, 1)
                                   if photo_index else index / (23 if len(opening) > 1 else hook_frames - 1))
                    aspect = original.width / original.height
                    if aspect < 1.25 or aspect > 2.4:
                        # Preserve tall charts and wide diagrams without
                        # cropping their labels or changing their meaning.
                        contained = ImageOps.contain(original, (888, 500), Image.Resampling.LANCZOS)
                        photo = Image.new('RGB', (888, 500), t.INK)
                        photo.paste(contained, ((888-contained.width)//2, (500-contained.height)//2))
                    else:
                        zoom = 1.04 + 0.12 * photo_phase
                        scaled_w = round(888 * zoom)
                        scaled_h = round(500 * zoom)
                        enlarged = ImageOps.fit(
                            original, (scaled_w, scaled_h),
                            Image.Resampling.LANCZOS, centering=(0.5, 0.48 + 0.08 * photo_phase))
                        max_x = max(0, scaled_w - 888)
                        max_y = max(0, scaled_h - 500)
                        left = round(max_x * (0.12 + 0.76 * photo_phase))
                        top = round(max_y * (0.80 - 0.60 * photo_phase))
                        photo = enlarged.crop((left, top, left + 888, top + 500))

                    img = cover.copy()
                    img.paste(photo, (96, 315))
                    d = ImageDraw.Draw(img)
                    d.rounded_rectangle((96, 815, 984, 1300), radius=38, fill=t.INK)
                    d.rounded_rectangle((110, 335, 340, 395), radius=20, fill=t.INK)
                    label = 'تصویر خبر' if item.get('kind') == 'publisher' else 'تصویر نمادین'
                    d.text((225, 365), t._rtl(label),
                           font=t._font(asset_root, 23, True), fill='white', anchor='mm')

                    reveal_progress = max(0.0, min(1.0, phase / 0.72))
                    revealed = min(len(title_words), 1 + int(reveal_progress * max(0, len(title_words) - 1)))
                    visible = ' '.join(title_words[:revealed])
                    if visible:
                        rows = t._wrap(d, visible, title_font, 740)
                        for row_index, row in enumerate(rows):
                            d.text((930, 855 + row_index * int(title_font.size * 1.42)),
                                   t._rtl(row), font=title_font, fill='white', anchor='rt')
                    add(img, hook_seconds / hook_frames, revealed > previous_revealed)
                    previous_revealed = revealed

                add(img, 0.6)
        else:
            title_font = t._font(asset_root, 72, True)
            title_rows = t._wrap(ImageDraw.Draw(cover), title, title_font, 820)
            if len(title_rows) > 6:
                title_font = t._font(asset_root, 60, True)
                title_rows = t._wrap(ImageDraw.Draw(cover), title, title_font, 820)
            if len(title_rows) > 7:
                raise t.TrialReelError('The headline is too long for the Reel cover.')
            for index in range(hook_frames):
                phase = index / max(hook_frames - 1, 1)
                img = cover.copy()
                d = ImageDraw.Draw(img)
                d.rounded_rectangle((96, 320, 984, 1080), radius=42, fill=t.INK)
                d.ellipse((820, 382, 906, 468), fill=t.GOLD)
                d.text((863, 425), '!', font=t._font(asset_root, 54, True), fill=t.INK, anchor='mm')
                reveal_progress = max(0.0, min(1.0, (phase - 0.04) / 0.72))
                revealed = min(len(title_words), int(reveal_progress * len(title_words)) + (1 if reveal_progress else 0))
                visible = ' '.join(title_words[:revealed])
                if visible:
                    rows = t._wrap(d, visible, title_font, 820)
                    for row_index, row in enumerate(rows):
                        d.text((930, 540 + row_index * int(title_font.size * 1.45)),
                               t._rtl(row), font=title_font, fill='white', anchor='rt')
                d.text((930, 1000), t._rtl('خبر را در چند ثانیه بخوانید'),
                       font=t._font(asset_root, 32, True), fill='#BCEBD3', anchor='rt')
                add(img, hook_seconds / hook_frames, revealed > previous_revealed)
                previous_revealed = revealed
            add(img, 0.6)

        body_photos = []
        for item in (media[1:8] if len(media) > 1 else media[:1]):
            with Image.open(item['path']) as photo:
                if photo.width * photo.height > 40000000:
                    raise t.TrialReelError('Illustrative image is too large.')
                photo = photo.convert('RGB')
                if photo.width / photo.height < 1.25 or photo.width / photo.height > 2.4:
                    contained = ImageOps.contain(photo, (888, 500), Image.Resampling.LANCZOS)
                    image = Image.new('RGB', (888, 500), t.INK)
                    image.paste(contained, ((888-contained.width)//2, (500-contained.height)//2))
                else:
                    image = ImageOps.fit(photo, (888, 500), Image.Resampling.LANCZOS)
            body_photos.append((item, image))
        for page,body in enumerate(chunks,2):
            blank=t._frame(title,'',kind,page,pages,asset_root,story_type)
            draw=ImageDraw.Draw(blank); font=t._font(asset_root,56)
            rows=t._wrap(draw,body,font,780)
            if len(rows)>7: font=t._font(asset_root,48); rows=t._wrap(draw,body,font,780)
            if len(rows)>8: raise t.TrialReelError('A story segment does not fit.')
            if body_photos:
                # Spread all available pictures through the story while text
                # stays on screen and is revealed word by word.
                page_index = page - 2
                photos = body_photos[page_index::len(chunks)]
                if not photos:
                    photos = [body_photos[page_index % len(body_photos)]]
                total_words = sum(len(row.split()) for row in rows)
                duration = max(total_words * step + 2.0, len(photos) * 1.1)
                frames = max(total_words, math.ceil(duration / .16))
                seconds = duration / frames
                top = 880
                line_height = int(font.size * 1.45)
                if top + (len(rows) - 1) * line_height + int(font.size * 1.6) > 1470:
                    raise t.TrialReelError('A story segment does not fit below the image.')
                prior = 0
                for index in range(frames):
                    elapsed_on_card = index * seconds
                    revealed = min(total_words, max(1, int(elapsed_on_card / step) + 1))
                    photo_index = min(len(photos) - 1, int(index * len(photos) / frames))
                    item, image = photos[photo_index]
                    img = blank.copy()
                    img.paste(image, (96, 315))
                    d = ImageDraw.Draw(img)
                    d.rectangle((120, 845, 960, 1470), fill='#FFFFFF')
                    d.rounded_rectangle((110, 335, 340, 395), radius=20, fill=t.INK)
                    label = 'تصویر خبر' if item.get('kind') == 'publisher' else 'تصویر نمادین'
                    d.text((225, 365), t._rtl(label), font=t._font(asset_root,23,True),
                           fill='white', anchor='mm')
                    remaining = revealed
                    for row_index, row in enumerate(rows):
                        parts = row.split()
                        count = min(len(parts), remaining)
                        if count:
                            d.text((930, top + row_index * line_height),
                                   t._rtl(' '.join(parts[:count])), font=font, fill=t.INK, anchor='rt')
                        remaining -= count
                    add(img, seconds, revealed > prior)
                    prior = revealed
                continue
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



