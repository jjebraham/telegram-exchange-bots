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
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','closed','drawn')),
    invites_per_point INTEGER NOT NULL CHECK(invites_per_point >= 1),
    min_stay_hours INTEGER NOT NULL CHECK(min_stay_hours >= 0),
    max_points INTEGER NOT NULL DEFAULT 0 CHECK(max_points >= 0),
    num_winners INTEGER NOT NULL CHECK(num_winners >= 1),
    prize_text TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL UNIQUE REFERENCES campaigns(id) ON DELETE CASCADE,
    seed TEXT NOT NULL,
    entrants_json TEXT NOT NULL,
    winners_json TEXT NOT NULL,
    entrant_digest TEXT NOT NULL,
    verification_summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
