"""Bounded, single-use SMS password reset; no plaintext OTP storage or logging."""
import asyncio
import hashlib
import hmac
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import time

from fastapi import HTTPException
from .database import get_db
from . import sms_gateway

logger=logging.getLogger(__name__)
LIFETIME=600
RESEND_SECONDS=60
MAX_ATTEMPTS=5
MAX_SENDS=2
ALTERNATE_AFTER=60
DELIVERY_POLL_SECONDS=15
DELIVERY_POLL_COUNT=5
PEPPER=Path('/home/kianirad2020/.local/state/kiani-sms-reset/pepper')


def initialize():
    PEPPER.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        fd=os.open(PEPPER,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd,'wb') as stream:stream.write(secrets.token_bytes(32))
    info=PEPPER.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise RuntimeError('unsafe_sms_reset_state')
    if len(PEPPER.read_bytes())!=32:
        raise RuntimeError('invalid_sms_reset_state')
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS sms_password_reset_challenges (
            id TEXT PRIMARY KEY, phone_number TEXT NOT NULL, ip_hash TEXT NOT NULL,
            code_hash TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            sent_at INTEGER, provider_reference TEXT)''')
        conn.execute('CREATE INDEX IF NOT EXISTS sms_reset_phone_time ON sms_password_reset_challenges(phone_number,created_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS sms_reset_ip_time ON sms_password_reset_challenges(ip_hash,created_at)')
        conn.execute('''CREATE TABLE IF NOT EXISTS sms_password_reset_deliveries (
            challenge_id TEXT NOT NULL, attempt INTEGER NOT NULL,
            client_reference TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
            message_id TEXT, provider_status INTEGER,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            PRIMARY KEY (challenge_id, attempt))''')


def normalize_phone(value):
    if not isinstance(value,str) or len(value)>32:
        raise HTTPException(status_code=400,detail='invalid_phone')
    digits=''.join(str(int(c)) if c.isdecimal() else c for c in str(value))
    digits=re.sub(r'[\s+()-]','',digits)
    if digits.startswith('0098'):digits='0'+digits[4:]
    elif digits.startswith('98'):digits='0'+digits[2:]
    if not re.fullmatch(r'09[0-9]{9}',digits):
        raise HTTPException(status_code=400,detail='invalid_phone')
    return digits


def signature(challenge,phone,code):
    return hmac.new(PEPPER.read_bytes(),(challenge+':'+phone+':'+code).encode(),hashlib.sha256).hexdigest()


def begin(phone,ip):
    if not sms_gateway.configured():raise HTTPException(status_code=503,detail='sms_unavailable')
    phone=normalize_phone(phone)
    now=int(time.time())
    challenge=secrets.token_hex(16)
    code=f'{secrets.randbelow(1000000):06d}'
    ip_hash=hashlib.sha256(str(ip).encode()).hexdigest()
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        last=conn.execute('SELECT MAX(created_at) FROM sms_password_reset_challenges WHERE phone_number=?',(phone,)).fetchone()[0]
        retry=max(0,RESEND_SECONDS-(now-last)) if last is not None else 0
        per_phone=conn.execute('SELECT COUNT(*) FROM sms_password_reset_challenges WHERE phone_number=? AND created_at>=?',(phone,now-3600)).fetchone()[0]
        per_ip=conn.execute('SELECT COUNT(*) FROM sms_password_reset_challenges WHERE ip_hash=? AND created_at>=?',(ip_hash,now-3600)).fetchone()[0]
        total=conn.execute('SELECT COUNT(*) FROM sms_password_reset_challenges WHERE created_at>=?',(now-3600,)).fetchone()[0]
        if retry or per_phone>=5 or per_ip>=60 or total>=300:
            wait=retry or 3600
            raise HTTPException(status_code=429,detail='reset_rate_limited',headers={'Retry-After':str(wait)})
        user=conn.execute('SELECT id FROM users WHERE phone_number=?',(phone,)).fetchone()
        # A newer request invalidates pending retries and codes for this number.
        conn.execute("UPDATE sms_password_reset_challenges SET state='superseded' WHERE phone_number=? AND state IN ('pending','sent')",(phone,))
        conn.execute('''INSERT INTO sms_password_reset_challenges
            (id,phone_number,ip_hash,code_hash,state,created_at,expires_at) VALUES (?,?,?,?,?,?,?)''',
            (challenge,phone,ip_hash,signature(challenge,phone,code),'pending' if user else 'unknown',now,now+LIFETIME))
    response={'status':'accepted','challenge_id':challenge,'expires_in':LIFETIME,'retry_after':RESEND_SECONDS}
    return response,(phone,code,challenge) if user else None


def active_delivery(challenge):
    with get_db() as conn:
        row=conn.execute('SELECT state,expires_at,attempts FROM sms_password_reset_challenges WHERE id=?',(challenge,)).fetchone()
        return bool(row and row['state'] in ('pending','sent') and row['expires_at']>int(time.time())
                    and row['attempts']<MAX_ATTEMPTS)


def claim_delivery(challenge,attempt,reference):
    now=int(time.time())
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT state,expires_at,attempts FROM sms_password_reset_challenges WHERE id=?',(challenge,)).fetchone()
        if (not row or row['state'] not in ('pending','sent') or row['expires_at']<=now
                or row['attempts']>=MAX_ATTEMPTS or not 1<=attempt<=MAX_SENDS):return False
        if attempt==2:
            prior=conn.execute('SELECT state FROM sms_password_reset_deliveries WHERE challenge_id=? AND attempt=1',(challenge,)).fetchone()
            if not prior or prior['state']!='delivery_failed':return False
        cursor=conn.execute('''INSERT OR IGNORE INTO sms_password_reset_deliveries
            (challenge_id,attempt,client_reference,state,created_at,updated_at) VALUES (?,?,?,'sending',?,?)''',
            (challenge,attempt,reference,now,now))
        return cursor.rowcount==1


def finish_send(challenge,attempt,result):
    # Accept the verified explicit-sender transport. The previous OTP contract
    # remains compatible while the two servers are updated or rolled back.
    verified_transport=(result.get('method')=='SendSingleSMS' and result.get('sender_line')=='30005088'
                        and isinstance(result.get('source_template'),str))
    accepted=result.get('ok') is True and (verified_transport or result.get('method')=='SendOtpSMS') and bool(result.get('message_id'))
    now=int(time.time())
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''UPDATE sms_password_reset_deliveries
            SET state=?,message_id=?,updated_at=? WHERE challenge_id=? AND attempt=? AND state='sending' ''',
            ('accepted' if accepted else 'send_unconfirmed',result.get('message_id') if accepted else None,now,challenge,attempt))
        row=conn.execute('SELECT state,expires_at,attempts FROM sms_password_reset_challenges WHERE id=?',(challenge,)).fetchone()
        active=bool(row and row['state'] in ('pending','sent') and row['expires_at']>now and row['attempts']<MAX_ATTEMPTS)
        if active:
            conn.execute('''UPDATE sms_password_reset_challenges SET state=?,sent_at=?,provider_reference=? WHERE id=?''',
                ('sent' if accepted else 'failed',now if accepted else None,result.get('message_id') if accepted else None,challenge))
        import json
        conn.execute('INSERT INTO admin_logs(action,details) VALUES (?,?)',('password_reset_sms',json.dumps({
            'challenge':challenge,'attempt':attempt,'accepted':accepted,'provider':'ghasedak.me',
            'method':str(result.get('method','SendSingleSMS'))[:32],
            'sender_line':result.get('sender_line'),'source_template':result.get('source_template'),
            'reason':str(result.get('error','accepted'))[:64],
            'provider_code':result.get('provider_code'),'message_id':result.get('message_id') if accepted else None})))
    return accepted and active


