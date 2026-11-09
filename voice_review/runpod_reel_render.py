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
    if result.returncode: raise RenderError('Remote render command failed')
    return result.stdout


def remote_work(pod,lease,root,home):
    """Use only API-bound SSH metadata, a pinned host key, and this job's bundle."""
    from runpod_manager import render_target
    target=render_target(pod)
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
    check='import os,json;print(json.dumps({"pod":os.environ.get("RUNPOD_POD_ID")}))'
    identity=json.loads(command(ssh+['python3 -c '+shlex.quote(check)],timeout=15))
    if identity.get('pod')!=pod['id']: raise RenderError('SSH endpoint is not the expected Pod')
    bootstrap="set -eu; command -v ffmpeg >/dev/null 2>&1 || (apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg); python3 -c 'import PIL,arabic_reshaper,bidi' 2>/dev/null || python3 -m pip install --disable-pip-version-check --quiet Pillow arabic-reshaper python-bidi"
    started=time.monotonic()
    command(ssh+[bootstrap],timeout=150)
    gpu=command(ssh+['nvidia-smi --query-gpu=name --format=csv,noheader'],timeout=15).decode().strip()
    if pod['gpu']['id'] not in gpu: raise RenderError('Allocated GPU was not verified')
    remote='/tmp/kiani-reel-'+lease
    if not re.fullmatch(r'/tmp/kiani-reel-[a-f0-9]{32}',remote): raise RenderError('Invalid render job identity')
    command(ssh+['mkdir -m 700 '+remote],timeout=15)
    command(['scp',*options,'-P',str(port),str(root/'bundle.tgz'),address+':'+remote+'/bundle.tgz'],timeout=60)
    command(ssh+['tar -xzf '+remote+'/bundle.tgz -C '+remote+' && python3 '+remote+'/code/runpod_remote_render.py '+remote],timeout=240)
    command(['scp',*options,'-P',str(port),address+':'+remote+'/output.mp4',str(root/'output.mp4')],timeout=60)
    command(['scp',*options,'-P',str(port),address+':'+remote+'/result.json',str(root/'remote-result.json')],timeout=15)
    result=json.loads((root/'remote-result.json').read_text())
    if hashlib.sha256((root/'output.mp4').read_bytes()).hexdigest()!=result.get('sha256'):
        raise RenderError('Retrieved video checksum mismatch')
    # Full local decode catches broken/truncated video or audio before publishing.
    command(['ffmpeg','-v','error','-xerror','-i',str(root/'output.mp4'),'-f','null','-'],timeout=90)
    result.update(gpu=gpu,ssh_host_key_fingerprint=fingerprint,remote_total_seconds=round(time.monotonic()-started,3))
    private_write(root/'result.json',result)


def worker(home,lease,unit,root):
    try:
        return probe.run_worker(home,lease,unit,work=lambda pod,l:remote_work(pod,l,root,home))
    except Exception as exc:
        private_write(root/'error.json',{'category':type(exc).__name__})
        raise


def submit(root,*,home=None):
    home=Path.home() if home is None else Path(home)
    root=Path(root).resolve(); state=home/'.local/state/kiani-instagram-runpod'
    if state not in root.parents: raise RenderError('Render bundle must be in private managed state',fallback_safe=True)
    job_id=root.name
    with closing(leases.connect(state/'leases.sqlite3')) as con:
        # The preflight and spend reservation are serialized with the Pod lock.
        from runpod_worker_lock import pod_lock
        cfg=service.private_json(home/'.config/kiani-instagram-runpod/config.json')
        with pod_lock(state,cfg['pod_id']) as held:
            if not held or cfg.get('enabled'): raise RenderError('Another managed GPU session is active',fallback_safe=True)
            month=spend_guard(con)
            con.execute('INSERT INTO render_spend VALUES(?,?,?,?,?)',(job_id,month,None,.5,'RESERVED'))
        lease=None
        def runner(args,**kwargs):
            args=list(args)
            index=next(i for i,v in enumerate(args) if v.endswith('/runpod_api_probe.py'))
            args[index]=str(Path(__file__).resolve())
            args+=['--job',str(root)]
            return subprocess.run(args,**kwargs)
        try:
            lease=probe.begin(home,runner=runner)
            con.execute('UPDATE render_spend SET lease_id=? WHERE job_id=?',(lease,job_id))
            print('Managed GPU render queued; independent watchdog and worker time limit active.',flush=True)
            deadline=time.monotonic()+540
            while time.monotonic()<deadline:
                result=probe.finalize(home,lease)
                if result in ('already disabled','stopped and watchdog returned to disabled mode') or result.startswith('start rejected;'):
                    row=con.execute('SELECT state,created_at,updated_at,rate_usd FROM leases WHERE lease_id=?',(lease,)).fetchone()
                    if not row or row['state'] not in ('CLOSED','START_REJECTED','CANCELLED'): break
                    cost=0 if row['state']!='CLOSED' else (row['updated_at']-row['created_at'])*row['rate_usd']/3600
                    con.execute('UPDATE render_spend SET estimate_usd=?,state=? WHERE job_id=?',(cost,row['state'],job_id))
                    if not (root/'result.json').is_file(): raise RenderError('GPU render did not complete; Pod confirmed stopped',fallback_safe=True)
                    info=json.loads((root/'result.json').read_text()); info.update(lease_id=lease,estimated_compute_usd=round(cost,6),shutdown_confirmed=True)
                    private_write(root/'result.json',info)
                    return info
                time.sleep(3)
            raise RenderError('Managed GPU outcome unresolved; watchdog retained')
        except Exception as exc:
            if lease is None:
                active=con.execute("SELECT COUNT(*) FROM leases WHERE pod_id=? AND state IN ('RESERVED','START_REQUESTED','START_CONFIRMED','ACTION_UNCERTAIN','STOP_REQUESTED')",(cfg['pod_id'],)).fetchone()[0]
                if active:
                    raise RenderError('GPU launch could not be confirmed; budget reservation and watchdog retained') from None
                con.execute('UPDATE render_spend SET estimate_usd=0,state=? WHERE job_id=?',('NOT_STARTED',job_id))
                if isinstance(exc,RenderError): raise
                raise RenderError('Managed GPU startup preflight failed',fallback_safe=True) from None
            if isinstance(exc,RenderError): raise
            raise RenderError('Managed GPU job requires recovery') from None


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
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--unit');p.add_argument('--job',required=True)
    a=p.parse_args()
    try:
        root=Path(a.job).resolve(); state=Path.home()/'.local/state/kiani-instagram-runpod'
        if state not in root.parents or root.is_symlink(): raise RenderError('Untrusted render job location')
        print(worker(Path.home(),a.worker,a.unit,Path(a.job)) if a.worker else json.dumps(submit(Path(a.job))),flush=True)
    except Exception as exc:
        print('Managed GPU renderer stopped:',type(exc).__name__,flush=True);raise SystemExit(1)
