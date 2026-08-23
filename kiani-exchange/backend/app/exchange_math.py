from dataclasses import dataclass


@dataclass
class CalculatedOrder:
    fee_amount: float
    fee_currency: str
    net_send_amount: float
    receive_amount: float


def calculate_fee(exchange_type: str, send_amount: float) -> tuple[float, str]:
    if exchange_type == "sell_lira":  # TL -> Toman
        return (160.0 if send_amount < 5000 else 0.0, "TL")

    if exchange_type == "buy_lira":  # Toman -> TL
        return (160.0 if send_amount < 15_000_000 else 0.0, "TL")

    if exchange_type in {"buy_usdt", "sell_usdt", "convert_usdt_to_lira", "convert_lira_to_usdt"}:
        return (5.0, "USDT")

    return (0.0, "")


def calculate_order(exchange_type: str, send_amount: float, rates: dict[str, float]) -> CalculatedOrder:
    fee_amount, fee_currency = calculate_fee(exchange_type, send_amount)

    if exchange_type == "buy_lira":
        receive = (send_amount / rates["buy_lira"]) - fee_amount
        net_send = send_amount
    elif exchange_type == "sell_lira":
        net_send = max(send_amount - fee_amount, 0.0)
        receive = net_send * rates["sell_lira"]
    elif exchange_type == "buy_usdt":
        receive = (send_amount / rates["buy_usdt"]) - fee_amount
        net_send = send_amount
    elif exchange_type == "sell_usdt":
        net_send = max(send_amount - fee_amount, 0.0)
        receive = net_send * rates["sell_usdt"]
    elif exchange_type == "convert_usdt_to_lira":
        net_send = max(send_amount - fee_amount, 0.0)
        receive = net_send * rates["usdt_to_lira"]
    elif exchange_type == "convert_lira_to_usdt":
        receive = (send_amount / rates["lira_to_usdt"]) - fee_amount
        net_send = send_amount
    else:
        raise ValueError("unsupported_exchange_type")

    return CalculatedOrder(
        fee_amount=round(fee_amount, 4),
        fee_currency=fee_currency,
        net_send_amount=round(max(net_send, 0.0), 4),
        receive_amount=round(max(receive, 0.0), 4),
    )


def _effective_rate(raw_rate: float, manual_rate: float, percentage: float, decimals: int | None) -> float:
    base = manual_rate if manual_rate and manual_rate > 0 else raw_rate
    effective = base * (1 + (percentage / 100.0))
    if decimals is None:
        return round(effective / 10) * 10
    return round(effective, decimals)


def derive_rates(
    usdt_irr: float,
    usdt_try: float,
    settings: dict[str, float] | None = None,
) -> dict[str, float]:
    settings = settings or {}
    eff_toman = usdt_irr / 10
    raw_toman_per_tl = eff_toman / usdt_try

    return {
        "buy_lira": _effective_rate(
            raw_toman_per_tl,
            float(settings.get("toman_to_tl_manual_rate", 0) or 0),
            float(settings.get("toman_to_tl_percentage", -0.5) or 0),
            None,
        ),
        "sell_lira": _effective_rate(
            raw_toman_per_tl,
            float(settings.get("tl_to_toman_manual_rate", 0) or 0),
            float(settings.get("tl_to_toman_percentage", -6.0) or 0),
            None,
        ),
        "buy_usdt": _effective_rate(
            eff_toman,
            float(settings.get("toman_to_usdt_manual_rate", 0) or 0),
            float(settings.get("toman_to_usdt_percentage", 1.0) or 0),
            None,
        ),
        "sell_usdt": _effective_rate(
            eff_toman,
            float(settings.get("usdt_to_toman_manual_rate", 0) or 0),
            float(settings.get("usdt_to_toman_percentage", -1.0) or 0),
            None,
        ),
        "usdt_to_lira": _effective_rate(
            usdt_try,
            float(settings.get("usdt_to_tl_manual_rate", 0) or 0),
            float(settings.get("usdt_to_tl_percentage", -2.0) or 0),
            2,
        ),
        "lira_to_usdt": _effective_rate(
            usdt_try,
            float(settings.get("tl_to_usdt_manual_rate", 0) or 0),
            float(settings.get("tl_to_usdt_percentage", 2.0) or 0),
            2,
        ),
        "foreign_payment": round((eff_toman * 1.05) / 10) * 10,
    }
