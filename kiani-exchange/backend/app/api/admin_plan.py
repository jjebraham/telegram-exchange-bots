import json
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_db

router = APIRouter()


def _is_admin(username: str, password: str) -> bool:
    return (
        username == os.getenv("ADMIN_PANEL_USERNAME", "admin")
        and password == os.getenv("ADMIN_PANEL_PASSWORD", "admin123")
    )


def _require_admin(username: str, password: str) -> None:
    if not _is_admin(username, password):
        raise HTTPException(status_code=401, detail="invalid_admin_credentials")


class AdminAuthBody(BaseModel):
    username: str
    password: str


class GenericUpdateBody(AdminAuthBody):
    payload: dict


@router.get('/admin/settings')
async def get_settings(username: str, password: str):
    _require_admin(username, password)
    with get_db() as conn:
        rows = conn.execute('SELECT key, value, category, description FROM system_configs ORDER BY category, key').fetchall()
    return {'settings': [dict(r) for r in rows]}


@router.put('/admin/settings')
async def put_settings(req: GenericUpdateBody):
    _require_admin(req.username, req.password)
    with get_db() as conn:
        for key, value in req.payload.items():
            conn.execute(
                '''
                INSERT INTO system_configs (key, value, category, description, updated_at)
                VALUES (?, ?, 'general', '', CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                ''',
                (key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)),
            )
    return {'ok': True}


@router.get('/admin/settings/categories')
async def settings_categories(username: str, password: str):
    _require_admin(username, password)
    with get_db() as conn:
        rows = conn.execute('SELECT DISTINCT category FROM system_configs ORDER BY category').fetchall()
    return {'categories': [r['category'] for r in rows]}


@router.get('/admin/segments')
async def list_segments(username: str, password: str):
    _require_admin(username, password)
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM user_segments ORDER BY id DESC').fetchall()
    return {'segments': [dict(r) for r in rows]}


@router.post('/admin/segments')
async def create_segment(req: GenericUpdateBody):
    _require_admin(req.username, req.password)
    with get_db() as conn:
        conn.execute(
            'INSERT INTO user_segments (name, criteria_json, user_count, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
            (req.payload.get('name', 'New Segment'), json.dumps(req.payload.get('criteria', {})), int(req.payload.get('user_count', 0))),
        )
    return {'ok': True}


@router.put('/admin/segments/{segment_id}')
async def update_segment(segment_id: int, req: GenericUpdateBody):
    _require_admin(req.username, req.password)
    with get_db() as conn:
        conn.execute(
            'UPDATE user_segments SET name=?, criteria_json=?, user_count=? WHERE id=?',
            (req.payload.get('name', ''), json.dumps(req.payload.get('criteria', {})), int(req.payload.get('user_count', 0)), segment_id),
        )
    return {'ok': True}


@router.delete('/admin/segments/{segment_id}')
async def delete_segment(segment_id: int, username: str, password: str):
    _require_admin(username, password)
    with get_db() as conn:
        conn.execute('DELETE FROM user_segments WHERE id=?', (segment_id,))
    return {'ok': True}


@router.get('/admin/segments/{segment_id}/users')
async def segment_users(segment_id: int, username: str, password: str):
    _require_admin(username, password)
    return {'segment_id': segment_id, 'users': [], 'note': 'criteria-based resolver pending'}


@router.get('/admin/users/{user_id}')
async def user_details(user_id: int, username: str, password: str):
    _require_admin(username, password)
    with get_db() as conn:
        row = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='user_not_found')
    return {'user': dict(row)}


@router.put('/admin/users/{user_id}')
async def update_user(user_id: int, req: GenericUpdateBody):
    _require_admin(req.username, req.password)
    allowed = {
        'first_name', 'last_name', 'email', 'national_id', 'dob', 'bank_card_number',
        'kyc_status', 'risk_score', 'is_active', 'is_banned',
    }
    updates = {k: v for k, v in req.payload.items() if k in allowed}
    if not updates:
        return {'ok': True, 'updated': 0}
    clause = ', '.join([f"{k}=?" for k in updates.keys()])
    with get_db() as conn:
        cur = conn.execute(f'UPDATE users SET {clause} WHERE id=?', (*updates.values(), user_id))
    return {'ok': True, 'updated': cur.rowcount}


