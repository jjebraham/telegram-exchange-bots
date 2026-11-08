"""FFmpeg filter construction for the opt-in narrated Reel mix."""
import math


def mix_filter(duration, music_volume=0.20, ducking=True):
    if (not isinstance(duration, (int, float)) or isinstance(duration, bool) or
            not math.isfinite(duration) or duration < 1 or duration > 300):
        raise ValueError('Invalid Reel audio duration.')
    if (not isinstance(music_volume, (int, float)) or isinstance(music_volume, bool) or
            not math.isfinite(music_volume) or not 0 <= music_volume <= 1):
        raise ValueError('Invalid music volume.')
    if not isinstance(ducking, bool):
        raise ValueError('Invalid ducking setting.')
    # Production's un-narrated base is .22. The default multiplier is .20.
    level = .22 * music_volume
    end = max(0.0, duration - 1.0)
    music = (f'[1:a]aformat=sample_rates=48000:channel_layouts=stereo,'
             f'volume={level:.6f},afade=t=in:st=0:d=0.8,'
             f'afade=t=out:st={end:.3f}:d=1[m];')
    keys = '[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=.25[k];'
    voice = '[3:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1[v0];'
    if ducking:
        duck = ('[v0]asplit=2[v][side];'
                '[m][side]sidechaincompress=threshold=.025:ratio=8:attack=25:release=300[bed];')
    else:
        duck = '[v0]anull[v];[m]anull[bed];'
    return music + keys + voice + duck + '[bed][k][v]amix=inputs=3:duration=first:normalize=0,alimiter=limit=.95:level=false[a]'

