"""Render a verified, self-contained bundle. No credentials or publishing APIs."""
from pathlib import Path
import hashlib, json, os, subprocess, sys, time


def render(root):
    root=Path(root).resolve()
    data=json.loads((root/'job.json').read_text())
    for name,digest in data['manifest'].items():
        path=root/name
        if (path.is_symlink() or not path.is_file() or root not in path.resolve().parents
                or hashlib.sha256(path.read_bytes()).hexdigest()!=digest):
            raise ValueError('Render input checksum mismatch')
    sys.path.insert(0,str(root/'code'))
    import instagram_trial_reels as trial
    trial.STATE=root/'frames'; trial.STATE.mkdir(mode=0o700,exist_ok=True)
    os.environ['REEL_VIDEO_ENCODER']=data.get('encoder','h264_nvenc')
    os.environ['REEL_RUNPOD_ENABLED']='false'
    os.environ['REEL_MUSIC_VOLUME']=str(data['music_volume'])
    os.environ['REEL_AUDIO_DUCKING_ENABLED']='true' if data['ducking'] else 'false'
    media=[dict(item,path=root/item['path']) for item in data['media']]
    narration=[dict(item,path=root/item['path']) for item in data['narration']] if data['narration'] else None
    started=time.monotonic()
    duration=trial.render_video(data['story'],data['kind'],root/'output.mp4',root/'assets',
             media=media,narration=narration,music_path=root/data['music'] if data['music'] else None)
    result={'duration_seconds':duration,'render_seconds':round(time.monotonic()-started,3),
            'encoder':os.environ['REEL_VIDEO_ENCODER'],'sha256':hashlib.sha256((root/'output.mp4').read_bytes()).hexdigest()}
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__': render(sys.argv[1])
