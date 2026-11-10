"""One disposable GPU per render session, with a persistent independent watchdog.

Only this manager's newly created, uniquely named Pods are stopped/deleted.
Existing Pods are untouched. Inputs, output verification and API secrets stay
on Selenium. No request with an unknown outcome is automatically retried.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener
from urllib.error import HTTPError
import json, os, re, subprocess, sys, time, uuid

from runpod_api_client import RunpodAPI, NoRedirect
import runpod_lease_store as leases
import runpod_secrets
import runpod_watchdog_service as service
from runpod_systemd_guard import validate_properties
from runpod_reel_render import RenderError, command, private_write, remote_work, spend_guard

TIMER='kiani-runpod-render-watchdog.timer'
SERVICE='kiani-runpod-render-watchdog.service'
TERMINAL={'COMPLETE','FAILED_STOPPED','NO_CAPACITY'}
GPUS=('NVIDIA RTX A6000','NVIDIA GeForce RTX 4090','NVIDIA L4')
# Official Runpod base 2.0.0 / Ubuntu 24.04, verified registry digest. Video
# encoding needs the host driver, not a multi-gigabyte PyTorch/CUDA toolkit.
IMAGE='runpod/base@sha256:4e92edb0d7c90f5bc4e9fc8cdd1a4c9e0e330d4bc58c18bbfc677090af92be90'


def paths(home): return home/'.local/state/kiani-instagram-runpod'


def api(home):
    return RunpodAPI(runpod_secrets.read(home/'.config/kiani-instagram-runpod/credentials.env'))


def http(home,path,body=None,*,method=None):
    key=runpod_secrets.read(home/'.config/kiani-instagram-runpod/credentials.env')
    req=Request('https://api.runpod.io'+path,data=None if body is None else json.dumps(body).encode(),
                headers={'Authorization':'Bearer '+key,'Accept':'application/json','Content-Type':'application/json'},
                method=method or ('GET' if body is None else 'POST'))
    with build_opener(NoRedirect()).open(req,timeout=30) as res:
        if res.status==204: return None
        raw=res.read(2_000_001)
    if len(raw)>2_000_000: raise RenderError('Oversized provider response')
    return json.loads(raw)


def unit_contents(home):
    python=str(Path(sys.executable).resolve()); script=str(Path(__file__).resolve())
    if any(c in python+script+str(home) for c in '\n\r%'): raise RenderError('Invalid service path')
    return {
      SERVICE:'[Unit]\nDescription=Kiani disposable render cleanup\nStartLimitIntervalSec=0\n\n[Service]\nType=exec\nEnvironment="HOME='+str(home)+'"\nExecStart="'+python+'" -B "'+script+'" --sweep\nRuntimeMaxSec=90s\nTimeoutStopSec=5s\nRestart=on-failure\nRestartSec=30s\n',
      TIMER:'[Unit]\nDescription=Watch Kiani GPU render sessions\n\n[Timer]\nOnBootSec=30s\nOnUnitActiveSec=30s\nAccuracySec=1s\nUnit='+SERVICE+'\n\n[Install]\nWantedBy=timers.target\n'}


def install(home):
    state=paths(home);state.mkdir(parents=True,mode=0o700,exist_ok=True)
    if any(service.private_json(p).get('state') not in TERMINAL for p in state.glob('render-*/session.json')):
        raise RenderError('A managed render is active; watchdog upgrade refused')
    directory=home/'.config/systemd/user';directory.mkdir(parents=True,exist_ok=True)
    for name,content in unit_contents(home).items():
        path=directory/name
        if path.is_symlink(): raise RenderError('Untrusted watchdog service location')
        if path.exists():
            backup=state/(name+'.backup-'+uuid.uuid4().hex);backup.write_bytes(path.read_bytes());backup.chmod(0o600)
        path.write_text(content);path.chmod(0o600)
    command(['systemctl','--user','daemon-reload'],15)
    command(['systemctl','--user','enable','--now',TIMER],15)
    command(['systemctl','--user','start',SERVICE],45)
    print('Independent render watchdog installed and active; no Pod started.',flush=True)


def verify_watchdog(home):
    for name,content in unit_contents(home).items():
        path=home/'.config/systemd/user'/name
        if path.is_symlink() or path.read_text()!=content: raise RenderError('Render watchdog revision differs',fallback_safe=True)
    command(['systemctl','--user','is-enabled','--quiet',TIMER],10)
    command(['systemctl','--user','is-active','--quiet',TIMER],10)


def active(unit):
    result=subprocess.run(['systemctl','--user','is-active','--quiet',unit],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
    return result.returncode==0


def matching_pod(home,session):
    if session.get('pod_id'):
        try: return http(home,'/v2/pods/'+session['pod_id'])
        except HTTPError as exc:
            if exc.code==404 and session.get('delete_requested') and session.get('shutdown_confirmed'): return None
            raise RenderError('Managed Pod status unavailable') from None
        except Exception: raise RenderError('Managed Pod status unavailable') from None
    found=http(home,'/v2/pods?limit=1000')
    if found.get('pagination',{}).get('hasNextPage'): raise RenderError('Placement inventory incomplete')
    matches=[p for p in found.get('pods',[]) if p.get('name')==session['name'] and p.get('id') not in session['before']]
    if len(matches)>1: raise RenderError('Ambiguous placement identity')
    return matches[0] if matches else None


def owned(pod,session):
    if (pod.get('name')!=session['name'] or pod.get('id') in session['before'] or pod.get('mounts')):
        return False
    created=datetime.fromisoformat(pod['createdAt'].replace('Z','+00:00')).timestamp()
    if not session['created_at']-60<=created<=session['created_at']+180: return False
    if session.get('started_at') and pod.get('startedAt')!=session['started_at']: return False
    return True


def close_budget(home,root,session,state):
    cost=0.0 if state=='NO_CAPACITY' else max(0,time.time()-session['created_at'])*session.get('rate',1)/3600
    with closing(leases.connect(paths(home)/'leases.sqlite3')) as con:
        con.execute('UPDATE render_spend SET estimate_usd=?,state=? WHERE job_id=?',(cost,state,root.name))
    session.update(state=state,stopped_at=time.time(),estimated_compute_usd=round(cost,6),shutdown_confirmed=True)
    private_write(root/'session.json',session)
    return session


def cleanup(home,root,*,force=False):
    from runpod_worker_lock import pod_lock
    with pod_lock(paths(home),'disposable-cleanup-'+root.name.rsplit('-',1)[-1]) as held:
        if not held: return 'cleanup_busy'
        session=service.private_json(root/'session.json')
        if session['state'] in TERMINAL: return session['state']
        running=active(session['unit'])
        if running and not force and time.time()-session['created_at']<450:
            private_write(root/'watchdog.json',{'time':time.time(),'result':'watching'})
            return 'watching'
        if running and not force:
            command(['systemctl','--user','stop',session['unit']],15)
        if session['state']=='PREPARING':
            if time.time()-session['created_at']<30 and not force: return 'queued'
            return close_budget(home,root,session,'NO_CAPACITY')['state']
        pod=matching_pod(home,session)
        if pod is None:
            if session.get('delete_requested') and session.get('shutdown_confirmed'):
                return close_budget(home,root,session,'COMPLETE' if (root/'result.json').is_file() else 'FAILED_STOPPED')['state']
            if session.get('create_rejected'): return close_budget(home,root,session,'NO_CAPACITY')['state']
            return 'creation_unconfirmed'
        if not owned(pod,session): raise RenderError('Disposable Pod ownership changed; automatic action refused')
        session.update(pod_id=pod['id'],rate=pod.get('cost',1))
        private_write(root/'session.json',session)
        if pod['status']!='EXITED':
            if pod.get('locked') is not False or 'stop' not in pod.get('actions',[]): return 'stop_not_available'
            try: api(home).transition(pod['id'],'stop')
            except Exception: return 'stop_response_unconfirmed'
            pod=api(home).status(pod['id'])
            if pod.get('status')!='EXITED': return 'stop_requested'
        # This Pod was created only for this reproducible job; stop before deletion.
        session.update(state='STOPPED_DELETE_PENDING',delete_requested=True,shutdown_confirmed=True)
        private_write(root/'session.json',session)
        try: http(home,'/v2/pods/'+pod['id'],method='DELETE')
        except HTTPError as exc:
            if exc.code!=404: return 'stopped_cleanup_pending'
        except Exception: return 'stopped_cleanup_pending'
        state='COMPLETE' if (root/'result.json').is_file() else 'FAILED_STOPPED'
        return close_budget(home,root,session,state)['state']


def sweep(home):
    root=paths(home);root.mkdir(parents=True,mode=0o700,exist_ok=True)
    failures=0
    for path in sorted(root.glob('render-*/session.json')):
        try:
            if service.private_json(path).get('state') in TERMINAL: continue
            result=cleanup(home,path.parent)
            if result not in TERMINAL|{'watching','queued','cleanup_busy','stop_requested'}: failures+=1
        except Exception: failures+=1
    private_write(root/'render-watchdog-heartbeat.json',{'time':time.time(),'recovery_needed':failures})
    return failures


def candidates(home):
    catalog=http(home,'/v2/catalog/gpus?include=AVAILABILITY&product=POD&cloud=SECURE')
    return [g for name in GPUS for g in catalog['gpus'] if g['id']==name and
            g.get('availability') in ('LOW','MEDIUM','HIGH') and 0<g.get('price',{}).get('secure',999)<=1]


def acknowledge_watchdog(root,*,wait=time.sleep):
    # A timer pass may already be finishing when this worker starts. Require
    # this job's own fresh acknowledgement; do not mistake a queued pass for it.
    for attempt in range(15):
        command(['systemctl','--user','start',SERVICE],45)
        try:
            beat=service.private_json(root/'watchdog.json')
            if beat.get('result')=='watching' and time.time()-beat['time']<=10: return
        except (OSError,ValueError): pass
        wait(.5)
    raise RenderError('Independent render watchdog did not observe worker')


def worker(home,root):
    session=service.private_json(root/'session.json');unit=session['unit']
    for attempt in range(10):
        properties=command(['systemctl','--user','show',unit,'-p','MainPID','-p','ActiveState','-p','RuntimeMaxUSec'],10).decode()
        try: validate_properties(properties,os.getpid(),maximum_seconds=420);break
        except Exception:
            if attempt==9: raise
            time.sleep(.3)
    verify_watchdog(home)
    acknowledge_watchdog(root)
    try:
        inventory=http(home,'/v2/pods?limit=1000')
        if inventory.get('pagination',{}).get('hasNextPage'): raise RenderError('Placement inventory incomplete')
        session.update(before=[p['id'] for p in inventory['pods']],state='CREATE_REQUESTED'); private_write(root/'session.json',session)
        public=(home/'.ssh/runpod_reels_ed25519.pub').read_text().strip()
        if not public.startswith('ssh-ed25519 ') or '\n' in public: raise RenderError('Rendering public key unavailable')
        for gpu in candidates(home):
            body={'name':session['name'],'image':IMAGE,'cloud':'SECURE','gpu':{'id':gpu['id'],'count':1},
                  'disk':20,'mounts':{},'ports':['22/tcp'],'startSsh':True,
                  'env':{'PUBLIC_KEY':public,'NVIDIA_DRIVER_CAPABILITIES':'compute,utility,video'}}
            try: pod=http(home,'/v2/pods',body)
            except HTTPError as exc:
                if exc.code in (400,403): continue
                session['create_rejected']=exc.code in (401,402,404,413,422)
                private_write(root/'session.json',session);raise
            session.update(pod_id=pod.get('id'),rate=pod.get('cost',1),state='STARTING')
            private_write(root/'session.json',session)
            if not owned(pod,session) or not 0<pod.get('cost',999)<=1: raise RenderError('Placement rate or identity not approved')
            deadline=time.monotonic()+180
            while pod.get('status') in ('PROVISIONING','STARTING') and time.monotonic()<deadline:
                time.sleep(3);pod=api(home).status(pod['id'])
            if pod.get('status')!='RUNNING': raise RenderError('GPU startup did not complete')
            session.update(started_at=pod.get('startedAt'),state='RENDERING'); private_write(root/'session.json',session)
            remote_work(pod,session['nonce'],root,home)
            session=service.private_json(root/'session.json');session['state']='OUTPUT_VERIFIED';private_write(root/'session.json',session)
            break
        else:
            session['create_rejected']=True;private_write(root/'session.json',session)
            raise RenderError('No approved GPU capacity available')
    except Exception as exc:
        private_write(root/'error.json',{'category':type(exc).__name__,'detail':str(exc) if isinstance(exc,RenderError) else None,
                                        'diagnostic':getattr(exc,'diagnostic',None)})
    finally:
        cleanup(home,root,force=True)


def submit(home,root):
    state=paths(home);verify_watchdog(home)
    nonce=uuid.uuid4().hex
    session={'nonce':nonce,'name':'kiani-reel-'+nonce,'unit':'kiani-runpod-render-'+nonce+'.service',
             'state':'PREPARING','created_at':time.time(),'before':[]}
    with closing(leases.connect(state/'leases.sqlite3')) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            month=spend_guard(con)
            if con.execute("SELECT COUNT(*) FROM render_spend WHERE state='RESERVED'").fetchone()[0]:
                raise RenderError('A GPU session is already reserved; using local rendering',fallback_safe=True)
            con.execute('INSERT INTO render_spend VALUES(?,?,?,?,?)',(root.name,month,nonce,.5,'RESERVED'))
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK');raise
    private_write(root/'session.json',session)
    try:
        command(['systemd-run','--user','--quiet','--collect','--no-block','--unit='+session['unit'],
                 '--property=Type=exec','--property=RuntimeMaxSec=420s','--property=TimeoutStopSec=10s',
                 '--setenv=HOME='+str(home),sys.executable,str(Path(__file__).resolve()),'--worker',str(root)],15)
    except Exception:
        # No create request can precede a supervised worker; sweep still resolves
        # an uncertain launch rather than trusting the launcher response.
        raise RenderError('GPU worker launch unconfirmed; watchdog retained') from None
    deadline=time.monotonic()+540
    while time.monotonic()<deadline:
        time.sleep(3);data=service.private_json(root/'session.json')
        if data['state'] in TERMINAL:
            if data['state']!='COMPLETE': raise RenderError('GPU session ended without usable output; compute stopped',fallback_safe=True)
            info=json.loads((root/'result.json').read_text())
            info.update(lease_id=nonce,estimated_compute_usd=data['estimated_compute_usd'],shutdown_confirmed=True)
            private_write(root/'result.json',info);return info
    raise RenderError('GPU session needs recovery; watchdog and budget reservation retained')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--install',action='store_true');parser.add_argument('--sweep',action='store_true');parser.add_argument('--worker');parser.add_argument('--job')
    args=parser.parse_args();home=Path.home()
    try:
        if args.install: install(home)
        elif args.sweep: raise SystemExit(1 if sweep(home) else 0)
        else:
            root=Path(args.worker or args.job).resolve()
            if root.parent!=paths(home) or not re.fullmatch(r'render-[a-z0-9-]+',root.name): raise RenderError('Invalid job path')
            print(worker(home,root) if args.worker else json.dumps(submit(home,root)),flush=True)
    except Exception as exc:
        print('GPU session:',str(exc) if isinstance(exc,RenderError) else type(exc).__name__,flush=True);raise SystemExit(1)
