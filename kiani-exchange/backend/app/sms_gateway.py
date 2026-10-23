"""Ghasedak access through the dedicated, fixed-operation Akamai SSH relay."""
import asyncio
import json
import os
from pathlib import Path
import re
import stat

HOST = '139.162.186.28'
IDENTITY = Path('/home/kianirad2020/.ssh/kiani_ghasedak_ed25519')
KNOWN_HOSTS = Path('/home/kianirad2020/.ssh/kiani_akamai_rates_known_hosts')


def configuration():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env',override=False)
    key = os.getenv('GHASEDAK_API_KEY','').strip()
    template = os.getenv('GHASEDAK_TEMPLATE_NAME','').strip()
    parameter = os.getenv('GHASEDAK_OTP_PARAMETER','').strip()
    if not key or not template or not parameter:
        raise RuntimeError('sms_not_configured')
    return key,template,parameter


def configured():
    try:
        configuration()
        for path in (IDENTITY,KNOWN_HOSTS):
            info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():return False
        return not bool(IDENTITY.stat().st_mode & 0o077)
    except (OSError,RuntimeError):
        return False


async def call_relay(action, **values):
    key,template,parameter=configuration()
    if action not in {'account_info','template_info','send_otp','message_status'}:
        raise ValueError('unsupported_sms_operation')
    if not configured():raise RuntimeError('sms_not_configured')
    payload={'action':action,'api_key':key,'template':template,'parameter':parameter,**values}
    command=['ssh','-F','/dev/null','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','UserKnownHostsFile='+str(KNOWN_HOSTS),'-o','GlobalKnownHostsFile=/dev/null',
        '-o','IdentitiesOnly=yes','-o','ConnectTimeout=4','-i',str(IDENTITY),'root@'+HOST,'ghasedak-v1']
    process=await asyncio.create_subprocess_exec(*command,stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        stdout,_stderr=await asyncio.wait_for(process.communicate(json.dumps(payload).encode()),
                                             timeout=32 if action=='send_otp' else 22)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return {'ok':False,'error':'sms_transport_timeout'}
    if process.returncode or len(stdout)>8192:
        return {'ok':False,'error':'sms_transport_unavailable'}
    try:result=json.loads(stdout)
    except (ValueError,UnicodeError):return {'ok':False,'error':'invalid_sms_response'}
    if not isinstance(result,dict):return {'ok':False,'error':'invalid_sms_response'}
    if result.get('ok') is True:
        if result.get('protocol')!=1 or result.get('provider')!='ghasedak.me' or result.get('action')!=action:
            return {'ok':False,'error':'invalid_sms_response'}
    return result
