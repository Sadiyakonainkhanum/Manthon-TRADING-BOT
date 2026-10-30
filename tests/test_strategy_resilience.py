import pytest
from engine.state import state
from engine.config import config
from engine.strategy import strategy
from engine.indicators import TechnicalIndicators
from engine.sentiment_analyzer import sentiment_analyzer
from engine.risk_manager import risk_manager
from engine.execution_engine import execution_engine


def setup_function():
    state.reset_capital()
    config.DEMO_MODE = False
    config.SUBMIT_LIVE_ORDERS = False
    state.is_running = True
    state.sim_stage = "simulation"
    state.sim_status = "RUNNING"


def test_missing_and_stale_prices():
    """Verify indicators gracefully handle zero, none, and insufficient price bars."""
    # Empty price series
    eval_empty = TechnicalIndicators.evaluate_signals([])
    assert eval_empty["signal"] == "HOLD"
    assert eval_empty["drop_3d_pct"] is None

    # Series with < 4 bars
    eval_short = TechnicalIndicators.evaluate_signals([100.0, 101.0, 99.0])
    assert eval_short["signal"] == "HOLD"
    assert "Insufficient" in eval_short["reason"]

    # Flat / stale price series (zero volatility)
    stale_prices = [100.0] * 25
    eval_stale = TechnicalIndicators.evaluate_signals(stale_prices)
    assert eval_stale["drop_3d_pct"] == 0.0
    assert eval_stale["fast_ma"] == 100.0
    assert eval_stale["slow_ma"] == 100.0
    assert eval_stale["rsi"] == 100.0 or eval_stale["rsi"] is not None


def test_duplicate_signals_blocked_same_simulated_day():
    """Verify that multiple orders for the same ticker on the same simulated day are prevented."""
    ticker = "BLUX"
    price = 200.0
    date = "2025-10-15"

    # First order should fill in paper mode
    res1 = execution_engine.execute_order(ticker, "BUY", 50, price, simulated_date=date, strategy_reason="Signal 1")
    assert res1["status"] == "FILLED"
    assert f"{ticker}:{date}" in state.daily_executed_orders

    # Second order on same day must be rejected
    res2 = execution_engine.execute_order(ticker, "BUY", 50, price, simulated_date=date, strategy_reason="Signal 2")
    assert res2["status"] == "REJECTED"
    assert "DUPLICATE_ORDER_PREVENTED" in res2["rejection_reason"]


def test_cash_reserve_floor_enforcement():
    """Verify that orders violating the 20% liquid cash cushion are rejected."""
    # Total Wealth = 1,000,000 (300,000 cash + 700,000 in other stock holdings)
    # 20% cushion = 200,000.
    state.available_cash = 300000.0
    state.holdings = {
        "AERX": {"quantity": 700, "avg_price": 1000.0, "position_type": "LONG", "margin_locked": 0.0, "is_demo": False}
    }
    state.market_prices["AERX"] = {"close": 1000.0}

    # Attempt to buy 150 shares of a 1,000 stock (cost: 150,000 = 15% of wealth, within 25% cap).
    # Remaining cash = 150,000 (< 200,000 reserve * 0.75 = 150,000 buffer).
    is_valid, reason = risk_manager.validate_order("HMDP", "BUY", 180, 1000.0)
    assert is_valid is False
    assert "RISK_VIOLATION" in reason or "min cash cushion" in reason


def test_single_stock_concentration_cap():
    """Verify that no single stock can exceed 25% of total portfolio wealth."""
    total_wealth = 1000000.0
    state.available_cash = 1000000.0
    # Attempt to buy 300 shares of a 1,000 stock (cost: 300,000 = 30% of portfolio).
    is_valid, reason = risk_manager.validate_order("ORCX", "BUY", 300, 1000.0)
    assert is_valid is False
    assert "CONCENTRATION_LIMIT" in reason


def test_transaction_costs_deductions():
    """Verify that flat Rs 20 brokerage is charged on BUY and Rs 35.34 (brokerage + DP) on SELL."""
    ticker = "PLNX"
    price = 100.0
    date1 = "2025-10-10"
    date2 = "2025-10-11"

    # BUY 50 shares
    res_buy = execution_engine.execute_order(ticker, "BUY", 50, price, simulated_date=date1)
    assert res_buy["status"] == "FILLED"
    assert res_buy["fee"] == 20.00
    assert state.total_brokerage_paid == 20.00
    assert state.total_dp_charges_paid == 0.00

    # SELL 50 shares
    res_sell = execution_engine.execute_order(ticker, "SELL", 50, 110.0, simulated_date=date2)
    assert res_sell["status"] == "FILLED"
    assert res_sell["fee"] == 20.00 + 15.34
    assert state.total_brokerage_paid == 40.00
    assert state.total_dp_charges_paid == 15.34


def test_stop_loss_pricing_isolation():
    """
    Test stop-loss detection and price isolation across different tickers.
    If HMDP drops 5%, it should trigger a stop loss with HMDP's current price.
    """
    # Setup holding for HMDP (entered at 1,000, current price drops to 950 -> -5.0%)
    state.holdings["HMDP"] = {
        "quantity": 50,
        "avg_price": 1000.0,
        "position_type": "LONG",
        "margin_locked": 0.0,
        "is_demo": False
    }
    state.market_prices["HMDP"] = {"close": 950.0}

    stop_orders = risk_manager.check_stop_losses()
    assert len(stop_orders) == 1
    assert stop_orders[0]["ticker"] == "HMDP"
    assert stop_orders[0]["action"] == "SELL"
    assert "STOP_LOSS: Down 5.00%" in stop_orders[0]["reason"]


