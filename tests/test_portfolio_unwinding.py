import pytest
from engine.state import state
from engine.strategy import strategy
from engine.execution_engine import execution_engine
from engine.config import config


def test_simulation_unwinding_liquidates_open_positions():
    state.reset_capital()
    config.SUBMIT_LIVE_ORDERS = False
    state.is_running = True
    state.emergency_stop = False
    state.sim_stage = "simulation"
    state.sim_status = "RUNNING"
    state.sim_total_days = 30
    state.sim_days_completed = 29  # Penultimate day (unwinding active!)

    # Setup open long position in ALPHACORP (flat P&L to test pure unwinding liquidation)
    state.holdings["ALPHACORP"] = {
        "quantity": 100,
        "avg_price": 550.0,
        "position_type": "LONG",
        "entry_date": "2025-01-01",
        "is_demo": False,
    }

    candle = {
        "ticker": "ALPHACORP",
        "open": 550.0,
        "high": 552.0,
        "low": 548.0,
        "close": 551.0,
        "volume": 100000,
    }

    # Run on_price_tick on penultimate day
    strategy.on_price_tick(
        tick_data=candle,
        simulated_date="2025-01-30",
        is_demo=False,
        event_source="LIVE_KAFKA",
    )

    # Position should be closed via SELL unwinding order
    assert "ALPHACORP" not in state.holdings or state.holdings["ALPHACORP"]["quantity"] == 0
    # Latest order in log should be SELL with [SIM_UNWIND]
    assert len(state.order_log) > 0
    latest_order = state.order_log[-1]
    assert latest_order["action"] == "SELL"
    assert "[SIM_UNWIND]" in latest_order["strategy_reason"]


def test_simulation_unwinding_blocks_new_buy_entries():
    state.reset_capital()
    config.SUBMIT_LIVE_ORDERS = False
    state.is_running = True
    state.emergency_stop = False
    state.sim_stage = "simulation"
    state.sim_status = "RUNNING"
    state.sim_total_days = 30
    state.sim_days_completed = 30  # Final day (unwinding active)

    # No open position
    assert "BETATECH" not in state.holdings

    candle = {
        "ticker": "BETATECH",
        "open": 100.0,
        "high": 110.0,
        "low": 95.0,
        "close": 105.0,
        "volume": 200000,
    }

    order_count_before = len(state.order_log)

    strategy.on_price_tick(
        tick_data=candle,
        simulated_date="2025-01-31",
        is_demo=False,
        event_source="LIVE_KAFKA",
    )

    # New entries must be strictly blocked during unwinding
    assert "BETATECH" not in state.holdings
    # No BUY order should have been dispatched
    buy_orders = [o for o in state.order_log[order_count_before:] if o.get("action") == "BUY"]
    assert len(buy_orders) == 0
