"""On-demand reproducible rendering; publishing and credentials stay on Selenium.

The supervised worker shares the independent lifecycle watchdog. Inputs are
saved before startup, outputs are retrieved and decoded before returning, and
only a confirmed stopped Pod permits fallback after a submitted GPU job.
"""
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone
import hashlib, json, os, re, shlex, shutil, sqlite3, subprocess, sys, tarfile, tempfile, time, uuid

import runpod_api_probe as probe
from runpod_api_client import RunpodAPI
import runpod_lease_store as leases
import runpod_secrets
import runpod_watchdog_service as service


class RenderError(RuntimeError):
    def __init__(self,message,*,fallback_safe=False):
        super().__init__(message); self.fallback_safe=fallback_safe


def private_write(path,data):
    path=Path(path)
    fd,name=tempfile.mkstemp(prefix='.render-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(data,out,ensure_ascii=False,indent=2); out.write('\n');out.flush();os.fsync(out.fileno())
        os.chmod(name,0o600); os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


def bundle(story,kind,asset_root,media,narration,music_path,root,*,runtime=None):
    """Copy an explicit allowlist of code/assets; never copy env or cache files."""
    root=Path(root); root.mkdir(mode=0o700,parents=True,exist_ok=True)
    runtime=Path(runtime) if runtime else Path(__file__).resolve().parent.parent
    manifest={}
    def copy(source,name):
        source=Path(source)
        if source.is_symlink() or not source.is_file() or source.stat().st_size>50_000_000:
            raise RenderError('An approved render input is unavailable',fallback_safe=True)
        dest=root/name; dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        shutil.copyfile(source,dest); dest.chmod(0o600)
        manifest[name]=hashlib.sha256(dest.read_bytes()).hexdigest()
        return name
    for name in ('instagram_trial_reels.py','instagram_reel_motion.py','instagram_reel_usage.py'):
        copy(runtime/name,'code/'+name)
    for name in ('reel_audio_mix.py','runpod_remote_render.py'):
        copy(runtime/'voice_review'/name,'code/'+name)
    for name in ('fonts/Vazirmatn-Regular.ttf','fonts/Vazirmatn-Bold.ttf','assets/instagram/kiani-logo.svg'):
        copy(Path(asset_root)/name,'assets/'+name)
    images=[]
    for i,item in enumerate(media or []):
        images.append({'path':copy(item['path'],f'media/{i}.jpg'),'kind':item.get('kind','publisher')})
    segments=[]
    for i,item in enumerate(narration or []):
        segments.append({'path':copy(item['path'],f'narration/{i}.wav'),
                         'duration':item['duration'],'word_starts':item['word_starts']})
    data={'story':{k:story[k] for k in ('title_fa','summary_fa','source_name','story_type','reel_length') if k in story},
          'kind':kind,'media':images,'narration':segments,
          'music':copy(music_path,'music/audio') if music_path else None,'manifest':manifest,
          'music_volume':float(os.environ.get('REEL_MUSIC_VOLUME','0.20')),
          'ducking':os.environ.get('REEL_AUDIO_DUCKING_ENABLED','true')=='true','encoder':'h264_nvenc'}
    if not 0<=data['music_volume']<=.2: raise RenderError('Unreviewed music level',fallback_safe=True)
    private_write(root/'job.json',data)
    with tarfile.open(root/'bundle.tgz','w:gz') as archive:
        for name in ('job.json',*manifest): archive.add(root/name,arcname=name,recursive=False)
    return data


def spend_guard(con,now=None,*,monthly_cap=10.0,reserve=.5):
    """Reserve the full possible session before starting; no monthly reset edits."""
    now=datetime.now(timezone.utc) if now is None else now
    month=now.strftime('%Y-%m')
    con.execute('CREATE TABLE IF NOT EXISTS render_spend(job_id TEXT PRIMARY KEY,month_utc TEXT NOT NULL,lease_id TEXT,estimate_usd REAL NOT NULL,state TEXT NOT NULL)')
    total=con.execute('SELECT COALESCE(SUM(estimate_usd),0) FROM render_spend WHERE month_utc=?',(month,)).fetchone()[0]
    if total+reserve>monthly_cap+1e-9: raise RenderError('Monthly GPU budget exhausted',fallback_safe=True)
    return month


def command(args,timeout=30):
    result=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout)
    if result.returncode:
        stderr=result.stderr.decode('utf-8',errors='replace').lower()
        category='command_failed'
        for needle,label in (('permission denied','ssh_authentication'),('connection refused','ssh_not_ready'),
                             ('no such file','missing_render_file'),('unknown encoder','nvenc_not_installed'),
                             ('libnvidia-encode','nvenc_driver_missing'),('cannot load libcuda','cuda_driver_missing'),
                             ('no module named','render_dependency_missing'),('error reinitializing filters','video_filter_failed')):
            if needle in stderr: category=label;break
        error=RenderError('Render command failed: '+category)
        error.diagnostic=stderr[-4000:]
        raise error
    return result.stdout


