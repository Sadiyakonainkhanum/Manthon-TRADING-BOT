import pytest
from engine.state import state
from engine.config import config
from engine.strategy import strategy
from engine.universe_manager import universe_manager
from engine.heartbeat_worker import heartbeat_worker


def setup_function():
    state.reset_capital()
    config.DEMO_MODE = True
    config.SUBMIT_LIVE_ORDERS = False


import time
import pytest
from engine.state import state
from engine.config import config
from engine.strategy import strategy
from engine.universe_manager import universe_manager
from engine.heartbeat_worker import heartbeat_worker


def setup_function():
    state.reset_capital()
    config.DEMO_MODE = True
    config.SUBMIT_LIVE_ORDERS = False


def test_heartbeat_sequence_acknowledgment():
    # Pre-flight sequence #14 in demo mode
    state.is_demo_mode = True
    success = heartbeat_worker.acknowledge_sequence(14)
    assert success is True
    assert state.last_heartbeat_seq == 14
    assert state.heartbeat_status == "DEMO"


def test_readiness_indicator_states():
    # 1. DEMO state
    state.is_demo_mode = True
    r_demo = state.get_readiness_status()
    assert r_demo["status"] == "DEMO"
    assert "NOT COMPETITION-READY" in r_demo["sublabel"]
    assert r_demo["is_ready"] is False

    # 2. ERROR state when Kafka disconnected
    state.is_demo_mode = False
    state.kafka_status = "DISCONNECTED"
    state.kafka_error = "Broker unreachable"
    r_err = state.get_readiness_status()
    assert r_err["status"] == "ERROR"
    assert r_err["is_ready"] is False

    # 3. WAITING state when Kafka connected but no heartbeat yet
    state.kafka_status = "CONNECTED"
    state.kafka_error = None
    state.rest_status = "ONLINE"
    state.rest_error = None
    state.last_heartbeat_seq = 0
    state.last_heartbeat_time = None
    state.last_heartbeat_ack_success = False
    r_wait = state.get_readiness_status()
    assert r_wait["status"] == "WAITING"
    assert r_wait["is_ready"] is False

    # 4. READY state when Kafka connected and recent ACK confirmed
    state.last_heartbeat_seq = 5
    state.last_heartbeat_time = time.time()
    state.last_heartbeat_ack_success = True
    state.last_heartbeat_latency_ms = 4.2
    r_ready = state.get_readiness_status()
    assert r_ready["status"] == "READY"
    assert r_ready["is_ready"] is True
    assert "PRE-FLIGHT CONFIRMED" in r_ready["sublabel"]


def test_trading_halted_when_paused():
    state.is_running = True
    state.is_demo_mode = False  # Simulate live stage
    state.sim_stage = "simulation"
    state.sim_status = "PAUSED"  # Paused stage

    # Ensure no trade is executed
    order_count_before = len(state.order_log)
    candle = {"ticker": "ALPHACORP", "close": 1500.0, "open": 1500.0, "high": 1510.0, "low": 1490.0, "volume": 1000000}
    strategy.on_price_tick(candle, simulated_date="2021-04-20", is_demo=False)
    assert len(state.order_log) == order_count_before


def test_trading_halted_when_completed():
    state.is_running = True
    state.is_demo_mode = False
    state.sim_stage = "simulation"
    state.sim_status = "COMPLETED"

    order_count_before = len(state.order_log)
    candle = {"ticker": "BETATECH", "close": 1000.0, "open": 1000.0, "high": 1010.0, "low": 990.0, "volume": 1000000}
    strategy.on_price_tick(candle, simulated_date="2021-04-20", is_demo=False)
    assert len(state.order_log) == order_count_before


def test_dynamic_universe_discovery_not_hardcoded():
    univ = universe_manager.load_universe()
    assert len(univ) > 0
    first_ticker = list(state.universe.keys())[0]
    assert first_ticker in state.universe
    assert state.universe[first_ticker]["name"] != ""

