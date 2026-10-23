"""Read deployment credentials without changing market-module startup order."""
import os
from pathlib import Path
from dotenv import dotenv_values

_NAMES = {'WALLEX_API_KEY', 'KIANI_TRANSACTION_BOT_TOKEN', 'KIANI_REGISTRATION_BOT_TOKEN', 'KIANI_PRIVATE_PROXY_PRICE_CACHE_1', 'KIANI_PRIVATE_PROXY_USERS_1', 'KIANI_PRIVATE_PROXY_TRANSACTIONS_1', 'KIANI_PRIVATE_PROXY_PRICE_CACHE_2'}

def credential(name: str) -> str:
    if name not in _NAMES:
        raise ValueError("unsupported_credential_name")
    value = os.getenv(name)
    if not value:
        value = dotenv_values(Path(__file__).resolve().parents[1] / ".env").get(name)
    return str(value or "").strip()
