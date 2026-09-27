SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    draw_at TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','closed','drawn')),
    invites_per_point INTEGER NOT NULL CHECK(invites_per_point >= 1),
    min_stay_hours INTEGER NOT NULL CHECK(min_stay_hours >= 0),
    max_points INTEGER NOT NULL DEFAULT 0 CHECK(max_points >= 0),
    num_winners INTEGER NOT NULL CHECK(num_winners >= 1),
    prize_text TEXT NOT NULL DEFAULT '',
    rules_locked_at TEXT,
    rules_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invite_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    invite_link TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(campaign_id, user_id)
);
CREATE TABLE IF NOT EXISTS pending_referrals (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    joined_user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    referrer_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    joined_username TEXT,
    joined_first_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, joined_user_id)
);
CREATE INDEX IF NOT EXISTS idx_pending_referrals_referrer
    ON pending_referrals(campaign_id, referrer_id);
CREATE TABLE IF NOT EXISTS pending_referral_reminders (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    joined_user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    sent_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, joined_user_id)
);
CREATE TABLE IF NOT EXISTS participant_welcomes (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    sent_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, user_id)
);
CREATE TABLE IF NOT EXISTS funnel_events (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, user_id, event_type, source)
);
CREATE INDEX IF NOT EXISTS idx_funnel_events_campaign_type
    ON funnel_events(campaign_id, event_type);
CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    joined_user_id INTEGER NOT NULL,
    referrer_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    joined_username TEXT,
    joined_first_name TEXT,
    joined_at TEXT NOT NULL,
    stay_since TEXT NOT NULL,
    left_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    qualified_notified_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(campaign_id, joined_user_id)
);
CREATE INDEX IF NOT EXISTS idx_referrals_campaign_referrer ON referrals(campaign_id, referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_campaign_joined ON referrals(campaign_id, joined_user_id);
CREATE INDEX IF NOT EXISTS idx_referrals_active_stay ON referrals(campaign_id, active, stay_since);
CREATE TABLE IF NOT EXISTS referral_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    joined_user_id INTEGER NOT NULL,
    referrer_id INTEGER,
    event_type TEXT NOT NULL,
    event_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_referral_events_campaign_user
    ON referral_events(campaign_id, joined_user_id, event_at);
CREATE INDEX IF NOT EXISTS idx_referral_events_campaign_referrer
    ON referral_events(campaign_id, referrer_id, event_at);
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
    admin_user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_campaign
    ON admin_audit_log(campaign_id, created_at);
CREATE TABLE IF NOT EXISTS draw_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL UNIQUE REFERENCES campaigns(id) ON DELETE CASCADE,
    entrants_json TEXT NOT NULL,
    entrant_digest TEXT NOT NULL,
    verification_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL UNIQUE REFERENCES campaigns(id) ON DELETE CASCADE,
    seed TEXT NOT NULL,
    seed_source TEXT NOT NULL DEFAULT '',
    entrants_json TEXT NOT NULL,
    winners_json TEXT NOT NULL,
    reserves_json TEXT NOT NULL DEFAULT '[]',
    entrant_digest TEXT NOT NULL,
    verification_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaign_daily_metrics (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    snapshot_date TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_metrics_campaign_date
    ON campaign_daily_metrics(campaign_id, snapshot_date);
CREATE TABLE IF NOT EXISTS notification_throttle (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    window_started_at TEXT NOT NULL,
    sent_count INTEGER NOT NULL DEFAULT 0,
    suppressed_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(campaign_id, user_id)
);
CREATE TABLE IF NOT EXISTS maintenance_status (
    name TEXT PRIMARY KEY,
    last_ok_at TEXT,
    last_error_at TEXT,
    last_error TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""
