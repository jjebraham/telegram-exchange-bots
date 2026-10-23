"""Real Ehraz identity checks, strict validation, and server-owned proof reuse."""
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import time
from urllib.parse import urlsplit

import aiohttp
from fastapi import HTTPException

from .ehraz_transport import ALLOWED_PATHS, tunnel_json

logger = logging.getLogger(__name__)
POLICY_VERSION = "ehraz-real-v2"
# Controlled user validation: changing only DOB failed the civil lookup,
# then restoring the correct DOB returned a complete successful comparison.
BIRTH_DATE_POLICY_READY = True
PROOF_TTL_SECONDS = 90
_proof_secret = secrets.token_bytes(32)
_proofs = OrderedDict()
_civil_proofs = OrderedDict()
_translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def digits(value):
    return re.sub(r"[\s/\-\u200c]", "", str(value).translate(_translation))


def national_id(value):
    value = digits(value)
    if not re.fullmatch(r"[0-9]{10}", value):
        raise HTTPException(status_code=400, detail="invalid_national_id")
    return value


def phone(value):
    value = digits(value)
    if value.startswith("+"):
        value = value[1:]
    if value.startswith("0098"):
        value = "0" + value[4:]
    elif value.startswith("98") and len(value) == 12:
        value = "0" + value[2:]
    elif value.startswith("9") and len(value) == 10:
        value = "0" + value
    if not re.fullmatch(r"09[0-9]{9}", value):
        raise HTTPException(status_code=400, detail="invalid_phone_number")
    return value


def normalize_payload(path, payload):
    result = {"nationalCode": national_id(payload.get("nationalCode", ""))}
    if path == "/api/v1/match/national-with-mobile":
        result["mobileNumber"] = phone(payload.get("mobileNumber", ""))
    elif path == "/api/v1/match/card-with-national":
        card = digits(payload.get("cardNumber", ""))
        birth_date = digits(payload.get("birthDate", ""))
        if not re.fullmatch(r"[0-9]{16}", card):
            raise HTTPException(status_code=400, detail="invalid_card_number")
        if not re.fullmatch(r"[0-9]{8}", birth_date):
            raise HTTPException(status_code=400, detail="invalid_date_of_birth")
        result.update(cardNumber=card, birthDate=birth_date)
    else:
        raise HTTPException(status_code=503, detail="verification_configuration_error")
    return result


def normalize_registration(req):
    card = normalize_payload("/api/v1/match/card-with-national", {
        "nationalCode": req.national_id, "cardNumber": req.bank_card_number,
        "birthDate": req.date_of_birth,
    })
    updates = {"national_id": card["nationalCode"],
               "bank_card_number": card["cardNumber"],
               "date_of_birth": card["birthDate"],
               "phone_number": phone(req.phone_number),
               "first_name": req.first_name.strip(),
               "last_name": req.last_name.strip()}
    updates["father_name"] = clean_name(req.father_name)
    if not updates["first_name"] or not updates["last_name"]:
        raise HTTPException(status_code=400, detail="invalid_name")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="invalid_password")
    return (req.model_copy(update=updates) if hasattr(req, "model_copy")
            else req.copy(update=updates))


def clean_name(value):
    value = " ".join(str(value).strip().split()).translate(str.maketrans({"ي": "ی", "ك": "ک"}))
    if not value or len(value) > 80:
        raise HTTPException(status_code=400, detail="invalid_identity_name")
    return value


def require_birth_date_policy():
    if not BIRTH_DATE_POLICY_READY:
        raise HTTPException(status_code=503, detail="birth_date_verification_unavailable")


def check_registration_conflicts(connection, req):
    for column, value, detail in (
        ("phone_number", req.phone_number, "already_registered_phone"),
        ("national_id", req.national_id, "already_registered_national_id"),
        ("bank_card_number", req.bank_card_number, "already_registered_card"),
    ):
        if connection.execute("SELECT id FROM users WHERE " + column + " = ?", (value,)).fetchone():
            raise HTTPException(status_code=409, detail=detail)


