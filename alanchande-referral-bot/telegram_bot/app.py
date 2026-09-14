import logging
import os

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
)

from referral_core import ReferralDB
from .admin_handlers import (
    cmd_admin_stats,
    cmd_audit,
    cmd_campaign_activate,
    cmd_campaign_close,
    cmd_campaign_config,
    cmd_campaign_create,
    cmd_campaigns,
    cmd_draw,
    cmd_verify,
)
from .config import Settings
from .reminders import post_init, post_stop
from .user_handlers import (
    cmd_menu,
    cmd_start,
    cmd_stats_user,
    on_chat_member,
    on_menu_callback,
    on_referral_check,
)

log = logging.getLogger("alanchande_referral_bot")


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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("me", cmd_stats_user))
    app.add_handler(CallbackQueryHandler(on_menu_callback, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(on_referral_check, pattern=r"^ref:check:"))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))

    app.add_handler(CommandHandler("campaign_create", cmd_campaign_create))
    app.add_handler(CommandHandler("campaign_config", cmd_campaign_config))
    app.add_handler(CommandHandler("campaign_activate", cmd_campaign_activate))
    app.add_handler(CommandHandler("campaign_close", cmd_campaign_close))
    app.add_handler(CommandHandler("campaigns", cmd_campaigns))
    app.add_handler(CommandHandler("stats", cmd_admin_stats))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(CommandHandler("verify", cmd_verify))
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
