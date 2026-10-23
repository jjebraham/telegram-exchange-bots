"""KYC review using the production application's existing admin sessions."""

import hashlib
import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..admin_auth import optional_admin_session
from ..database import get_db
from . import kyc as kyc_api

router = APIRouter()
RETAINED_METADATA = kyc_api.BASE_DIR / "kyc_retained_metadata.json"


class KycDecisionRequest(BaseModel):
    reason: str | None = None
    level3_photo_reviewed: bool = False


def require_review_session(session=Depends(optional_admin_session)):
    if session is None:
        raise HTTPException(status_code=401, detail="admin_session_required")
    if session["role"] not in {"admin", "support"}:
        raise HTTPException(status_code=403, detail="kyc_review_permission_required")
    return session


def require_decision_session(session=Depends(require_review_session)):
    if session["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin_role_required")
    return session


def _audit(action: str, details: dict) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO admin_logs (action, details) VALUES (?, ?)",
            (action, json.dumps(details, ensure_ascii=False)),
        )


def _mask_phone(value) -> str:
    value = str(value or "")
    return f"{value[:4]}***{value[-4:]}" if len(value) >= 8 else "***"


def _mask_national_id(value) -> str:
    value = str(value or "")
    return f"***{value[-4:]}" if value else "***"


def _private_file(value: str | None) -> Path:
    if not value:
        raise HTTPException(status_code=404, detail="file_not_found")
    path = Path(value).resolve()
    if kyc_api.UPLOAD_ROOT.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="file_not_found")
    return path


def _file_response(path: Path) -> FileResponse:
    return FileResponse(
        str(path),
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _uploaded_files():
    root = kyc_api.UPLOAD_ROOT.resolve()
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if root not in resolved.parents or not resolved.is_file():
            continue
        relative = path.relative_to(root)
        if len(relative.parts) != 2 or not relative.parts[0].isdigit():
            continue
        file_id = hashlib.sha256(relative.as_posix().encode()).hexdigest()
        yield file_id, int(relative.parts[0]), resolved


@router.get("/admin/kyc/submissions")
async def list_submissions(status: str | None = None, session=Depends(require_review_session)):
    if status and status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=400, detail="invalid_kyc_status")
    kyc_api._ensure_schema()
    query = """SELECT k.*, u.first_name, u.last_name, u.phone_number,
                      u.national_id, u.verification_level
               FROM kyc_submissions k JOIN users u ON u.id = k.user_id"""
    params = ()
    if status:
        query += " WHERE k.status = ?"
        params = (status,)
    query += " ORDER BY k.id DESC LIMIT 300"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        result.append({
            **kyc_api._submission_dict(row),
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "phone_number": _mask_phone(row["phone_number"]),
            "national_id": _mask_national_id(row["national_id"]),
            "verification_level": int(row["verification_level"] or 1),
        })
    return {"submissions": result}