def _cache_key(path, payload, token):
    message = json.dumps([path, payload, token], sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_proof_secret, message, hashlib.sha256).hexdigest()


async def real_match(url, payload, timeout_seconds=12):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "ehraz.io"
            or parsed.path not in ALLOWED_PATHS or parsed.query or parsed.fragment):
        raise HTTPException(status_code=503, detail="verification_configuration_error")
    payload = normalize_payload(parsed.path, payload)
    token = os.getenv("EHRAZ_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="ehraz_not_configured")

    now = time.monotonic()
    for key, (expires_at, _) in list(_proofs.items()):
        if expires_at <= now:
            _proofs.pop(key, None)
    key = _cache_key(parsed.path, payload, token)
    if key in _proofs:
        _, proof = _proofs[key]
        logger.info("EHRAZ verified proof reused path=%s", parsed.path)
        return dict(proof)

    try:
        status, data = await tunnel_json("POST", parsed.path, token, payload,
                                        timeout_seconds=timeout_seconds)
    except (aiohttp.ClientError, TimeoutError, OSError) as error:
        logger.warning("EHRAZ transport failure path=%s class=%s", parsed.path, type(error).__name__)
        raise HTTPException(status_code=503, detail="verification_service_unavailable") from None

    code = data.get("code")
    valid = (status == 200 and type(data.get("matched")) is bool
             and (code is None or str(code) == "0"))
    if not valid:
        safe_code = str(code) if isinstance(code, (str, int)) and str(code).isdigit() else "unknown"
        logger.warning("EHRAZ rejected path=%s status=%s code=%s", parsed.path, status, safe_code)
        if status in (401, 403):
            detail = "ehraz_auth_failed"
        elif str(code) == "6":
            detail = "ehraz_insufficient_credit"
        elif status == 200 and (code is None or str(code) == "0"):
            # The provider replied but did not supply a valid match result.
            # This can follow invalid input; do not label it a transport outage
            # or convert it into a definite mismatch without an actual boolean.
            detail = "ownership_lookup_unconfirmed"
        else:
            detail = "verification_service_unavailable"
        raise HTTPException(status_code=503, detail=detail)

    proof = {"matched": data["matched"],
             "verified_at": datetime.now(timezone.utc).isoformat(),
             "provider": "ehraz", "policy_version": POLICY_VERSION}
    logger.info("EHRAZ completed path=%s route=akamai_tls matched=%s", parsed.path, proof["matched"])
    if proof["matched"] is True:
        if len(_proofs) >= 512:
            _proofs.popitem(last=False)
        _proofs[key] = (time.monotonic() + PROOF_TTL_SECONDS, dict(proof))
    return proof


async def civil_match(payload):
    """Civil registry comparison; birth-date behavior must pass release validation."""
    path = "/api/v1/info/identity-similarity"
    first_name = clean_name(payload.get("firstName", ""))
    last_name = clean_name(payload.get("lastName", ""))
    father_name = clean_name(payload.get("fatherName", ""))
    birth_date = digits(payload.get("birthDate", ""))
    if not re.fullmatch(r"[0-9]{8}", birth_date):
        raise HTTPException(status_code=400, detail="invalid_date_of_birth")
    payload = {"nationalCode": national_id(payload.get("nationalCode", "")),
               "birthDate": birth_date, "firstName": first_name,
               "lastName": last_name, "fullName": first_name + " " + last_name,
               "fatherName": father_name}
    token = os.getenv("EHRAZ_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="ehraz_not_configured")
    now = time.monotonic()
    for key, (expires, _) in list(_civil_proofs.items()):
        if expires <= now:
            _civil_proofs.pop(key, None)
    key = _cache_key(path, payload, token)
    if key in _civil_proofs:
        return dict(_civil_proofs[key][1])
    try:
        status, data = await tunnel_json("POST", path, token, payload, timeout_seconds=15)
    except (aiohttp.ClientError, TimeoutError, OSError) as error:
        logger.warning("EHRAZ civil transport class=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="verification_service_unavailable") from None
    fields = ("firstNameSimilarityPercentage", "lastNameSimilarityPercentage",
              "fullNameSimilarityPercentage", "fatherNameSimilarityPercentage")
    percentages = []
    for field in fields:
        value = data.get(field)
        if isinstance(value, str) and re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]+)?", value):
            value = float(value)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            percentages = []
            break
        percentages.append(value)
    code = data.get("code")
    if status != 200 or (code is not None and str(code) != "0") or len(percentages) != 4:
        # Types only; no response text or personal values are recorded.
        safe_types = {k: type(v).__name__ for k, v in list(data.items())[:16]
                      if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,49}", k)}
        safe_code = str(code) if isinstance(code, (str, int)) and str(code).isdigit() else "unknown"
        logger.warning("EHRAZ civil unavailable status=%s code=%s schema=%s", status, safe_code, json.dumps(safe_types))
        detail = ("ehraz_insufficient_credit" if str(code) == "6" else
                  "identity_lookup_unconfirmed" if status == 200 and (code is None or str(code) == "0")
                  else "verification_service_unavailable")
        raise HTTPException(status_code=503, detail=detail)
    matched = all(value == 100 for value in percentages)
    # The validated civil-registry lookup uses the exact submitted DOB together
    # with national ID. Positive proof additionally requires all four matches;
    # transport/core errors and incomplete results never create a proof.
    proof = {"matched": matched,
             "birth_date_verified": matched and BIRTH_DATE_POLICY_READY,
             "birth_date_verification_basis": "ehraz_civil_lookup_with_birth_date",
             "verified_at": datetime.now(timezone.utc).isoformat(),
             "provider": "ehraz", "policy_version": POLICY_VERSION}
    logger.info("EHRAZ civil completed matched=%s policy_ready=%s", matched, BIRTH_DATE_POLICY_READY)
    if matched:
        if len(_civil_proofs) >= 256:
            _civil_proofs.popitem(last=False)
        _civil_proofs[key] = (time.monotonic() + PROOF_TTL_SECONDS, dict(proof))
    return proof


def ensure_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS registration_identity_checks (
        user_id INTEGER PRIMARY KEY,
        provider TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        phone_checked_at TEXT NOT NULL,
        card_checked_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    columns = {row[1] for row in connection.execute('PRAGMA table_info(registration_identity_checks)')}
    if 'identity_checked_at' not in columns:
        connection.execute('ALTER TABLE registration_identity_checks ADD COLUMN identity_checked_at TEXT')
    if 'birth_date_verified' not in columns:
        connection.execute('ALTER TABLE registration_identity_checks ADD COLUMN birth_date_verified INTEGER NOT NULL DEFAULT 0')


def record_registration(connection, user_id, mobile_proof, card_proof, identity_proof):
    require_birth_date_policy()
    if (identity_proof.get("birth_date_verified") is not True or
            identity_proof.get("birth_date_verification_basis") != "ehraz_civil_lookup_with_birth_date"):
        raise HTTPException(status_code=503, detail="birth_date_verification_unavailable")
    if any(proof.get("matched") is not True for proof in (mobile_proof, card_proof, identity_proof)):
        raise HTTPException(status_code=503, detail="verification_required")
    ensure_schema(connection)
    now = datetime.now(timezone.utc).isoformat()
    connection.execute('''INSERT INTO registration_identity_checks
        (user_id, provider, policy_version, phone_checked_at, card_checked_at, created_at,
         identity_checked_at, birth_date_verified)
        VALUES (?, 'ehraz', ?, ?, ?, ?, ?, 1)''',
        (user_id, POLICY_VERSION, mobile_proof["verified_at"], card_proof["verified_at"], now,
         identity_proof["verified_at"]))
    connection.execute("INSERT INTO admin_logs(action,details) VALUES (?,?)", (
        "registration_identity_verified",
        json.dumps({"user_id": user_id, "provider": "ehraz", "policy_version": POLICY_VERSION,
                    "phone_checked_at": mobile_proof["verified_at"],
                    "card_checked_at": card_proof["verified_at"],
                    "identity_checked_at": identity_proof["verified_at"],
                    "birth_date_verified": True}),
    ))
