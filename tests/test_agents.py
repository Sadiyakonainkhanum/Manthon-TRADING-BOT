import math
import pytest
from engine.agents import AgnesAnalyst, JeffDecisionAgent, agnes, jeff
from engine.state import state
from engine.config import config
from engine.risk_manager import risk_manager
from engine.execution_engine import execution_engine
from engine.strategy import strategy


def test_agnes_valid_analysis_calculation():
    """Verify Agnes correctly computes MA, RSI, 3D drop, and market brief."""
    analyst = AgnesAnalyst()
    # 25 days of ascending prices: 100, 102, ..., 148
    history = [{"date": f"2025-01-{i:02d}", "close": 100.0 + i * 2.0} for i in range(1, 26)]
    news = [
        {"ticker": "BLUX", "headline": "Strong Q3 earnings beat", "sentiment": "BULLISH", "score": 0.85, "date": "2025-01-25"}
    ]

    report = analyst.analyze(
        ticker="BLUX",
        current_price=150.0,
        price_history=history,
        news_feed=news,
        simulated_date="2025-01-25"
    )

    assert report["is_valid"] is True
    assert report["ticker"] == "BLUX"
    assert report["current_price"] == 150.0
    assert report["fast_ma"] is not None
    assert report["slow_ma"] is not None
    assert report["fast_ma"] > report["slow_ma"]
    assert report["trend_direction"] == "BULLISH"
    assert report["rsi"] is not None
    assert report["sentiment"] == "BULLISH"
    assert "Strong Q3 earnings beat" in report["market_context"]


def test_agnes_invalid_and_non_finite_price():
    """Verify Agnes gracefully rejects non-finite, NaN, bool, or negative prices."""
    analyst = AgnesAnalyst()
    history = [{"date": "2025-01-01", "close": 100.0}]

    for bad_price in [None, True, False, float("nan"), float("inf"), float("-inf"), -50.0, 0.0]:
        report = analyst.analyze(
            ticker="AERX",
            current_price=bad_price,
            price_history=history,
            news_feed=[],
            simulated_date="2025-01-01"
        )
        assert report["is_valid"] is False
        assert report["current_price"] is None
        assert "Invalid price" in report["error"]


def test_agnes_news_scoping_ignores_stale_news():
    """Verify Agnes only scopes news matching the current simulated day."""
    analyst = AgnesAnalyst()
    history = [{"date": "2025-05-10", "close": 100.0} for _ in range(5)]
    news = [
        {"ticker": "MOTR", "headline": "Ancient news flash", "sentiment": "BEARISH", "score": -0.9, "date": "2025-01-01"}
    ]

    report = analyst.analyze(
        ticker="MOTR",
        current_price=100.0,
        price_history=history,
        news_feed=news,
        simulated_date="2025-05-10"
    )

    assert report["is_valid"] is True
    assert report["sentiment"] == "NEUTRAL"
    assert report["sentiment_score"] == 0.0


def test_jeff_oversold_dip_recommends_buy():
    """Verify Jeff recommends BUY on a -4% dip with non-bearish sentiment."""
    decision_agent = JeffDecisionAgent()
    agnes_brief = {
        "is_valid": True,
        "ticker": "HAVN",
        "current_price": 95.0,
        "drop_3d_pct": -4.5,
        "sentiment": "NEUTRAL",
        "market_context": "HAVN dropped -4.5% in 3 days without negative news."
    }

    decision = decision_agent.decide(agnes_brief, current_holding={"quantity": 0})
    assert decision["action"] == "BUY"
    assert decision["confidence"] >= 0.80
    assert "oversold dip" in decision["explanation"].lower()
    assert decision["provider"] == "DETERMINISTIC_FALLBACK"


def test_jeff_oversold_dip_vetoed_by_bearish_news():
    """Verify Jeff recommends HOLD if an oversold dip has bearish news."""
    decision_agent = JeffDecisionAgent()
    agnes_brief = {
        "is_valid": True,
        "ticker": "HAVN",
        "current_price": 95.0,
        "drop_3d_pct": -4.5,
        "sentiment": "BEARISH",
        "news_headline": "Regulatory probe opened",
        "market_context": "HAVN dropped -4.5% with bearish news probe."
    }

    decision = decision_agent.decide(agnes_brief, current_holding={"quantity": 0})
    assert decision["action"] == "HOLD"
    assert "vetoed" in decision["explanation"].lower() or "falling knife" in decision["explanation"].lower()


