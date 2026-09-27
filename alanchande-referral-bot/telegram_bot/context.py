from telegram import Update
from telegram.ext import ContextTypes

from referral_core import ReferralDB
from .config import Settings


def services(context: ContextTypes.DEFAULT_TYPE) -> tuple[Settings, ReferralDB]:
    return context.application.bot_data["settings"], context.application.bot_data["db"]


def is_admin(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id in settings.admin_ids)