@router.post('/admin/users/{user_id}/ban')
async def ban_user(user_id: int, req: GenericUpdateBody):
    _require_admin(req.username, req.password)
    is_banned = int(bool(req.payload.get('is_banned', True)))
    with get_db() as conn:
        conn.execute('UPDATE users SET is_banned=? WHERE id=?', (is_banned, user_id))
    return {'ok': True, 'is_banned': bool(is_banned)}


@router.get('/admin/users/{user_id}/activity')
async def user_activity(user_id: int, username: str, password: str):
    _require_admin(username, password)
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM user_activity_logs WHERE user_id=? ORDER BY id DESC LIMIT 500', (user_id,)).fetchall()
    return {'activity': [dict(r) for r in rows]}


# Placeholder endpoints for full backend roadmap coverage.
PLACEHOLDER_ENDPOINTS = [
    ('GET', '/admin/exchanges', 'admin_exchanges_list'),
    ('GET', '/admin/exchanges/{exchange_id}', 'admin_exchanges_detail'),
    ('PUT', '/admin/exchanges/{exchange_id}/status', 'admin_exchanges_status'),
    ('POST', '/admin/exchanges/{exchange_id}/notes', 'admin_exchanges_notes'),
    ('GET', '/admin/exchanges/stats', 'admin_exchanges_stats'),
    ('GET', '/admin/rates/history', 'admin_rates_history'),
    ('POST', '/admin/rates/alert', 'admin_rates_alert'),
    ('GET', '/admin/pairs', 'admin_pairs_list'),
    ('POST', '/admin/pairs', 'admin_pairs_create'),
    ('PUT', '/admin/pairs/{pair_id}', 'admin_pairs_update'),
    ('DELETE', '/admin/pairs/{pair_id}', 'admin_pairs_disable'),
    ('GET', '/admin/fees', 'admin_fees_get'),
    ('PUT', '/admin/fees', 'admin_fees_put'),
    ('GET', '/admin/fees/calculator', 'admin_fees_calculator'),
    ('GET', '/admin/kyc/pending', 'admin_kyc_pending'),
    ('GET', '/admin/kyc/{user_id}', 'admin_kyc_docs'),
    ('POST', '/admin/kyc/{user_id}/verify', 'admin_kyc_verify'),
    ('POST', '/admin/kyc/{user_id}/reject', 'admin_kyc_reject'),
    ('GET', '/admin/kyc/stats', 'admin_kyc_stats'),
    ('GET', '/admin/limits', 'admin_limits_get'),
    ('PUT', '/admin/limits', 'admin_limits_put'),
    ('GET', '/admin/limits/user/{id}', 'admin_limits_user'),
    ('POST', '/admin/limits/override', 'admin_limits_override'),
    ('GET', '/admin/audit', 'admin_audit_get'),
    ('GET', '/admin/audit/export', 'admin_audit_export'),
    ('GET', '/admin/audit/user/{id}', 'admin_audit_user'),
    ('GET', '/admin/faq', 'admin_faq_list_singular'),
    ('POST', '/admin/faq', 'admin_faq_create_singular'),
    ('PUT', '/admin/faq/{id}', 'admin_faq_update_singular'),
    ('DELETE', '/admin/faq/{id}', 'admin_faq_delete_singular'),
    ('PUT', '/admin/faq/reorder', 'admin_faq_reorder_singular'),
    ('GET', '/admin/announcements', 'admin_announcements_list'),
    ('POST', '/admin/announcements', 'admin_announcements_create'),
    ('PUT', '/admin/announcements/{id}', 'admin_announcements_update'),
    ('DELETE', '/admin/announcements/{id}', 'admin_announcements_delete'),
    ('GET', '/admin/email-templates', 'admin_email_templates_list'),
    ('PUT', '/admin/email-templates/{type}', 'admin_email_templates_update'),
    ('POST', '/admin/email-templates/test', 'admin_email_templates_test'),
    ('GET', '/admin/bot/logs', 'admin_bot_logs'),
    ('GET', '/admin/bot/logs/{user_id}', 'admin_bot_logs_user'),
    ('GET', '/admin/bot/logs/export', 'admin_bot_logs_export'),
    ('GET', '/admin/bot/commands', 'admin_bot_commands_list'),
    ('PUT', '/admin/bot/commands/{command}', 'admin_bot_commands_update'),
    ('POST', '/admin/bot/commands/{command}/toggle', 'admin_bot_commands_toggle'),
    ('POST', '/admin/bot/commands', 'admin_bot_commands_create'),
    ('GET', '/admin/bot/stats', 'admin_bot_stats'),
    ('GET', '/admin/bot/stats/daily', 'admin_bot_stats_daily'),
    ('GET', '/admin/bot/response-times', 'admin_bot_response_times'),
    ('GET', '/admin/bot/auto-reply', 'admin_bot_auto_reply_list'),
    ('POST', '/admin/bot/auto-reply', 'admin_bot_auto_reply_create'),
    ('PUT', '/admin/bot/auto-reply/{id}', 'admin_bot_auto_reply_update'),
    ('DELETE', '/admin/bot/auto-reply/{id}', 'admin_bot_auto_reply_delete'),
    ('GET', '/admin/bot/scheduled', 'admin_bot_scheduled_list'),
    ('POST', '/admin/bot/scheduled', 'admin_bot_scheduled_create'),
    ('DELETE', '/admin/bot/scheduled/{id}', 'admin_bot_scheduled_delete'),
    ('GET', '/admin/fraud/alerts', 'admin_fraud_alerts'),
    ('GET', '/admin/fraud/rules', 'admin_fraud_rules_list'),
    ('POST', '/admin/fraud/rules', 'admin_fraud_rules_create'),
    ('PUT', '/admin/fraud/rules/{id}', 'admin_fraud_rules_update'),
    ('GET', '/admin/fraud/patterns', 'admin_fraud_patterns'),
    ('GET', '/admin/blacklist', 'admin_blacklist_list'),
    ('POST', '/admin/blacklist', 'admin_blacklist_create'),
    ('DELETE', '/admin/blacklist/{id}', 'admin_blacklist_delete'),
    ('GET', '/admin/blacklist/check', 'admin_blacklist_check'),
    ('GET', '/admin/velocity/rules', 'admin_velocity_rules_list'),
    ('POST', '/admin/velocity/rules', 'admin_velocity_rules_create'),
    ('PUT', '/admin/velocity/rules/{id}', 'admin_velocity_rules_update'),
    ('GET', '/admin/abuse/config', 'admin_abuse_config_get'),
    ('PUT', '/admin/abuse/config', 'admin_abuse_config_put'),
    ('GET', '/admin/abuse/events', 'admin_abuse_events'),
    ('POST', '/admin/abuse/whitelist', 'admin_abuse_whitelist'),
    ('GET', '/admin/review/queue', 'admin_review_queue'),
    ('PUT', '/admin/review/{id}/approve', 'admin_review_approve'),
    ('PUT', '/admin/review/{id}/reject', 'admin_review_reject'),
    ('POST', '/admin/review/{id}/flag', 'admin_review_flag'),
    ('POST', '/admin/broadcast', 'admin_broadcast_send'),
    ('GET', '/admin/broadcast/history', 'admin_broadcast_history'),
    ('GET', '/admin/broadcast/{id}/stats', 'admin_broadcast_stats'),
    ('GET', '/admin/support/tickets', 'admin_support_tickets'),
    ('GET', '/admin/support/tickets/{id}', 'admin_support_tickets_detail'),
    ('POST', '/admin/support/tickets/{id}/reply', 'admin_support_tickets_reply'),
    ('PUT', '/admin/support/tickets/{id}/status', 'admin_support_tickets_status'),
    ('PUT', '/admin/support/tickets/{id}/assign', 'admin_support_tickets_assign'),
    ('POST', '/admin/notifications/send', 'admin_notifications_send'),
    ('GET', '/admin/notifications/templates', 'admin_notifications_templates'),
    ('POST', '/admin/notifications/schedule', 'admin_notifications_schedule'),
    ('GET', '/admin/campaigns', 'admin_campaigns_list'),
    ('POST', '/admin/campaigns', 'admin_campaigns_create'),
    ('GET', '/admin/campaigns/{id}/analytics', 'admin_campaigns_analytics'),
    ('GET', '/admin/referrals', 'admin_referrals_list'),
    ('GET', '/admin/referrals/stats', 'admin_referrals_stats'),
    ('PUT', '/admin/referrals/config', 'admin_referrals_config'),
    ('GET', '/admin/referrals/leaderboard', 'admin_referrals_leaderboard'),
    ('GET', '/admin/promotions', 'admin_promotions_list'),
    ('POST', '/admin/promotions', 'admin_promotions_create'),
    ('PUT', '/admin/promotions/{id}', 'admin_promotions_update'),
    ('GET', '/admin/promotions/{id}/usage', 'admin_promotions_usage'),
    ('GET', '/admin/gamification/config', 'admin_gamification_config_get'),
    ('PUT', '/admin/gamification/config', 'admin_gamification_config_put'),
    ('GET', '/admin/gamification/leaderboard', 'admin_gamification_leaderboard'),
    ('POST', '/admin/gamification/badges', 'admin_gamification_badges_create'),
    ('GET', '/admin/transactions/export', 'admin_transactions_export'),
    ('GET', '/admin/transactions/stats', 'admin_transactions_stats'),
    ('GET', '/admin/reports/daily', 'admin_reports_daily'),
    ('GET', '/admin/reports/monthly', 'admin_reports_monthly'),
    ('GET', '/admin/reports/revenue', 'admin_reports_revenue'),
    ('GET', '/admin/reports/export', 'admin_reports_export'),
    ('GET', '/admin/analytics/overview', 'admin_analytics_overview'),
    ('GET', '/admin/analytics/users', 'admin_analytics_users'),
    ('GET', '/admin/analytics/exchanges', 'admin_analytics_exchanges'),
    ('GET', '/admin/analytics/revenue', 'admin_analytics_revenue'),
    ('GET', '/admin/analytics/charts', 'admin_analytics_charts'),
    ('GET', '/admin/api-keys', 'admin_api_keys_list'),
    ('POST', '/admin/api-keys', 'admin_api_keys_create'),
    ('DELETE', '/admin/api-keys/{id}', 'admin_api_keys_delete'),
    ('GET', '/admin/api-keys/{id}/usage', 'admin_api_keys_usage'),
    ('GET', '/admin/webhooks', 'admin_webhooks_list'),
    ('POST', '/admin/webhooks', 'admin_webhooks_create'),
    ('PUT', '/admin/webhooks/{id}', 'admin_webhooks_update'),
    ('POST', '/admin/webhooks/{id}/test', 'admin_webhooks_test'),
    ('GET', '/admin/webhooks/{id}/logs', 'admin_webhooks_logs'),
    ('POST', '/admin/backup/create', 'admin_backup_create'),
    ('GET', '/admin/backup/list', 'admin_backup_list'),
    ('POST', '/admin/backup/restore', 'admin_backup_restore'),
    ('GET', '/admin/backup/schedule', 'admin_backup_schedule_get'),
    ('PUT', '/admin/backup/schedule', 'admin_backup_schedule_put'),
    ('GET', '/admin/system/status', 'admin_system_status'),
    ('POST', '/admin/system/maintenance', 'admin_system_maintenance'),
    ('GET', '/admin/system/logs', 'admin_system_logs'),
    ('GET', '/admin/system/metrics', 'admin_system_metrics'),
]


async def _placeholder_handler(**kwargs):
    username = kwargs.get('username')
    password = kwargs.get('password')
    if username is None or password is None:
        body = kwargs.get('req')
        if body is not None:
            username = getattr(body, 'username', None)
            password = getattr(body, 'password', None)
    _require_admin(username or '', password or '')
    return {
        'implemented': False,
        'message': 'Endpoint scaffolded for admin roadmap implementation',
        'timestamp': datetime.utcnow().isoformat(),
        'received': {k: v for k, v in kwargs.items() if k not in {'password'}},
    }


for method, path, name in PLACEHOLDER_ENDPOINTS:
    if method in {'POST', 'PUT'}:
        async def handler(req: GenericUpdateBody, **kwargs):
            data = {'req': req}
            data.update(kwargs)
            return await _placeholder_handler(**data)
    else:
        async def handler(**kwargs):
            return await _placeholder_handler(**kwargs)
    handler.__name__ = name
    router.add_api_route(path, handler, methods=[method])