def test_jeff_golden_cross_rsi_overbought_guard():
    """Verify Jeff withholds BUY (recommending HOLD) if RSI >= 70 on Golden Cross."""
    decision_agent = JeffDecisionAgent()
    agnes_brief = {
        "is_valid": True,
        "ticker": "SONA",
        "current_price": 200.0,
        "fast_ma": 205.0,
        "slow_ma": 190.0,
        "is_golden_cross": True,
        "rsi": 74.5,
        "sentiment": "NEUTRAL",
        "market_context": "Golden cross with high RSI 74.5."
    }

    decision = decision_agent.decide(agnes_brief, current_holding={"quantity": 0})
    assert decision["action"] == "HOLD"
    assert "overbought" in decision["explanation"].lower()


def test_jeff_golden_cross_healthy_rsi_recommends_buy():
    """Verify Jeff recommends BUY on Golden Cross with healthy RSI (<70)."""
    decision_agent = JeffDecisionAgent()
    agnes_brief = {
        "is_valid": True,
        "ticker": "SONA",
        "current_price": 200.0,
        "fast_ma": 205.0,
        "slow_ma": 190.0,
        "is_golden_cross": True,
        "rsi": 54.0,
        "sentiment": "NEUTRAL",
        "market_context": "Golden cross with normal RSI 54."
    }

    decision = decision_agent.decide(agnes_brief, current_holding={"quantity": 0})
    assert decision["action"] == "BUY"
    assert decision["confidence"] >= 0.70
    assert "golden cross" in decision["explanation"].lower()


def test_jeff_death_cross_exits_long_position():
    """Verify Jeff recommends SELL on Death Cross when holding a long position."""
    decision_agent = JeffDecisionAgent()
    agnes_brief = {
        "is_valid": True,
        "ticker": "ROUT",
        "current_price": 120.0,
        "fast_ma": 115.0,
        "slow_ma": 125.0,
        "is_death_cross": True,
        "market_context": "Death cross active."
    }

    decision = decision_agent.decide(agnes_brief, current_holding={"quantity": 100, "position_type": "LONG"})
    assert decision["action"] == "SELL"
    assert "death cross" in decision["explanation"].lower()
    assert decision["confidence"] >= 0.70


def test_jeff_death_cross_holds_when_flat():
    """Verify Jeff recommends HOLD on Death Cross when no long position is held."""
    decision_agent = JeffDecisionAgent()
    agnes_brief = {
        "is_valid": True,
        "ticker": "ROUT",
        "current_price": 120.0,
        "fast_ma": 115.0,
        "slow_ma": 125.0,
        "is_death_cross": True,
        "market_context": "Death cross active."
    }

    decision = decision_agent.decide(agnes_brief, current_holding={"quantity": 0})
    assert decision["action"] == "HOLD"


def test_jeff_invalid_agnes_brief_safe_hold():
    """Verify Jeff returns safe HOLD if Agnes report was flagged invalid."""
    decision_agent = JeffDecisionAgent()
    agnes_brief = {
        "is_valid": False,
        "ticker": "PLNX",
        "error": "Stale price NaN"
    }

    decision = decision_agent.decide(agnes_brief, current_holding={"quantity": 0})
    assert decision["action"] == "HOLD"
    assert decision["confidence"] == 0.0
    assert "withheld" in decision["explanation"].lower()


def test_agent_integration_with_risk_manager_and_sizing():
    """End-to-end test: Jeff BUY recommendation must pass risk manager checks and dynamic 3% sizing."""
    state.reset_capital()
    state.is_running = True
    config.DEMO_MODE = False
    config.SUBMIT_LIVE_ORDERS = False
    state.sim_stage = "simulation"
    state.sim_status = "RUNNING"

    # Feed 25 descending prices to create a sharp 3-day dip (-5.0%)
    prices = [100.0] * 20 + [98.0, 96.0, 95.0, 90.0]
    for p in prices:
        tick = {
            "ticker": "DSNY",
            "open": p,
            "high": p,
            "low": p,
            "close": p,
            "volume": 50000
        }
        strategy.on_price_tick(tick, simulated_date="2025-10-20")

    # Verify Agnes and Jeff state
    assert "DSNY" in state.agent_decisions
    dec = state.agent_decisions["DSNY"]
    assert dec["agnes"]["is_valid"] is True
    assert dec["jeff"]["action"] == "BUY"

    # Verify order execution complied with dynamic sizing and risk manager
    dsny_holdings = state.holdings.get("DSNY")
    assert dsny_holdings is not None
    assert dsny_holdings["quantity"] > 0
    trade_val = dsny_holdings["quantity"] * 90.0
    wealth = state.compute_wealth_metrics()["total_wealth"]

    # Target 3% allocation (approx ₹30,000)
    assert 20000.0 <= trade_val <= 35000.0
    # Must preserve >= 20% cash reserve (>= ₹200,000)
    assert state.available_cash >= wealth * 0.20

    # Clean up stage state
    state.sim_stage = "disconnected"
    state.sim_status = "OFFLINE"
    config.DEMO_MODE = True


