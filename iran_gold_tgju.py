"""TGJU gold ticks through the existing fixed Akamai feed, retaining native clocks."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from iran_gold_data import DIGITS, GoldError, MAX_COLLECTION_AGE, SPEC, TEHRAN, UTC, fresh, number, stamp

HOST = '139.162.186.28'
HOST_LINE = HOST + ' ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEnTEGelzvtZGAbgDtRPDBEDpre/9+Gx+ubQC4jJHCrO'
SELECTOR = 'tgju_current'
TRANSPORT = 'akamai-restricted-ssh/tgju_current'
SOURCE = 'https://call4.tgju.org/ajax.json'
MAX_BYTES = 2_000_000
NATIVE_FIELDS = ('p', 'l', 'h', 'ts', 't_en', 't')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def relay_evidence(receipt, verified_at):
    try:
        observed = stamp(receipt['observed_at_utc'])
        http_date = parsedate_to_datetime(receipt['http_date'])
        age = Decimal(str(receipt['http_age_seconds']))
        if isinstance(receipt['http_age_seconds'], bool):
            raise ValueError
    except Exception:
        raise GoldError('TGJU relay freshness evidence is malformed.', 'source') from None
    if (http_date.tzinfo is None or not age.is_finite() or not 0 <= age <= 30 or
            not -5 <= (verified_at-observed).total_seconds() <= 30 or
            not -5 <= (verified_at-http_date).total_seconds() <= 90):
        raise GoldError('TGJU relay response is stale, future-dated or cached too long.', 'stale')


def fetch_payload():
    folder = Path.home()/'.ssh'
    identity, hosts = folder/'kiani_akamai_rates_ed25519', folder/'kiani_akamai_rates_known_hosts'
    for path in (identity, hosts):
        try:
            info = path.lstat()
        except OSError:
            raise GoldError('Existing TGJU feed identity or host pin is unavailable.', 'source') from None
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & 0o022 or path == identity and info.st_mode & 0o077):
            raise GoldError('Existing TGJU feed files have unsafe permissions.', 'configuration')
    if hosts.read_text(encoding='ascii').strip() != HOST_LINE:
        raise GoldError('TGJU feed host pin differs from the reviewed route.', 'configuration')
    command = ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile='+str(hosts),
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'IdentitiesOnly=yes',
        '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes',
        '-o', 'PermitLocalCommand=no', '-o', 'ConnectionAttempts=1',
        '-o', 'ConnectTimeout=5', '-o', 'LogLevel=ERROR',
        '-i', str(identity), 'root@'+HOST, SELECTOR]
    try:
        result = subprocess.run(command, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise GoldError('TGJU fixed-feed connection failed or timed out.', 'source') from None
    if result.returncode or not result.stdout or len(result.stdout) > MAX_BYTES:
        raise GoldError('TGJU fixed-feed request failed or returned an invalid size.', 'source')
    try:
        envelope = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        raise GoldError('TGJU fixed-feed response is not JSON.', 'source') from None
    if (not isinstance(envelope, dict) or envelope.get('ok') is not True or
            type(envelope.get('protocol')) is not int or envelope['protocol'] != 1 or
            envelope.get('selector') != SELECTOR or envelope.get('http_status', 200) != 200 or
            not isinstance(envelope.get('response_headers'), dict)):
        raise GoldError('TGJU fixed-feed response identity changed.', 'source')
    headers = {str(k).lower(): v for k, v in envelope['response_headers'].items()}
    verified = datetime.now(UTC)
    receipt = dict(observed_at_utc=envelope.get('observed_at_utc'),
        http_date=headers.get('date'), http_age_seconds=headers.get('age', '0'),
        verified_at_utc=verified.isoformat())
    relay_evidence(receipt, verified)
    payload = envelope.get('data')
    if not isinstance(payload, dict) or not isinstance(payload.get('current'), dict):
        raise GoldError('TGJU fixed-feed payload lacks its current quote map.', 'source')
    return payload, receipt, hashlib.sha256(result.stdout).hexdigest()


def native_quote(asset, record, now):
    if not isinstance(record, dict) or not all(k in record for k in NATIVE_FIELDS):
        raise GoldError('TGJU exact instrument evidence is incomplete.', 'source')
    raw_date, clock = record['ts'], record['t_en']
    if (not isinstance(raw_date, str) or
            not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', raw_date) or
            not isinstance(clock, str) or not re.fullmatch(r'\d{2}:\d{2}:\d{2}', clock) or
            not isinstance(record['t'], str) or record['t'].translate(DIGITS) != clock):
        raise GoldError('TGJU exposes a date-only or ambiguous original quote clock.', 'stale')
    try:
        # TGJU's native ts/t_en clock is the provider's Tehran clock. Never use
        # the bridge observation time as the market tick's publication time.
        updated = datetime.strptime(raw_date, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TEHRAN)
    except ValueError:
        raise GoldError('TGJU original date/clock is invalid.', 'source') from None
    if updated.strftime('%H:%M:%S') != clock:
        raise GoldError('TGJU original clocks disagree.', 'source')
    fresh(updated, now)
    if any(not isinstance(record[k], str) for k in ('p', 'l', 'h')):
        raise GoldError('TGJU current/range price representation changed.', 'source')
    rial, low, high = (number(record[k]) for k in ('p', 'l', 'h'))
    if not low <= rial <= high or rial != rial.to_integral_value():
        raise GoldError('TGJU current rial quote is outside its native daily range.', 'source')
    toman = rial/10
    if toman != toman.to_integral_value() or not Decimal(SPEC[asset][5]) <= toman <= Decimal(SPEC[asset][6]):
        raise GoldError('TGJU exact conversion or conservative price bounds failed.', 'source')
    return toman, rial, updated.astimezone(UTC)


def validate_quote(asset, quote, now):
    if (quote.get('transport') != TRANSPORT or quote.get('source_url') != SOURCE or
            quote.get('provider_symbol') != SPEC[asset][2] or quote.get('unit') != 'rial' or
            quote.get('source_timezone') != 'Asia/Tehran'):
        raise GoldError('TGJU relay instrument, unit or source identity changed.', 'source')
    record = quote.get('native_record')
    price, rial, updated = native_quote(asset, record, now)
    receipt = quote.get('relay_receipt')
    if not isinstance(receipt, dict):
        raise GoldError('TGJU relay receipt is missing.', 'source')
    verified = stamp(receipt.get('verified_at_utc'))
    relay_evidence(receipt, verified)
    if not -5 <= (now-verified).total_seconds() <= MAX_COLLECTION_AGE:
        raise GoldError('TGJU relay collection evidence expired.', 'stale')
    if (number(quote.get('price')) != price or number(quote.get('original_rial')) != rial or
            stamp(quote.get('updated_at')) != updated or quote.get('record_hash') != digest(record) or
            not re.fullmatch('[0-9a-f]{64}', quote.get('page_hash', ''))):
        raise GoldError('TGJU normalized quote differs from its original evidence.', 'source')
    return price


def parse(payload, receipt, page_hash, now):
    current = payload.get('current') if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        raise GoldError('TGJU original current quote map is unavailable.', 'source')
    quotes, rejected = {}, {}
    for asset, spec in SPEC.items():
        try:
            raw = current.get(spec[2])
            record = {k: raw[k] for k in NATIVE_FIELDS} if isinstance(raw, dict) else None
            price, rial, updated = native_quote(asset, record, now)
            quote = dict(price=str(price), original_rial=str(rial), unit='rial',
                updated_at=updated.isoformat(), source_url=SOURCE, page_hash=page_hash,
                provider_symbol=spec[2], source_timezone='Asia/Tehran', transport=TRANSPORT,
                native_record=record, record_hash=digest(record), relay_receipt=dict(receipt))
            validate_quote(asset, quote, now)
            quotes[asset] = quote
        except (GoldError, KeyError, TypeError, ValueError) as exc:
            rejected[asset] = dict(status='blocked', code=exc.code if isinstance(exc, GoldError) else 'source',
                detail=str(exc) if isinstance(exc, GoldError) else 'Incomplete TGJU native quote evidence.')
    return dict(quotes=quotes, rejected=rejected)


def collect():
    payload, receipt, page_hash = fetch_payload()
    return parse(payload, receipt, page_hash, datetime.now(UTC))