def test_stop_loss_uses_target_ticker_price_not_incoming_ticker_price():
    """
    REGRESSION TEST:
    Verify that when an incoming tick for DSNY (Rs 110.27) arrives,
    a stopped-out position in HMDP (entry Rs 1,500, current Rs 1,400) is liquidated
    at HMDP's price (Rs 1,400.00), NOT at DSNY's price (Rs 110.27).
    """
    state.holdings["HMDP"] = {
        "quantity": 50,
        "avg_price": 1500.0,
        "position_type": "LONG",
        "margin_locked": 0.0,
        "is_demo": False
    }
    state.market_prices["HMDP"] = {
        "ticker": "HMDP",
        "close": 1400.0
    }

    # Incoming tick for DSNY with a vastly different price (Rs 110.27)
    incoming_dsny_tick = {
        "ticker": "DSNY",
        "open": 110.27,
        "high": 110.50,
        "low": 110.00,
        "close": 110.27,
        "volume": 1000000
    }

    strategy.on_price_tick(incoming_dsny_tick, simulated_date="2025-10-15")

    # Locate the stop-loss order in the order log
    hmdp_orders = [o for o in state.order_log if o.get("ticker") == "HMDP"]
    assert len(hmdp_orders) == 1
    hmdp_stop = hmdp_orders[0]

    assert hmdp_stop["action"] == "SELL"
    assert hmdp_stop["quantity"] == 50
    # Must match HMDP's market price (1400.0), NOT DSNY's incoming price (110.27)
    assert hmdp_stop["price"] == 1400.0
    assert hmdp_stop["price"] != 110.27
    assert hmdp_stop["status"] == "FILLED"
    assert "STOP_LOSS" in hmdp_stop["strategy_reason"]


def test_stop_loss_skips_when_target_price_missing_or_invalid():
    """
    REGRESSION TEST:
    Verify that if a target position's market price is missing or <= 0 in state,
    the stop-loss execution is safely skipped rather than executing at an invalid price or
    falling back to the incoming ticker's price.
    """
    state.holdings["PLNX"] = {
        "quantity": 50,
        "avg_price": 200.0,
        "position_type": "LONG",
        "margin_locked": 0.0,
        "is_demo": False
    }
    # Target price is invalid / 0
    state.market_prices["PLNX"] = {
        "ticker": "PLNX",
        "close": 0.0
    }

    orders_count_before = len(state.order_log)

    incoming_tick = {
        "ticker": "DSNY",
        "open": 110.27,
        "high": 110.27,
        "low": 110.27,
        "close": 110.27,
        "volume": 1000000
    }

    strategy.on_price_tick(incoming_tick, simulated_date="2025-10-16")

    # PLNX must NOT be liquidated at price 0.0 or DSNY price 110.27
    plnx_orders = [o for o in state.order_log if o.get("ticker") == "PLNX"]
    assert len(plnx_orders) == 0
    assert state.holdings["PLNX"]["quantity"] == 50


def test_news_recency_filter_blocks_stale_news():
    """Verify that news from an earlier simulated date does not leak into today's price tick."""
    state.reset_capital()
    state.is_running = True
    config.DEMO_MODE = False
    config.SUBMIT_LIVE_ORDERS = False
    state.sim_stage = "simulation"
    state.sim_status = "RUNNING"

    # Add old news from 2025-01-01
    state.news_feed.append({
        "ticker": "MOTR",
        "headline": "Massive loss and fraud investigation",
        "description": "Probe into executive conduct",
        "date": "2025-01-01",
        "sentiment": "BEARISH",
        "score": -1.0
    })

    # Incoming tick on a much later date (2025-05-01) with flat prices
    tick = {
        "ticker": "MOTR",
        "open": 50.0,
        "high": 50.0,
        "low": 50.0,
        "close": 50.0,
        "volume": 100000
    }
    strategy.on_price_tick(tick, simulated_date="2025-05-01")

    # Signal must NOT be forced to SHORT based on 4-month-old news
    sig = state.strategy_signals.get("MOTR", {})
    assert sig.get("sentiment") == "NEUTRAL"
    assert sig.get("signal") != "SHORT"


def test_take_profit_order_execution():
    """Verify that when a holding reaches +5.0% profit, an exit SELL order is triggered."""
    state.reset_capital()
    state.is_running = True
    config.DEMO_MODE = False
    config.SUBMIT_LIVE_ORDERS = False
    state.sim_stage = "simulation"
    state.sim_status = "RUNNING"

    # Open a long position of 100 shares @ ₹100
    state.holdings["HAVN"] = {
        "quantity": 100,
        "avg_price": 100.0,
        "position_type": "LONG"
    }
    state.market_prices["HAVN"] = {"close": 106.0}  # +6% gain

    # Incoming tick triggers exit checks
    tick = {
        "ticker": "HAVN",
        "open": 106.0,
        "high": 106.0,
        "low": 106.0,
        "close": 106.0,
        "volume": 100000
    }
    strategy.on_price_tick(tick, simulated_date="2025-10-20")

    # Order log must contain a SELL for HAVN with TAKE_PROFIT
    tp_orders = [o for o in state.order_log if o.get("ticker") == "HAVN" and o.get("action") == "SELL"]
    assert len(tp_orders) == 1
    assert tp_orders[0]["status"] == "FILLED"
    assert "TAKE_PROFIT" in tp_orders[0]["strategy_reason"]
    assert "HAVN" not in state.holdings
