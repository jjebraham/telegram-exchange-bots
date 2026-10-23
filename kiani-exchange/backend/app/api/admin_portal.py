"""Read-only summaries used by the restored admin portal."""
import json
from fastapi import APIRouter, Depends
from ..admin_auth import optional_admin_session
from ..database import get_db
from .users import _require_admin_access

router = APIRouter()


@router.get('/admin/overview')
async def admin_overview(session=Depends(optional_admin_session)):
    _require_admin_access(session, {'admin', 'support', 'viewer'})
    with get_db() as conn:
        totals = dict(conn.execute('''SELECT COUNT(*) AS total_orders,
            SUM(CASE WHEN status = 'Done' THEN 1 ELSE 0 END) AS done_orders,
            SUM(CASE WHEN status LIKE 'Canceled%' THEN 1 ELSE 0 END) AS canceled_orders
            FROM transactions''').fetchone())
        kyc = conn.execute('''SELECT
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_kyc,
            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_kyc
            FROM kyc_submissions''').fetchone()
        totals.update(dict(kyc))
    return {'report': totals}


@router.get('/admin/kyc-logs')
async def admin_kyc_logs(session=Depends(optional_admin_session)):
    _require_admin_access(session, {'admin', 'support'})
    with get_db() as conn:
        rows = conn.execute('''SELECT id, user_id, level, status, rejection_reason,
            created_at, updated_at, reviewed_by, declaration_version
            FROM kyc_submissions ORDER BY updated_at DESC, id DESC LIMIT 300''').fetchall()
    items = [{'id': row['id'], 'created_at': row['updated_at'] or row['created_at'],
              'action': f"KYC #{row['id']} · level {row['level']} · {row['status']}",
              'details': json.dumps({'user_id': row['user_id'], 'status': row['status'],
                  'reviewed_by': row['reviewed_by'], 'reason': row['rejection_reason'],
                  'declaration_version': row['declaration_version']}, ensure_ascii=False)}
             for row in rows]
    return {'kyc_verification_logs': items, 'ehraz_logs': [], 'sms_logs': []}
