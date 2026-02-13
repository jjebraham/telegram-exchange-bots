from app.exchange_math import calculate_fee, calculate_order


def test_tl_to_toman_fee_threshold():
    assert calculate_fee("sell_lira", 4999)[0] == 80
    assert calculate_fee("sell_lira", 5000)[0] == 0
    assert calculate_fee("sell_lira", 8000)[0] == 0


def test_toman_to_tl_fee_threshold():
    assert calculate_fee("buy_lira", 14_999_999)[0] == 80
    assert calculate_fee("buy_lira", 15_000_000)[0] == 0
    assert calculate_fee("buy_lira", 25_000_000)[0] == 0


def test_usdt_to_tl_fee_before_rate():
    rates = {
        "buy_lira": 1000,
        "sell_lira": 1000,
        "buy_usdt": 1000,
        "sell_usdt": 1000,
        "usdt_to_lira": 42.78,
        "lira_to_usdt": 44.1,
    }
    result = calculate_order("convert_usdt_to_lira", 100, rates)
    assert result.fee_amount == 5
    assert result.net_send_amount == 95
    assert result.receive_amount == 4064.1


def test_usdt_to_tl_net_zero_when_fee_equals_send():
    rates = {
        "buy_lira": 1000,
        "sell_lira": 1000,
        "buy_usdt": 1000,
        "sell_usdt": 1000,
        "usdt_to_lira": 42.78,
        "lira_to_usdt": 44.1,
    }
    result = calculate_order("convert_usdt_to_lira", 5, rates)
    assert result.net_send_amount == 0
    assert result.receive_amount == 0