def test_agnes_event_source_and_latency_tracking():
    """Verify Agnes records event source, timestamps, and processing latency."""
    analyst = AgnesAnalyst()
    report_live = analyst.analyze(
        ticker="MOTR",
        current_price=60.0,
        price_history=[{"close": 60.0}],
        news_feed=[],
        simulated_date="2025-03-20",
        event_timestamp="2026-10-29T18:49:45.287Z",
        event_source="LIVE_KAFKA"
    )
    assert report_live["event_source"] == "LIVE_KAFKA"
    assert report_live["event_timestamp"] == "18:49:45"
    assert report_live["processing_latency_ms"] >= 0.0

    report_demo = analyst.analyze(
        ticker="MOTR",
        current_price=60.0,
        price_history=[{"close": 60.0}],
        news_feed=[],
        simulated_date="2025-03-20",
        event_timestamp="12:00:00",
        event_source="DEMO_MOCK"
    )
    assert report_demo["event_source"] == "DEMO_MOCK"
    assert report_demo["event_timestamp"] == "12:00:00"


def test_jeff_caches_decision_when_conditions_unchanged():
    """Verify Jeff avoids unnecessary evaluation and reuses cached decision when conditions are stable."""
    decision_agent = JeffDecisionAgent()
    brief1 = {
        "is_valid": True,
        "ticker": "AERX",
        "current_price": 100.0,
        "fast_ma": 100.0,
        "slow_ma": 100.0,
        "drop_3d_pct": 0.0,
        "rsi_regime": "NEUTRAL",
        "event_source": "LIVE_KAFKA",
        "event_timestamp": "10:00:01",
        "analysis_timestamp": "10:00:01",
    }
    dec1 = decision_agent.decide(brief1, current_holding={"quantity": 0})
    assert dec1["action"] == "HOLD"
    assert dec1["condition_change_reason"] == "Initial analysis for ticker"

    # Second tick: tiny price movement (100.1 = +0.1%), same indicators
    brief2 = {
        "is_valid": True,
        "ticker": "AERX",
        "current_price": 100.1,
        "fast_ma": 100.0,
        "slow_ma": 100.0,
        "drop_3d_pct": 0.1,
        "rsi_regime": "NEUTRAL",
        "event_source": "LIVE_KAFKA",
        "event_timestamp": "10:00:10",
        "analysis_timestamp": "10:00:10",
    }
    dec2 = decision_agent.decide(brief2, current_holding={"quantity": 0})
    assert dec2["action"] == "HOLD"
    assert dec2["condition_change_reason"] == "Unchanged (Cached)"


def test_jeff_re_evaluates_when_conditions_change():
    """Verify Jeff triggers fresh evaluation when conditions meaningfully change (e.g. price moves >= 1.0%)."""
    decision_agent = JeffDecisionAgent()
    brief1 = {
        "is_valid": True,
        "ticker": "BLUX",
        "current_price": 200.0,
        "event_source": "LIVE_KAFKA",
    }
    decision_agent.decide(brief1, current_holding={"quantity": 0})

    # Price jumps by 1.5% to 203.0
    brief2 = {
        "is_valid": True,
        "ticker": "BLUX",
        "current_price": 203.0,
        "event_source": "LIVE_KAFKA",
    }
    changed, reason = decision_agent.has_market_condition_changed("BLUX", brief2, current_holding={"quantity": 0})
    assert changed is True
    assert "Price moved" in reason


