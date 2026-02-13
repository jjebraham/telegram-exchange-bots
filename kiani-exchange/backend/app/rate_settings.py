from .database import get_db

DEFAULT_RATE_SETTINGS = {
    "toman_to_tl_factor": 0.995,
    "tl_to_toman_factor": 0.94,
    "buy_usdt_factor": 1.01,
    "sell_usdt_factor": 0.99,
    "usdt_to_lira_factor": 0.98,
    "lira_to_usdt_factor": 1.02,
    "foreign_payment_factor": 1.05,
}


def get_rate_settings() -> dict[str, float]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM rate_settings WHERE id = 1").fetchone()
    if not row:
        return DEFAULT_RATE_SETTINGS.copy()
    settings = DEFAULT_RATE_SETTINGS.copy()
    for key in settings.keys():
        value = row[key] if key in row.keys() else settings[key]
        settings[key] = float(value)
    return settings


def update_rate_settings(values: dict[str, float]) -> dict[str, float]:
    current = get_rate_settings()
    current.update(values)
    with get_db() as conn:
        conn.execute(
            """UPDATE rate_settings
               SET toman_to_tl_factor = ?, tl_to_toman_factor = ?, buy_usdt_factor = ?, sell_usdt_factor = ?,
                   usdt_to_lira_factor = ?, lira_to_usdt_factor = ?, foreign_payment_factor = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = 1""",
            (
                current["toman_to_tl_factor"],
                current["tl_to_toman_factor"],
                current["buy_usdt_factor"],
                current["sell_usdt_factor"],
                current["usdt_to_lira_factor"],
                current["lira_to_usdt_factor"],
                current["foreign_payment_factor"],
            ),
        )
    return current
