import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
)

from referral_core import ReferralDB, utcnow
from .admin_handlers import (
    cmd_admin_stats,
    cmd_adminlog,
    cmd_audit,
    cmd_campaign_activate,
    cmd_campaign_close,
    cmd_campaign_config,
    cmd_campaign_create,
    cmd_campaign_draw_at,
    cmd_campaigns,
    cmd_draw,
    cmd_flags,
    cmd_snapshot,
    cmd_verify,
)
from .config import Settings
from .context import is_admin, services
from .growth import (
    cmd_funnel_clear,
    cmd_promo_link,
    cmd_promo_post,
    cmd_weekly_post,
)
from .live_runtime import on_chat_member, post_init, post_stop
from .promo_handlers import cmd_start_entry, on_promo_enter
from .owned_audiences import cmd_owned_sources
from .launch_tracking import cmd_launch_mark, cmd_launch_report
from .publish import cmd_publish_promo, on_publish_promo_callback
from .referral_success import on_referral_check_and_welcome
from .share_activation import cmd_sources
from .user_handlers import cmd_menu, cmd_stats_user, on_menu_callback

log = logging.getLogger("alanchande_referral_bot")
UTC = timezone.utc


def _admin_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings, db = services(context)
    if not is_admin(update, settings):
        return settings, db, None
    campaign = db.get_campaign(context.args[0]) if context.args else db.live_campaign()
    return settings, db, campaign