@router.get("/admin/kyc/submissions/{submission_id}/file/{kind}")
async def submission_file(submission_id: int, kind: str, session=Depends(require_review_session)):
    if kind not in {"front", "back", "selfie"}:
        raise HTTPException(status_code=400, detail="invalid_file_kind")
    kyc_api._ensure_schema()
    column = {"front": "front_path", "back": "back_path", "selfie": "selfie_path"}[kind]
    with get_db() as conn:
        row = conn.execute(
            f"SELECT user_id, {column} AS path FROM kyc_submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="file_not_found")
    path = _private_file(row["path"])
    _audit("view_kyc_document", {"submission_id": submission_id, "kind": kind, "admin": session["username"]})
    return _file_response(path)


def _validate_documents(submission):
    kinds = ["front", "back"] if submission["level"] == 2 else ["selfie"]
    for kind in kinds:
        path = _private_file(submission[f"{kind}_path"])
        digest = submission[f"{kind}_sha256"]
        if digest and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise HTTPException(status_code=409, detail="document_hash_mismatch")


@router.post("/admin/kyc/submissions/{submission_id}/approve")
async def approve_submission(submission_id: int, req: KycDecisionRequest, session=Depends(require_decision_session)):
    kyc_api._ensure_schema()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        submission = conn.execute("SELECT * FROM kyc_submissions WHERE id = ?", (submission_id,)).fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="submission_not_found")
        if submission["status"] != "pending":
            raise HTTPException(status_code=409, detail="submission_already_reviewed")
        level = int(submission["level"])
        if level not in {2, 3}:
            raise HTTPException(status_code=400, detail="invalid_kyc_level")
        user = conn.execute("SELECT verification_level FROM users WHERE id = ?", (submission["user_id"],)).fetchone()
        if not user:
            raise HTTPException(status_code=409, detail="account_not_present")
        if level == 3 and int(user["verification_level"] or 1) < 2:
            raise HTTPException(status_code=409, detail="level2_required")
        if level == 3 and not req.level3_photo_reviewed:
            raise HTTPException(status_code=400, detail="level3_photo_review_confirmation_required")
        _validate_documents(submission)
        conn.execute(
            """UPDATE kyc_submissions SET status='approved', rejection_reason=NULL,
                      reviewed_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (session["username"], submission_id),
        )
        conn.execute(
            "UPDATE users SET verification_level=MAX(COALESCE(verification_level,1),?), kyc_status='Approved' WHERE id=?",
            (level, submission["user_id"]),
        )
    _audit("kyc_approved", {
        "submission_id": submission_id,
        "level": level,
        "admin": session["username"],
        "level3_photo_reviewed": req.level3_photo_reviewed if level == 3 else None,
        "declaration_version": submission["declaration_version"] if level == 3 else None,
    })
    await kyc_api._send_admin_text(f"KYC level {level} | Submission #{submission_id} => approved")
    return {"status": "approved", "verification_level": level}


@router.post("/admin/kyc/submissions/{submission_id}/reject")
async def reject_submission(submission_id: int, req: KycDecisionRequest, session=Depends(require_decision_session)):
    reason = (req.reason or "مدارک قابل تایید نیست؛ لطفاً دوباره بارگذاری کنید.").strip()
    if not reason or len(reason) > 2000:
        raise HTTPException(status_code=400, detail="invalid_rejection_reason")
    kyc_api._ensure_schema()
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        submission = conn.execute("SELECT * FROM kyc_submissions WHERE id=?", (submission_id,)).fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="submission_not_found")
        if submission["status"] != "pending":
            raise HTTPException(status_code=409, detail="submission_already_reviewed")
        conn.execute(
            """UPDATE kyc_submissions SET status='rejected', rejection_reason=?,
                      reviewed_by=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (reason, session["username"], submission_id),
        )
    _audit("kyc_rejected", {"submission_id": submission_id, "admin": session["username"]})
    await kyc_api._send_admin_text(f"KYC Submission #{submission_id} => rejected")
    return {"status": "rejected", "reason": reason}


@router.get("/admin/kyc/retained-files")
async def retained_files(session=Depends(require_review_session)):
    """Expose retained documents without creating accounts or verification decisions."""
    kyc_api._ensure_schema()
    historical = {}
    if RETAINED_METADATA.is_file():
        historical = json.loads(RETAINED_METADATA.read_text()).get("groups", {})
    with get_db() as conn:
        accounts = {int(row["id"]): dict(row) for row in conn.execute(
            "SELECT id, first_name, last_name, phone_number FROM users"
        )}
        referenced = {str(Path(row[0]).resolve()) for field in ["front_path", "back_path", "selfie_path"]
                      for row in conn.execute(f"SELECT {field} FROM kyc_submissions WHERE {field} IS NOT NULL")}
    groups = {}
    for file_id, user_id, path in _uploaded_files():
        if str(path) in referenced:
            continue
        account = accounts.get(user_id)
        archived = historical.get(str(user_id), {})
        if user_id not in groups:
            groups[user_id] = {
                "user_id": user_id,
                "account_present": account is not None,
                "first_name": account["first_name"] if account else archived.get("first_name", ""),
                "last_name": account["last_name"] if account else archived.get("last_name", ""),
                "phone_number": _mask_phone(account["phone_number"]) if account else archived.get("phone_number", ""),
                "previous_status": archived.get("previous_status"),
                "files": [],
            }
        match = re.search(r"level([23])_(\d+)_(front|back|selfie)", path.name)
        groups[user_id]["files"].append({
            "id": file_id,
            "name": path.name,
            "kind": match[3] if match else "document",
            "level": int(match[1]) if match else None,
            "size": path.stat().st_size,
            "uploaded_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        })
    return {"groups": list(groups.values()), "total_files": sum(len(g["files"]) for g in groups.values())}


@router.get("/admin/kyc/retained-files/{file_id}")
async def retained_file(file_id: str, session=Depends(require_review_session)):
    if not re.fullmatch(r"[a-f0-9]{64}", file_id):
        raise HTTPException(status_code=404, detail="file_not_found")
    for candidate, user_id, path in _uploaded_files():
        if candidate == file_id:
            _audit("view_retained_kyc_document", {"user_id": user_id, "file_id": file_id, "admin": session["username"]})
            return _file_response(path)
    raise HTTPException(status_code=404, detail="file_not_found")
