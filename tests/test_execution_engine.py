import pytest
from engine.state import state
from engine.config import config
from engine.execution_engine import execution_engine


def setup_function():
    state.reset_capital()
    config.DEMO_MODE = True
    config.SUBMIT_LIVE_ORDERS = False


def test_duplicate_order_prevention_same_day():
    state.market_prices["BETATECH"] = {"close": 1000.0}
    sim_date = "2021-04-15"

    # First order succeeds
    ord1 = execution_engine.execute_order("BETATECH", "BUY", 50, current_price=1000.0, simulated_date=sim_date)
    assert ord1["status"] == "FILLED"

    # Second order on the SAME day for SAME ticker must be prevented
    ord2 = execution_engine.execute_order("BETATECH", "BUY", 50, current_price=1000.0, simulated_date=sim_date)
    assert ord2["status"] == "REJECTED"
    assert "DUPLICATE_ORDER_PREVENTED" in ord2["rejection_reason"]


def test_order_fee_accounting():
    # Buy 50 shares of ALPHACORP at 1000
    state.market_prices["ALPHACORP"] = {"close": 1000.0}
    ord_buy = execution_engine.execute_order("ALPHACORP", "BUY", 50, current_price=1000.0, simulated_date="2021-04-16")
    assert ord_buy["status"] == "FILLED"
    assert ord_buy["fee"] == 20.00  # Flat ₹20 brokerage
    
    # Sell 50 shares of ALPHACORP
    ord_sell = execution_engine.execute_order("ALPHACORP", "SELL", 50, current_price=1050.0, simulated_date="2021-04-17")
    assert ord_sell["status"] == "FILLED"
    # Flat ₹20 brokerage + ₹15.34 DP charge = ₹35.34
    assert ord_sell["fee"] == 35.34


def test_decision_audit_trail_recorded():
    state.market_prices["GAMMAPHARMA"] = {"close": 500.0}
    execution_engine.execute_order("GAMMAPHARMA", "BUY", 50, current_price=500.0, simulated_date="2021-04-18", strategy_reason="Unit test signal")
    assert len(state.decision_audit_trail) > 0
    last_decision = state.decision_audit_trail[-1]
    assert last_decision["ticker"] == "GAMMAPHARMA"
    assert last_decision["strategy_reason"] == "Unit test signal"


def test_safety_lock_blocks_live_order_dispatch():
    from engine.api_client import api_client
    config.SUBMIT_LIVE_ORDERS = False
    config.SERVER_IP = "192.168.65.157"
    config.BOT_ACCESS_TOKEN = "dummy_token"
    res = api_client.submit_order("AERX", "BUY", 50)
    assert res["status"] == "REJECTED"
    assert "SAFETY_LOCK" in res["rejection_reason"]