def _age_text(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h {minutes % 60}m"
    return f"{hours // 24}d {hours % 24}h"


async def cmd_trend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db, campaign = _admin_campaign(update, context)
    if not update.message or not is_admin(update, settings):
        return
    if not campaign:
        await update.message.reply_text("Usage: /trend [campaign_slug] — campaign not found.")
        return
    db.capture_daily_metrics(campaign)
    rows = list(reversed(db.daily_metrics(campaign.id, limit=14)))
    lines = [f"📊 Daily trend — {campaign.slug}", ""]
    previous = None
    for row in rows:
        delta = ""
        if previous:
            dp = int(row["participants"]) - int(previous["participants"])
            dj = int(row["joined"]) - int(previous["joined"])
            delta = f" | Δ participants {dp:+d}, joins {dj:+d}"
        d1 = "n/a" if row.get("d1_retention_pct") is None else f"{row['d1_retention_pct']}%"
        d7 = "n/a" if row.get("d7_retention_pct") is None else f"{row['d7_retention_pct']}%"
        lines.append(
            f"• {row['snapshot_date']}: participants={row['participants']} starts={row['bot_starts']} "
            f"joins={row['joined']} active={row['active']} qualified={row['qualified']} "
            f"tickets={row['tickets']} K={row['k_factor_proxy']} D1={d1} D7={d7}{delta}"
        )
        previous = row
    lines.append("\nToday is updated throughout the day; older rows are day-end snapshots.")
    await update.message.reply_text("\n".join(lines))


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db = services(context)
    if not update.message or not is_admin(update, settings):
        return

    try:
        with db.connect() as conn:
            db_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
    except Exception as exc:
        db_check = f"ERROR: {exc}"

    try:
        me = await context.bot.get_me()
        telegram_status = f"OK (@{me.username})"
    except Exception as exc:
        telegram_status = f"ERROR: {type(exc).__name__}"

    backup_dir = Path(settings.backup_dir).expanduser()
    backups = sorted(
        backup_dir.glob("referral_bot-*.sqlite"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if backup_dir.exists() else []
    backup_age = None
    remote_state = "not configured" if not settings.backup_rclone_dest else "configured"
    backup_name = "none"
    if backups:
        latest = backups[0]
        backup_name = latest.name
        backup_time = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
        backup_age = (datetime.now(UTC) - backup_time).total_seconds()
        manifest_path = latest.with_suffix(latest.suffix + ".json")
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("remote_uploaded"):
                    remote_state = "uploaded"
                elif settings.backup_rclone_dest:
                    remote_state = "configured, latest not marked uploaded"
            except Exception:
                pass

    task_lines = []
    for key in (
        "qualification_task", "pending_reminder_task", "reconciliation_task",
        "analytics_task", "nudge_task", "daily_digest_task",
    ):
        task = context.application.bot_data.get(key)
        state = "missing" if task is None else ("failed/stopped" if task.done() else "running")
        task_lines.append(f"• {key}: {state}")

    statuses = {row["name"]: row for row in db.maintenance_statuses()}
    worker_lines = []
    now = utcnow()
    for name in (
        "qualification", "pending_reminder", "reconciliation", "analytics_snapshot",
        "nudges", "daily_admin_digest",
    ):
        row = statuses.get(name)
        if not row:
            worker_lines.append(f"• {name}: no run recorded yet")
            continue
        ok_age = None
        if row.get("last_ok_at"):
            from referral_core import parse_datetime
            ok_age = (now - parse_datetime(row["last_ok_at"])).total_seconds()
        suffix = f"last OK {_age_text(ok_age)} ago"
        if row.get("last_error"):
            suffix += f" | last error: {str(row['last_error'])[:90]}"
        worker_lines.append(f"• {name}: {suffix}")

    campaign = db.live_campaign()
    pending = db.pending_referrals_total(campaign.id) if campaign else 0
    lines = [
        "🩺 AlanChande bot health", "",
        f"Telegram: {telegram_status}",
        f"Database quick_check: {db_check}",
        f"Live campaign: {campaign.slug if campaign else 'none'}",
        f"Pending referrals: {pending}",
        f"Latest backup: {backup_name} ({_age_text(backup_age)} ago)",
        f"Off-server backup: {remote_state}",
        "", "Tasks:", *task_lines,
        "", "Worker heartbeat:", *worker_lines,
    ]
    await update.message.reply_text("\n".join(lines))


def create_application(settings: Settings) -> Application:
    db = ReferralDB(settings.db_path)
    db.init()
    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    app.add_handler(CommandHandler("start", cmd_start_entry))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("me", cmd_stats_user))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(on_promo_enter, pattern=r"^promo:enter:"))
    app.add_handler(CallbackQueryHandler(on_publish_promo_callback, pattern=r"^publishpromo:"))
    app.add_handler(CallbackQueryHandler(on_referral_check_and_welcome, pattern=r"^ref:check:"))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))

    app.add_handler(CommandHandler("campaign_create", cmd_campaign_create))
    app.add_handler(CommandHandler("campaign_config", cmd_campaign_config))
    app.add_handler(CommandHandler("campaign_draw_at", cmd_campaign_draw_at))
    app.add_handler(CommandHandler("campaign_activate", cmd_campaign_activate))
    app.add_handler(CommandHandler("campaign_close", cmd_campaign_close))
    app.add_handler(CommandHandler("campaigns", cmd_campaigns))
    app.add_handler(CommandHandler("stats", cmd_admin_stats))
    app.add_handler(CommandHandler("funnel", cmd_funnel_clear))
    app.add_handler(CommandHandler("trend", cmd_trend))
    app.add_handler(CommandHandler("sources", cmd_sources))
    app.add_handler(CommandHandler("owned_sources", cmd_owned_sources))
    app.add_handler(CommandHandler("launch_mark", cmd_launch_mark))
    app.add_handler(CommandHandler("launch_report", cmd_launch_report))
    app.add_handler(CommandHandler("promo_link", cmd_promo_link))
    app.add_handler(CommandHandler("promo_post", cmd_promo_post))
    app.add_handler(CommandHandler("publish_promo", cmd_publish_promo))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("weekly_post", cmd_weekly_post))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("flags", cmd_flags))
    app.add_handler(CommandHandler("adminlog", cmd_adminlog))
    app.add_handler(CommandHandler("verify", cmd_verify))
    app.add_handler(CommandHandler("snapshot", cmd_snapshot))
    app.add_handler(CommandHandler("draw", cmd_draw))
    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = Settings.from_env()
    app = create_application(settings)
    log.info("Starting AlanChande referral bot for %s", settings.channel_ref)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
