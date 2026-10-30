import pytest
from engine.state import state
from engine.risk_manager import risk_manager


def setup_function():
    state.reset_capital()
    state.emergency_stop = False


def test_emergency_stop_blocks_all_orders():
    state.emergency_stop = True
    valid, reason = risk_manager.validate_order("ALPHACORP", "BUY", 50, 1000.0)
    assert not valid
    assert "EMERGENCY_STOP" in reason


def test_insufficient_cash_rejected():
    state.available_cash = 500.0  # Only ₹500 cash
    valid, reason = risk_manager.validate_order("ALPHACORP", "BUY", 100, 1000.0)  # Requires ₹1,00,000
    assert not valid
    assert "INSUFFICIENT_CAPITAL" in reason


def test_concentration_limit_enforced():
    # Attempting to allocate > 25% of ₹10,00,000 into one stock (e.g. ₹3,50,000)
    state.available_cash = 1_000_000.0
    valid, reason = risk_manager.validate_order("ALPHACORP", "BUY", 350, 1000.0)
    assert not valid
    assert "CONCENTRATION_LIMIT" in reason


def test_stop_loss_trigger():
    # Long position entered at 1000, price falls to 960 (4% loss, limit 3.5%)
    state.holdings["ALPHACORP"] = {
        "quantity": 50,
        "avg_price": 1000.0,
        "position_type": "LONG"
    }
    state.market_prices["ALPHACORP"] = {"close": 960.0}

    orders = risk_manager.check_stop_losses()
    assert len(orders) == 1
    assert orders[0]["ticker"] == "ALPHACORP"
    assert orders[0]["action"] == "SELL"
    assert "STOP_LOSS" in orders[0]["reason"]


def test_take_profit_trigger():
    # Long position entered at 1000, price rises to 1060 (6% profit, target 5.0%)
    state.holdings["ALPHACORP"] = {
        "quantity": 50,
        "avg_price": 1000.0,
        "position_type": "LONG"
    }
    state.market_prices["ALPHACORP"] = {"close": 1060.0}

    orders = risk_manager.check_take_profits()
    assert len(orders) == 1
    assert orders[0]["ticker"] == "ALPHACORP"
    assert orders[0]["action"] == "SELL"
    assert "TAKE_PROFIT" in orders[0]["reason"]
    assert "1060.0" in str(state.market_prices["ALPHACORP"]["close"])

