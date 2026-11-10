"""Pod-local deadline using only Runpod's already-injected runtime credential.

Never accepts or transfers the account API key. The target must match PID 1's
Pod identity; this helper can only request that its own disposable Pod stop.
"""
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
import argparse,json,os,re,subprocess,sys,time


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def credential(expected):
    values=dict(x.split(b'=',1) for x in Path('/proc/1/environ').read_bytes().split(b'\x00') if b'=' in x)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',expected) or values.get(b'RUNPOD_POD_ID',b'').decode()!=expected:
        raise ValueError('Pod-local guard identity mismatch')
    token=values.get(b'RUNPOD_API_KEY',b'').decode()
    if not token or '\n' in token or '\r' in token:raise ValueError('Pod-local runtime credential unavailable')
    return token


def request(pod,token,*,stop=False):
    url='https://api.runpod.io/v2/pods/'+pod+('/action' if stop else '')
    req=Request(url,data=b'{"action":"stop"}' if stop else None,
                headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},
                method='POST' if stop else 'GET')
    with build_opener(NoRedirect()).open(req,timeout=10) as response:raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Oversized native guard response')
    data=json.loads(raw)
    if data.get('id')!=pod:raise ValueError('Pod-local guard response identity mismatch')
    return data.get('status')


def record(path,data):
    temp=path.with_suffix('.tmp')
    with temp.open('w') as stream:json.dump(data,stream);stream.flush();os.fsync(stream.fileno())
    temp.chmod(0o600);os.replace(temp,path)


def run(pod,deadline,marker):
    token=credential(pod)
    if not time.time()-60<=deadline<=time.time()+480:raise ValueError('Invalid Pod-local deadline')
    request(pod,token)
    record(marker,{'pod':pod,'pid':os.getpid(),'deadline':deadline,'state':'armed'})
    while time.time()<deadline:time.sleep(max(0,min(2,deadline-time.time())))
    while True:
        try:
            status=request(pod,token)
            if status=='EXITED':return
            request(pod,token,stop=True)
            record(marker,{'pod':pod,'pid':os.getpid(),'deadline':deadline,'state':'stop_requested'})
        except Exception:
            # Never store provider response bodies or credentials.
            record(marker,{'pod':pod,'pid':os.getpid(),'deadline':deadline,'state':'stop_retry'})
        time.sleep(10)


def arm(pod,deadline,marker):
    if marker.exists():raise ValueError('A Pod-local guard is already armed here')
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--run','--pod',pod,
                            '--deadline',str(deadline),'--marker',str(marker)],stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)
    until=time.monotonic()+15
    while time.monotonic()<until:
        if child.poll() is not None:raise ValueError('Pod-local guard did not start')
        if marker.is_file():
            data=json.loads(marker.read_text())
            if data.get('pod')==pod and data.get('pid')==child.pid and data.get('state')=='armed':return data
        time.sleep(.2)
    raise ValueError('Pod-local guard acknowledgement unavailable')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',action='store_true');parser.add_argument('--run',action='store_true')
    parser.add_argument('--pod',required=True);parser.add_argument('--deadline',type=float,required=True);parser.add_argument('--marker',required=True)
    args=parser.parse_args()
    try:
        if args.arm:print(json.dumps(arm(args.pod,args.deadline,Path(args.marker))),flush=True)
        elif args.run:run(args.pod,args.deadline,Path(args.marker))
        else:raise ValueError('An explicit guard mode is required')
    except Exception:
        print('Pod-local deadline guard unavailable',file=sys.stderr);raise SystemExit(1)
