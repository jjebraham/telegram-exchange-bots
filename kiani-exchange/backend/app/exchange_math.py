from dataclasses import dataclass


@dataclass
class CalculatedOrder:
    fee_amount: float
    fee_currency: str
    net_send_amount: float
    receive_amount: float


def calculate_fee(exchange_type: str, send_amount: float) -> tuple[float, str]:
    if exchange_type == "sell_lira":  # TL -> Toman
        return (80.0 if send_amount < 5000 else 0.0, "TL")

    if exchange_type == "buy_lira":  # Toman -> TL
        return (80.0 if send_amount < 15_000_000 else 0.0, "TL")

    if exchange_type in {"buy_usdt", "sell_usdt", "convert_usdt_to_lira", "convert_lira_to_usdt"}:
        return (5.0, "USDT")

    return (0.0, "")


def calculate_order(exchange_type: str, send_amount: float, rates: dict[str, float]) -> CalculatedOrder:
    fee_amount, fee_currency = calculate_fee(exchange_type, send_amount)

    if exchange_type == "buy_lira":
        receive = (send_amount / rates["buy_lira"]) - fee_amount
        net_send = send_amount
    elif exchange_type == "sell_lira":
        receive = send_amount * rates["sell_lira"]
        net_send = send_amount
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


def derive_rates(usdt_irr: float, usdt_try: float, settings: dict[str, float] | None = None) -> dict[str, float]:
    eff_toman = usdt_irr / 10
    s = settings or {}
    toman_to_tl = float(s.get("toman_to_tl_factor", 0.995))
    tl_to_toman = float(s.get("tl_to_toman_factor", 0.94))
    buy_usdt_factor = float(s.get("buy_usdt_factor", 1.01))
    sell_usdt_factor = float(s.get("sell_usdt_factor", 0.99))
    usdt_to_lira_factor = float(s.get("usdt_to_lira_factor", 0.98))
    lira_to_usdt_factor = float(s.get("lira_to_usdt_factor", 1.02))
    return {
        "buy_lira": round(((eff_toman / usdt_try) * toman_to_tl) / 10) * 10,
        "sell_lira": round(((eff_toman / usdt_try) * tl_to_toman) / 10) * 10,
        "buy_usdt": round((eff_toman * buy_usdt_factor) / 10) * 10,
        "sell_usdt": round((eff_toman * sell_usdt_factor) / 10) * 10,
        "usdt_to_lira": round(usdt_try * usdt_to_lira_factor, 2),
        "lira_to_usdt": round(usdt_try * lira_to_usdt_factor, 2),
    }