def record_delivery_status(challenge,attempt,status):
    now=int(time.time())
    state='delivered' if status==5 else 'delivery_failed' if status in (1,2,4,6) else 'accepted'
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('''UPDATE sms_password_reset_deliveries SET state=?,provider_status=?,updated_at=?
            WHERE challenge_id=? AND attempt=? AND state IN ('accepted','delivery_failed','delivered')''',
            (state,status,now,challenge,attempt))
        # Pending operator reports remain usable if a code arrives later.
        # Confirmed failures wait for the one alternate attempt or expire.
        if status in (1,2,4,6):
            next_state='pending' if status!=1 and attempt<MAX_SENDS else 'failed'
            conn.execute("UPDATE sms_password_reset_challenges SET state=? WHERE id=? AND state='sent'",(next_state,challenge))
        if state!='accepted':
            import json
            conn.execute('INSERT INTO admin_logs(action,details) VALUES (?,?)',('password_reset_sms_delivery',json.dumps({
                'challenge':challenge,'attempt':attempt,'provider_status':status,'delivery_state':state})))


async def deliver(phone,code,challenge):
    # Only keep the plaintext code in this task's memory; no persistent queue.
    # A process restart, newer request, successful reset or lock cancels retries.
    for attempt in range(1,MAX_SENDS+1):
        reference=challenge if attempt==1 else hashlib.sha256((challenge+':2').encode()).hexdigest()[:32]
        if not claim_delivery(challenge,attempt,reference):return
        started=time.monotonic()
        try:
            result=await sms_gateway.call_relay('send_otp',phone=phone,otp=code,reference=reference)
        except Exception:
            result={'ok':False,'error':'sms_unavailable'}
        if not finish_send(challenge,attempt,result):
            # An ambiguous transport response may already have sent a message.
            # Never issue a blind duplicate send.
            return
        retry=False
        for _ in range(DELIVERY_POLL_COUNT):
            await asyncio.sleep(DELIVERY_POLL_SECONDS)
            if not active_delivery(challenge):return
            try:
                report=await sms_gateway.call_relay('message_status',message_id=result['message_id'])
            except Exception:
                continue
            items=report.get('statuses') if report.get('ok') is True else None
            if not isinstance(items,list) or len(items)!=1:continue
            item=items[0]
            if str(item.get('messageId'))!=result['message_id'] or item.get('client_reference')!=reference:continue
            status=item.get('status')
            if isinstance(status,bool) or not isinstance(status,int) or not 0<=status<=8:continue
            record_delivery_status(challenge,attempt,status)
            if status==5:return
            if status in (1,2,4,6):
                retry=status!=1 and attempt<MAX_SENDS
                break
        if not retry:return
        delay=max(0,ALTERNATE_AFTER-(time.monotonic()-started))
        if delay:await asyncio.sleep(delay)
        if time.monotonic()-started>105:return
        if not active_delivery(challenge):return


