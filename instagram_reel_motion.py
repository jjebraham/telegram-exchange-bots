"""Render Persian word reveals and locally generated typing sounds without AI calls."""
from pathlib import Path
from array import array
import math
import random
import subprocess
import sys
import tempfile
import wave
from PIL import Image, ImageDraw, ImageOps

def grid_cover(t, title, kind, asset_root, media):
    """Make a complete-title first frame, with key content in the center square."""
    canvas = Image.new('RGB', (1080, 1920), '#05162F')
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 420, 1080, 1500), fill='#071D3F')
    d.rounded_rectangle((66, 450, 1014, 1470), radius=40, fill='#102C52')
    d.rounded_rectangle((96, 478, 984, 560), radius=22, fill='#FFFFFF')
    logo = t._brand_mark(asset_root).resize((64, 64), Image.Resampling.LANCZOS)
    canvas.paste(logo, (895, 486), logo)
    d.text((870, 518), t._rtl('صرافی کیانی'), font=t._font(asset_root, 34, True), fill=t.INK, anchor='rm')
    label = 'خبر کریپتو' if kind == 'crypto' else 'خبر اقتصادی'
    d.rounded_rectangle((116, 492, 335, 546), radius=24, fill='#CFF5ED')
    d.text((225, 519), t._rtl(label), font=t._font(asset_root, 25, True), fill=t.INK, anchor='mm')
    if media:
        with Image.open(media[0]['path']) as photo:
            if photo.width * photo.height > 40_000_000:
                raise t.TrialReelError('Article image is too large.')
            photo = photo.convert('RGB')
            photo.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        photo = moving_image(photo, .5, 0, (888, 355), t.INK)
        canvas.paste(photo, (96, 580))
    else:
        d.rectangle((96, 580, 984, 935), fill='#183F68')
        d.text((540, 755), 'KIANI', font=t._font(asset_root, 96, True), fill='#D5FAED', anchor='mm')
    d.rectangle((96, 935, 984, 945), fill='#00D9C8')
    d.rounded_rectangle((96, 945, 984, 1440), radius=24, fill='#081831')
    d.rounded_rectangle((130, 973, 310, 1027), radius=25, fill='#FFD469')
    d.text((220, 1000), t._rtl('در یک نگاه'), font=t._font(asset_root, 25, True), fill=t.INK, anchor='mm')
    # Preserve every word and only shrink within a bounded readable range.
    rows = None
    for size in (70, 64, 58, 52, 48):
        font = t._font(asset_root, size, True)
        try:
            candidate = t._wrap(d, title, font, 740)
        except t.TrialReelError:
            continue
        if len(candidate) <= 6 and len(candidate) * int(size * 1.38) <= 360:
            rows = candidate
            break
    if not rows:
        raise t.TrialReelError('The complete headline does not fit the Reel cover.')
    for i, row in enumerate(rows):
        d.text((925, 1050 + i * int(size * 1.38)), t._rtl(row), font=font, fill='white', anchor='rt')
    d.text((150, 1410), 'kiani.exchange', font=t._font(asset_root, 25, True), fill='#80E4D6', anchor='lm')
    return canvas

def moving_image(original, phase, mode, size, background):
    """Move safely inside the image viewport; keep diagrams completely visible."""
    width, height = size
    aspect = original.width / original.height
    if aspect < 1.25 or aspect > 2.4:
        contained = ImageOps.contain(original, (round(width*.94), round(height*.94)), Image.Resampling.LANCZOS)
        result = Image.new('RGB', size, background)
        dx = round((width-contained.width) * (.35 + .3*phase))
        dy = round((height-contained.height) * (.65 - .3*phase))
        result.paste(contained, (dx, dy))
        return result
    # Alternate zoom, left/right pan and vertical drift across photos.
    if mode % 4 == 0:
        zoom, x, y = 1.03 + .10*phase, .5, .5
    elif mode % 4 == 1:
        zoom, x, y = 1.13, .12 + .76*phase, .5
    elif mode % 4 == 2:
        zoom, x, y = 1.13, .88 - .76*phase, .5
    else:
        zoom, x, y = 1.13, .5, .85 - .70*phase
    scaled_w, scaled_h = round(width*zoom), round(height*zoom)
    fitted = ImageOps.fit(original, (scaled_w, scaled_h), Image.Resampling.LANCZOS)
    left, top = round((scaled_w-width)*x), round((scaled_h-height)*y)
    return fitted.crop((left, top, left+width, top+height))