def remote_work(pod,lease,root,home):
    """Use only API-bound SSH metadata, a pinned host key, and this job's bundle."""
    from runpod_manager import render_target, ManagerError
    deadline=time.monotonic()+180
    while True:
        try:
            target=render_target(pod);break
        except ManagerError:
            if time.monotonic()>=deadline: raise RenderError('Direct render connection did not become available') from None
            time.sleep(3)
            current=RunpodAPI(runpod_secrets.read(home/'.config/kiani-instagram-runpod/credentials.env')).status(pod['id'])
            if current.get('status')!='RUNNING' or current.get('startedAt')!=pod.get('startedAt'):
                raise RenderError('Render Pod generation changed before connection')
            pod=current
    host,port,user=target['ssh_host'],target['ssh_port'],target['ssh_user']
    key=home/'.ssh/runpod_reels_ed25519'
    if key.is_symlink() or key.stat().st_mode&0o077: raise RenderError('Protected rendering SSH key unavailable')
    known=root/'known_hosts'
    deadline=time.monotonic()+45
    while True:
        try:
            scanned=command(['ssh-keyscan','-T','5','-p',str(port),'-t','ed25519',host],timeout=10)
            break
        except RenderError:
            if time.monotonic()>=deadline: raise
            time.sleep(3)
    lines=[line for line in scanned.decode().splitlines() if not line.startswith('#')]
    if len(lines)!=1 or lines[0].split()[1]!='ssh-ed25519': raise RenderError('SSH host identity unavailable')
    known.write_text(lines[0]+'\n'); known.chmod(0o600)
    fingerprint=hashlib.sha256(lines[0].split()[2].encode()).hexdigest()
    options=['-i',str(key),'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','ForwardAgent=no',
             '-o','ConnectTimeout=8','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2',
             '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known)]
    address=user+'@'+host
    ssh=['ssh',*options,'-p',str(port),address]
    # SSH port publication can precede sshd readiness.
    # sshd does not inherit Docker's environment. Read only the Pod identity
    # from PID 1; never serialize the rest of that environment to Selenium.
    check=('import os,json;from pathlib import Path;'
           'items=Path("/proc/1/environ").read_bytes().split(b"\\x00");'
           'pod=next((x.split(b"=",1)[1].decode() for x in items if x.startswith(b"RUNPOD_POD_ID=")),None);'
           'print(json.dumps({"pod":os.environ.get("RUNPOD_POD_ID") or pod}))')
    identity=json.loads(command(ssh+['python3 -c '+shlex.quote(check)],timeout=15))
    if identity.get('pod')!=pod['id']: raise RenderError('SSH endpoint is not the expected Pod')
    print('GPU render stage: SSH identity verified',flush=True)
    def remote_command(script,timeout):
        # Restore only execution paths from Docker's environment. sshd starts
        # with a minimal PATH, which can select Ubuntu's system Python instead
        # of the image's prepared Python environment.
        bridge=('import os;from pathlib import Path;'
                'items=Path("/proc/1/environ").read_bytes().split(b"\\x00");'
                'values=dict(x.split(b"=",1) for x in items if b"=" in x);'
                'env=os.environ.copy();'
                'env.update({k:values[k.encode()].decode() for k in ("PATH","LD_LIBRARY_PATH","VIRTUAL_ENV","CUDA_VISIBLE_DEVICES","NVIDIA_VISIBLE_DEVICES","NVIDIA_DRIVER_CAPABILITIES") if k.encode() in values});'
                'os.execvpe("bash",["bash","-c",'+repr(script)+'],env)')
        return command(ssh+['python3 -c '+shlex.quote(bridge)],timeout=timeout)
    bootstrap=("set -eu; if ! command -v ffmpeg >/dev/null 2>&1 || ! python3 -m venv /tmp/kiani-render-venv >/dev/null 2>&1; then "
               "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg python3-venv; "
               "python3 -m venv /tmp/kiani-render-venv; fi; "
               "/tmp/kiani-render-venv/bin/python -m pip install --disable-pip-version-check --quiet "
               "Pillow==12.3.0 arabic-reshaper==3.0.1 python-bidi==0.6.11")
    started=time.monotonic()
    remote_command(bootstrap,150)
    print('GPU render stage: dependencies ready',flush=True)
    gpu=remote_command('nvidia-smi --query-gpu=name --format=csv,noheader',15).decode().strip()
    if pod['gpu']['id'] not in gpu: raise RenderError('Allocated GPU was not verified')
    remote_command('ffmpeg -hide_banner -loglevel error -y -f lavfi -i color=c=black:s=1080x1920:r=30 -t 0.5 -an -c:v h264_nvenc -preset p4 -pix_fmt yuv420p /tmp/kiani-nvenc-check.mp4',30)
    print('GPU render stage: NVENC hardware encoder verified',flush=True)
    remote='/tmp/kiani-reel-'+lease
    if not re.fullmatch(r'/tmp/kiani-reel-[a-f0-9]{32}',remote): raise RenderError('Invalid render job identity')
    remote_command('mkdir -m 700 '+remote,15)
    command(['scp',*options,'-P',str(port),str(root/'bundle.tgz'),address+':'+remote+'/bundle.tgz'],timeout=60)
    print('GPU render stage: encoding verified input bundle',flush=True)
    remote_command('tar -xzf '+remote+'/bundle.tgz -C '+remote+' && /tmp/kiani-render-venv/bin/python '+remote+'/code/runpod_remote_render.py '+remote,240)
    command(['scp',*options,'-P',str(port),address+':'+remote+'/output.mp4',str(root/'output.mp4')],timeout=60)
    command(['scp',*options,'-P',str(port),address+':'+remote+'/result.json',str(root/'remote-result.json')],timeout=15)
    result=json.loads((root/'remote-result.json').read_text())
    if hashlib.sha256((root/'output.mp4').read_bytes()).hexdigest()!=result.get('sha256'):
        raise RenderError('Retrieved video checksum mismatch')
    # Full local decode catches broken/truncated video or audio before publishing.
    command(['ffmpeg','-v','error','-xerror','-i',str(root/'output.mp4'),'-f','null','-'],timeout=90)
    print('GPU render stage: video and audio decoded on Selenium',flush=True)
    result.update(gpu=gpu,ssh_host_key_fingerprint=fingerprint,remote_total_seconds=round(time.monotonic()-started,3))
    private_write(root/'result.json',result)


def submit(root,*,home=None):
    from runpod_ephemeral import submit as submit_disposable
    return submit_disposable(Path.home() if home is None else Path(home),Path(root).resolve())


def render(story,kind,destination,asset_root,*,media,narration,music_path):
    home=Path.home(); state=home/'.local/state/kiani-instagram-runpod'
    root=state/('render-'+uuid.uuid4().hex)
    bundle(story,kind,asset_root,media,narration,music_path,root)
    result=submit(root,home=home)
    import instagram_trial_reels as trial
    duration=trial._probe_video(root/'output.mp4',shutil.which('ffprobe') or 'ffprobe')
    target=Path(destination); target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(root/'output.mp4',target); target.chmod(0o644)
    story['_rendering']={'renderer':'runpod','encoder':'h264_nvenc','estimated_gpu_compute_usd':result['estimated_compute_usd'],'gpu_session':result['lease_id']}
    return duration


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True)
    args=parser.parse_args()
    try: print(json.dumps(submit(Path(args.job))),flush=True)
    except Exception as exc:
        print('Managed GPU renderer stopped:',type(exc).__name__,flush=True);raise SystemExit(1)