def complete(phone,challenge,code,new_password,hash_password):
    phone=normalize_phone(phone)
    if not isinstance(code,str) or len(code)>6:
        raise HTTPException(status_code=400,detail='invalid_or_expired_code')
    code=''.join(str(int(c)) if c.isdecimal() else c for c in str(code))
    if not isinstance(new_password,str) or not 8<=len(new_password)<=128:
        raise HTTPException(status_code=400,detail='password_length')
    if not re.fullmatch(r'[a-f0-9]{32}',challenge or '') or not re.fullmatch(r'[0-9]{6}',code):
        raise HTTPException(status_code=400,detail='invalid_or_expired_code')
    now=int(time.time())
    failure=False
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM sms_password_reset_challenges WHERE id=? AND phone_number=?',(challenge,phone)).fetchone()
        if not row or row['state']!='sent' or row['expires_at']<=now or row['attempts']>=MAX_ATTEMPTS:
            failure=True
        elif not hmac.compare_digest(row['code_hash'],signature(challenge,phone,code)):
            attempts=row['attempts']+1
            conn.execute('UPDATE sms_password_reset_challenges SET attempts=?,state=? WHERE id=?',
                         (attempts,'locked' if attempts>=MAX_ATTEMPTS else 'sent',challenge))
            failure=True
        else:
            cursor=conn.execute('UPDATE users SET password_hash=? WHERE phone_number=?',(hash_password(new_password),phone))
            if cursor.rowcount!=1:
                failure=True
            conn.execute("UPDATE sms_password_reset_challenges SET state='used' WHERE phone_number=? AND state IN ('sent','pending')",(phone,))
    # Raise after committing failed attempts so retries cannot reset their limit.
    if failure:raise HTTPException(status_code=400,detail='invalid_or_expired_code')
    return {'status':'success'}