def render(t, title, source, kind, story_type, chunks, destination, asset_root, media, music_path, ffmpeg, *, narration=None):
    pages=len(chunks)+2
    words=sum(len(s.split()) for s in chunks)
    max_seconds = t.MAX_REEL_SECONDS
    step=min(.14,(max_seconds-4.6-3-2.0*len(chunks))/max(words,1))
    if step<.045: raise t.TrialReelError('Story is too long for a legible animated Reel.')
    if narration is not None:
        if len(narration)!=len(chunks)+1:
            raise t.TrialReelError('Narration does not match Reel sections.')
        if sum(item['duration'] for item in narration)+3.6 > max_seconds:
            raise t.TrialReelError('Narration is too long for a Reel; nothing was published.')
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
        # The first frame has the complete headline for profile thumbnails.
        # After this brief frame, the existing animated title begins.
        add(grid_cover(t, title, kind, asset_root, media), .24)
        title_words = title.split()
        hook_frames = 60
        hook_seconds = max(4.0, narration[0]['duration'] + .3) if narration else 4.0
        voice_starts = [elapsed]
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
                    img.paste(photo, (96, 405))
                    d = ImageDraw.Draw(img)
                    d.rounded_rectangle((96, 905, 984, 1390), radius=38, fill=t.INK)
                    if item.get('kind') == 'publisher':
                        d.rounded_rectangle((110, 425, 340, 485), radius=20, fill=t.INK)
                        d.text((225, 455), t._rtl('تصویر خبر'),
                               font=t._font(asset_root, 23, True), fill='white', anchor='mm')

                    reveal_progress = max(0.0, min(1.0, phase / 0.72))
                    revealed = min(len(title_words), 1 + int(reveal_progress * max(0, len(title_words) - 1)))
                    visible = ' '.join(title_words[:revealed])
                    if visible:
                        rows = t._wrap(d, visible, title_font, 740)
                        for row_index, row in enumerate(rows):
                            d.text((900, 945 + row_index * int(title_font.size * 1.42)),
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
                d.rounded_rectangle((96, 390, 984, 1150), radius=42, fill=t.INK)
                d.ellipse((820, 452, 906, 538), fill=t.GOLD)
                d.text((863, 495), '!', font=t._font(asset_root, 54, True), fill=t.INK, anchor='mm')
                reveal_progress = max(0.0, min(1.0, (phase - 0.04) / 0.72))
                revealed = min(len(title_words), int(reveal_progress * len(title_words)) + (1 if reveal_progress else 0))
                visible = ' '.join(title_words[:revealed])
                if visible:
                    rows = t._wrap(d, visible, title_font, 820)
                    for row_index, row in enumerate(rows):
                        d.text((900, 610 + row_index * int(title_font.size * 1.45)),
                               t._rtl(row), font=title_font, fill='white', anchor='rt')
                d.text((900, 1070), t._rtl('خبر را در چند ثانیه بخوانید'),
                       font=t._font(asset_root, 32, True), fill='#BCEBD3', anchor='rt')
                add(img, hook_seconds / hook_frames, revealed > previous_revealed)
                previous_revealed = revealed
            add(img, 0.6)

        body_photos = []
        for item in media[:8]:
            with Image.open(item['path']) as photo:
                if photo.width * photo.height > 40000000:
                    raise t.TrialReelError('Illustrative image is too large.')
                photo = photo.convert('RGB')
                photo.thumbnail((1600,1600), Image.Resampling.LANCZOS)
            body_photos.append((item, photo))
        for page,body in enumerate(chunks,2):
            if narration:
                voice_starts.append(elapsed)
            blank=t._frame(title,'',kind,page,pages,asset_root,story_type)
            draw=ImageDraw.Draw(blank); font=t._font(asset_root,56)
            rows=t._wrap(draw,body,font,780)
            if len(rows)>6: font=t._font(asset_root,48); rows=t._wrap(draw,body,font,780)
            if len(rows)>8: raise t.TrialReelError('A story segment does not fit.')
            if body_photos:
                # Spread all available pictures through the story while text
                # stays on screen and is revealed word by word.
                page_index = page - 2
                photos = body_photos[page_index::len(chunks)]
                if not photos:
                    photos = [body_photos[page_index % len(body_photos)]]
                if len(photos) == 1 and len(body_photos) > 1:
                    photos.append(next(candidate for candidate in body_photos if candidate is not photos[0]))
                total_words = sum(len(row.split()) for row in rows)
                speech_duration = narration[page-1]['duration'] if narration else 0
                duration = max(total_words * step + 2.0, len(photos) * 1.1, speech_duration + .3)
                word_step = speech_duration / max(total_words, 1) if narration else step
                frames = max(total_words, math.ceil(duration / .10))
                seconds = duration / frames
                top = 940
                line_height = int(font.size * 1.45)
                if top + (len(rows) - 1) * line_height + int(font.size * 1.6) > 1550:
                    raise t.TrialReelError('A story segment does not fit below the image.')
                prior = 0
                for index in range(frames):
                    elapsed_on_card = index * seconds
                    revealed = min(total_words, max(1, int(elapsed_on_card / word_step) + 1))
                    photo_index = min(len(photos) - 1, int(index * len(photos) / frames))
                    item, image = photos[photo_index]
                    segment_start = photo_index * frames / len(photos)
                    segment_length = frames / len(photos)
                    image_phase = max(0.0, min(1.0, (index - segment_start) / max(segment_length-1, 1)))
                    image = moving_image(image, image_phase, page_index+photo_index, (888,500), t.INK)
                    img = blank.copy()
                    img.paste(image, (96, 405))
                    d = ImageDraw.Draw(img)
                    d.rectangle((120, 925, 960, 1550), fill='#FFFFFF')
                    if item.get('kind') == 'publisher':
                        d.rounded_rectangle((110, 425, 340, 485), radius=20, fill=t.INK)
                        d.text((225, 455), t._rtl('تصویر خبر'), font=t._font(asset_root,23,True),
                               fill='white', anchor='mm')
                    remaining = revealed
                    for row_index, row in enumerate(rows):
                        parts = row.split()
                        count = min(len(parts), remaining)
                        if count:
                            d.text((900, top + row_index * line_height),
                                   t._rtl(' '.join(parts[:count])), font=font, fill=t.INK, anchor='rt')
                        remaining -= count
                    add(img, seconds, revealed > prior)
                    prior = revealed
                continue
            top=(1920-len(rows)*int(font.size*1.72))//2
            word_count=sum(len(row.split()) for row in rows)
            card_step = max(step, narration[page-1]['duration']/max(word_count,1)) if narration else step
            for revealed in range(1,word_count+1):
                img=blank.copy(); d=ImageDraw.Draw(img); remaining=revealed
                for index,row in enumerate(rows):
                    part=row.split(); count=min(len(part),remaining)
                    if count: d.text((930,top+index*int(font.size*1.72)),t._rtl(' '.join(part[:count])),font=font,fill=t.INK,anchor='rt')
                    remaining-=count
                add(img,card_step,True)
            add(img,2.0)
        closing = t._frame(title,source,kind,pages,pages,asset_root,story_type)
        if media:
            item = media[0]
            with Image.open(item['path']) as photo:
                if photo.width * photo.height > 40000000:
                    raise t.TrialReelError('Illustrative image is too large.')
                photo = photo.convert('RGB')
                image = ImageOps.contain(photo, (888, 300), Image.Resampling.LANCZOS)
                panel = Image.new('RGB', (888, 300), t.INK)
                panel.paste(image, ((888-image.width)//2, (300-image.height)//2))
            closing.paste(panel, (96, 1280))
            d = ImageDraw.Draw(closing)
            if item.get('kind') == 'publisher':
                d.rounded_rectangle((110, 1294, 340, 1354), radius=20, fill=t.INK)
                d.text((225, 1324), t._rtl('تصویر خبر'), font=t._font(asset_root,23,True),
                       fill='white', anchor='mm')
        add(closing,3)
        if not 12<=elapsed<=max_seconds: raise t.TrialReelError('Animated duration is outside Reel limits.')
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
            samples=array('h',(int(max(-1,min(1,s))*32767) for s in signal))
            if sys.byteorder != 'little': samples.byteswap()
            out.writeframes(samples.tobytes())
        voice_path=None
        if narration:
            sample_rate=24000
            combined=bytearray(int((elapsed+.1)*sample_rate)*2)
            for segment,start in zip(narration,voice_starts):
                with wave.open(str(segment['path']),'rb') as voice:
                    if voice.getframerate()!=sample_rate or voice.getnchannels()!=1 or voice.getsampwidth()!=2:
                        raise t.TrialReelError('Narration audio format is invalid.')
                    data=voice.readframes(voice.getnframes())
                offset=round(start*sample_rate)*2
                if offset+len(data)>len(combined):
                    raise t.TrialReelError('Narration does not fit the Reel timeline.')
                combined[offset:offset+len(data)]=data
            voice_path=root/'narration.wav'
            with wave.open(str(voice_path),'wb') as voice:
                voice.setnchannels(1); voice.setsampwidth(2); voice.setframerate(sample_rate)
                voice.writeframes(combined)
        cmd=[ffmpeg,'-y','-hide_banner','-loglevel','error','-threads','2','-f','concat','-safe','0','-i',str(playlist)]
        if music_path:
            if Path(music_path).is_symlink() or not Path(music_path).is_file(): raise t.TrialReelError('Verified music unavailable.')
            cmd+=['-stream_loop','-1','-i',str(music_path)]
        else: cmd+=['-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000']
        cmd+=['-i',str(sound)]
        if voice_path:
            cmd+=['-i',str(voice_path)]
            filters=f'[1:a]volume=0.10,afade=t=in:st=0:d=0.8,afade=t=out:st={max(0,elapsed-1):.2f}:d=1[m];[2:a]volume=.25[k];[3:a]volume=1.0[v];[m][k][v]amix=inputs=3:duration=first:normalize=0[a]'
        else:
            filters=f'[1:a]volume=0.22,afade=t=in:st=0:d=0.8,afade=t=out:st={max(0,elapsed-1):.2f}:d=1[m];[2:a]volume=.7[k];[m][k]amix=inputs=2:duration=first:normalize=0[a]'
        cmd+=['-filter_complex',filters,
              '-map','0:v:0','-map','[a]','-t',f'{elapsed:.3f}','-r','30','-vf','scale=in_range=full:out_range=tv,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','25','-profile:v','high','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-ar','48000','-ac','2','-movflags','+faststart',str(destination)]
        try: subprocess.run(cmd,capture_output=True,timeout=300,check=True)
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired,OSError): raise t.TrialReelError('Animated Reel rendering failed.') from None



