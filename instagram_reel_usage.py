"""Private per-Trial-Reel API usage accounting; contains no prompts or secrets."""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
import functools
import os
from pathlib import Path
import sqlite3
import time
import uuid
from decimal import Decimal

STATE = Path.home()/'.local/state/kiani-instagram-trial-reels'
DB = STATE/'deepseek-usage.sqlite3'
current = contextvars.ContextVar('reel_usage', default=None)

@contextmanager
def _connection():
    if STATE.is_symlink() or DB.is_symlink():
        raise RuntimeError('Unsafe usage state path')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE,0o700)
    con=sqlite3.connect(DB,timeout=10)
    os.chmod(DB,0o600)
    con.executescript('''CREATE TABLE IF NOT EXISTS runs(
      id TEXT PRIMARY KEY, origin TEXT NOT NULL, started REAL NOT NULL,
      ended REAL, outcome TEXT, error_type TEXT);
    CREATE TABLE IF NOT EXISTS calls(
      id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, time REAL NOT NULL, model TEXT,
      prompt_tokens INTEGER, cached_tokens INTEGER, uncached_tokens INTEGER,
      output_tokens INTEGER, total_tokens INTEGER, usage_known INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS notices(run_id TEXT NOT NULL, admin_id TEXT NOT NULL,
      sent_at REAL, PRIMARY KEY(run_id,admin_id));
    ''')
    if 'reference' not in {r[1] for r in con.execute('PRAGMA table_info(runs)')}:
        con.execute('ALTER TABLE runs ADD COLUMN reference TEXT')
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()

def _count(usage, name):
    value=usage.get(name)
    return value if type(value) is int and 0 <= value <= 100000000 else None

def record_envelope(body, envelope):
    run=current.get()
    if run is None: return
    u=envelope.get('usage') if isinstance(envelope,dict) else None
    u=u if isinstance(u,dict) else {}
    values=[_count(u,k) for k in ('prompt_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens','total_tokens')]
    model=body.get('model') if isinstance(body,dict) else None
    model=model[:100] if isinstance(model,str) else None
    complete=all(v is not None for v in values)
    if complete:
        complete=values[0]==values[1]+values[2] and values[4]==values[0]+values[3]
    try:
        with _connection() as con:
            con.execute('INSERT INTO calls(run_id,time,model,prompt_tokens,cached_tokens,uncached_tokens,output_tokens,total_tokens,usage_known) VALUES(?,?,?,?,?,?,?,?,?)',
                        (run,time.time(),model,*values,int(complete)))
    except (OSError,sqlite3.Error,RuntimeError):
        print('Trial Reel usage could not be recorded; publication continues.',flush=True)

def tracked(origin):
    def decorate(function):
        @functools.wraps(function)
        def wrapper(*args,**kwargs):
            if current.get() is not None: return function(*args,**kwargs)
            run=uuid.uuid4().hex
            try:
                with _connection() as con: con.execute('INSERT INTO runs(id,origin,started) VALUES(?,?,?)',(run,origin,time.time()))
            except (OSError,sqlite3.Error,RuntimeError):
                print('Trial Reel usage tracking unavailable.',flush=True)
                return function(*args,**kwargs)
            token=current.set(run); status='prepared'; error=None; reference=None
            try:
                result=function(*args,**kwargs)
                if result is None: status='no_result'
                elif isinstance(result,str): reference=result[:100]
                elif isinstance(result,tuple) and len(result)>=3 and isinstance(result[2],str): reference=result[2][:100]
                return result
            except BaseException as exc:
                status='failed'; error=type(exc).__name__[:100]
                raise
            finally:
                current.reset(token)
                try:
                    with _connection() as con: con.execute('UPDATE runs SET ended=?,outcome=?,error_type=?,reference=? WHERE id=?',(time.time(),status,error,reference,run))
                except (OSError,sqlite3.Error,RuntimeError):
                    print('Trial Reel usage outcome unavailable.',flush=True)
        return wrapper
    return decorate

def estimate(calls, now=None):
    # Published DeepSeek Flash prices, 2026-10-29, USD per million tokens.
    # Peak/off-peak and public holidays vary; report a range, not a bill.
    # Expire rates rather than quietly use outdated prices.
    if now is None: now=time.time()
    if now >= 1795910400: return None
    low=Decimal(0); high=Decimal(0)
    for model,cached,uncached,output,known in calls:
        if not known or model not in ('deepseek-flash','deepseek-v4-flash','deepseek-v4-flash-vision-exp'):
            return None
        value=(Decimal(cached)*Decimal('.003')+Decimal(uncached)*Decimal('.15')+Decimal(output)*Decimal('.6'))/Decimal(1000000)
        low+=value; high+=value*2
    return low,high

def deliver_notices(token, admins, send):
    """Deliver private cost notices for completed preparation attempts."""
    try:
        with _connection() as con:
            runs=con.execute('SELECT id,origin,outcome FROM runs WHERE ended IS NOT NULL ORDER BY started DESC LIMIT 100').fetchall()
            for run,origin,outcome in runs:
                for admin in admins:
                    con.execute('INSERT OR IGNORE INTO notices(run_id,admin_id) VALUES(?,?)',(run,str(admin)))
            pending=con.execute('''SELECT n.run_id,n.admin_id,r.origin,r.outcome,r.reference FROM notices n JOIN runs r ON r.id=n.run_id
                WHERE n.sent_at IS NULL ORDER BY r.started LIMIT 20''').fetchall()
        for run,admin,origin,outcome,reference in pending:
            with _connection() as con:
                calls=con.execute('SELECT model,cached_tokens,uncached_tokens,output_tokens,usage_known FROM calls WHERE run_id=?',(run,)).fetchall()
            estimate_range=estimate(calls)
            if estimate_range is None:
                amount='نامشخص؛ اطلاعات مصرف یا قیمت معتبر کامل نیست.'
            elif not calls:
                amount='۰ دلار؛ هیچ درخواست DeepSeek در این تلاش ثبت نشد.'
            else:
                amount=f'حدود ${estimate_range[0]:.6f} تا ${estimate_range[1]:.6f} (تخمین؛ تعرفه ممکن است تغییر کند).'
            label='دستی' if origin in {'admin_link','admin_direct'} else 'خودکار'
            msg=f'هزینه تخمینی DeepSeek برای تلاش ریل {label}: {amount}\nدرخواست‌های مدل: {len(calls)} | وضعیت آماده‌سازی: {outcome}\nشناسه ریل: {reference or "هنوز ایجاد نشده"}\nاین مبلغ شامل هزینه سرور نیست و صورتحساب نهایی محسوب نمی‌شود.'
            try: send(token,admin,msg)
            except Exception: continue
            with _connection() as con:
                con.execute('UPDATE notices SET sent_at=? WHERE run_id=? AND admin_id=?',(time.time(),run,admin))
    except (OSError,sqlite3.Error,RuntimeError):
        print('Trial Reel cost notice deferred.',flush=True)