def test_jeff_simulated_llm_timeout_falls_back_deterministically():
    """Verify Jeff gracefully catches LLM timeouts and uses deterministic fallback."""
    decision_agent = JeffDecisionAgent()
    config.LLM_PROVIDER = "test_provider"
    config.LLM_API_URL = "http://127.0.0.1:1"  # Unreachable local port, triggers immediate error
    config.LLM_API_KEY = "test_key"

    brief = {
        "is_valid": True,
        "ticker": "HAVN",
        "current_price": 95.0,
        "drop_3d_pct": -4.5,
        "sentiment": "NEUTRAL",
        "market_context": "Oversold dip -4.5%",
        "event_source": "LIVE_KAFKA",
    }

    try:
        dec = decision_agent.decide(brief, current_holding={"quantity": 0})
        # Must gracefully fall back to deterministic decision without crashing
        assert dec["provider"] == "DETERMINISTIC_FALLBACK"
        assert dec["action"] == "BUY"
    finally:
        config.LLM_PROVIDER = None
        config.LLM_API_URL = None
        config.LLM_API_KEY = None


def test_jeff_rsi_oversold_triggers_buy():
    """Verify Jeff recommends BUY on deep oversold RSI (<=30) with non-bearish news."""
    decision_agent = JeffDecisionAgent()
    brief = {
        "is_valid": True,
        "ticker": "AERX",
        "current_price": 627.33,
        "rsi": 27.18,
        "sentiment": "NEUTRAL",
        "drop_3d_pct": 1.8,
        "market_context": "AERX trading at 627.33 with oversold RSI 27.18.",
        "event_source": "LIVE_KAFKA"
    }

    decision = decision_agent.decide(brief, current_holding={"quantity": 0})
    assert decision["action"] == "BUY"
    assert decision["confidence"] >= 0.80
    assert "oversold rsi" in decision["explanation"].lower()


def test_dynamic_capital_allocation_scales_with_confidence():
    """Verify capital sizing scales dynamically based on real-time analysis confidence."""
    state.reset_capital()
    state.available_cash = 1_000_000.0
    state.peak_wealth = 1_000_000.0
    price = 100.0

    # Baseline 3% at 0.75 confidence -> 300 shares (₹30,000)
    qty_base = strategy.calculate_buy_quantity("TEST", price, confidence=0.75)
    assert qty_base == 300

    # High conviction (0.95 confidence) -> higher capital allocation (~3.8%)
    qty_high = strategy.calculate_buy_quantity("TEST", price, confidence=0.95)
    assert qty_high > qty_base
    assert (qty_high * price) <= 40000.0

    # Lower conviction (0.50 confidence) -> conservative capital allocation (~2.0%)
    qty_low = strategy.calculate_buy_quantity("TEST", price, confidence=0.50)
    assert qty_low < qty_base
    assert (qty_low * price) >= 15000.0


def test_paper_trading_active_during_development_stage():
    """Verify paper trading actively trades and causes capital to fluctuate during development stream."""
    state.reset_capital()
    state.is_running = True
    config.DEMO_MODE = False
    config.SUBMIT_LIVE_ORDERS = False
    state.sim_stage = "development"
    state.sim_status = "RUNNING"

    # Send an oversold tick for AERX (RSI <= 30)
    history = [{"date": f"2026-03-{i:02d}", "open": 700.0 - i * 3, "high": 705.0 - i * 3, "low": 690.0 - i * 3, "close": 695.0 - i * 3, "volume": 100000} for i in range(1, 25)]
    state.price_history["AERX"] = history

    tick = {
        "ticker": "AERX",
        "open": 620.0,
        "high": 630.0,
        "low": 618.0,
        "close": 627.33,
        "volume": 1200000
    }
    strategy.on_price_tick(tick, simulated_date="2026-03-26")

    # Capital must have fluctuated!
    assert len(state.order_log) > 0
    latest_ord = state.order_log[-1]
    assert latest_ord["status"] == "FILLED"
    assert latest_ord["ticker"] == "AERX"
    assert latest_ord["action"] == "BUY"

    # Available cash must have decreased from ₹10,00,000
    assert state.available_cash < 1_000_000.0
    assert "AERX" in state.holdings
    assert state.holdings["AERX"]["quantity"] > 0

    # Cleanup
    state.sim_stage = "disconnected"
    state.sim_status = "OFFLINE"
    config.DEMO_MODE = True

