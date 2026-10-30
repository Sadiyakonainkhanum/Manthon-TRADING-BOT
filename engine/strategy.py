import time
import math
import logging
from typing import Dict, Any, Optional
from engine.config import config
from engine.state import state
from engine.indicators import TechnicalIndicators
from engine.sentiment_analyzer import sentiment_analyzer
from engine.execution_engine import execution_engine
from engine.risk_manager import risk_manager
from engine.agents import agnes, jeff

logger = logging.getLogger(__name__)


class TradingStrategy:
    """Multi-signal quantitative strategy integrating Moving Averages, Mean Reversion, and Sentiment."""

    def __init__(self):
        self.default_order_size = 50  # Fallback batch size

    def calculate_buy_quantity(
        self,
        ticker: str,
        current_price: float,
        simulated_date: str = "",
        confidence: Optional[float] = None,
    ) -> int:
        """
        Dynamically computes conservative order quantity for a BUY order:
        - Target allocation: dynamically scales around baseline 3% (e.g. 2.0% - 4.5%)
          proportional to real-time confidence and market analysis strength.
        - Single stock concentration cap: strictly <= 25% of portfolio wealth including existing holdings
        - Cash cushion preservation: strictly preserves >= 20% of portfolio wealth in available cash after trade + fees
        - Discards invalid/stale prices (<= 0, NaN, non-numeric)
        - Truncates to whole integer shares
        - Skips micro-trades below config.MIN_TRADE_VALUE (₹5,000) to prevent fee erosion
        - Thread-safe and race-condition resilient via state.lock
        """
        if (
            current_price is None
            or isinstance(current_price, bool)
            or not isinstance(current_price, (int, float))
            or not math.isfinite(current_price)
            or current_price <= 0
        ):
            logger.warning(f"Position sizing rejected for {ticker}: Invalid or non-positive price ({current_price})")
            return 0

        # Duplicate order pre-check
        if simulated_date and f"{ticker}:{simulated_date}" in state.daily_executed_orders:
            return 0

        with state.lock:
            metrics = state.compute_wealth_metrics()
            total_wealth = metrics["total_wealth"]
            available_cash = metrics["available_cash"]

            if total_wealth <= 0 or available_cash <= 0:
                return 0

            base_target_pct = getattr(config, "TARGET_ALLOCATION_PCT", 0.03)

            # Dynamic capital fluctuation based on real-time analysis confidence & idle cash
            if confidence is not None and confidence > 0:
                scale_factor = max(0.67, min(1.35, confidence / 0.75))
                # In live trading with surplus cash (>35%), boost allocation on confident signals (up to 5.5% - 7.5%)
                if not state.is_demo_mode and available_cash > (total_wealth * 0.35):
                    cash_utilization_boost = min(2.1, 1.0 + (available_cash / total_wealth))
                else:
                    cash_utilization_boost = 1.0
                target_pct = base_target_pct * scale_factor * cash_utilization_boost
            else:
                target_pct = base_target_pct

            max_conc_pct = getattr(config, "MAX_STOCK_CONCENTRATION_PCT", 0.25)
            min_cash_pct = getattr(config, "MIN_CASH_BUFFER_PCT", 0.20)
            brokerage = getattr(config, "BROKERAGE_PER_ORDER", 20.00)
            min_trade_val = getattr(config, "MIN_TRADE_VALUE", 5000.0)

            # 1. Target allocation amount in currency (fluctuates with real-time analysis)
            target_amount = total_wealth * target_pct

            # 2. Single-stock concentration limit headroom
            existing_pos = state.holdings.get(ticker, {})
            existing_val = 0.0
            if existing_pos.get("position_type") == "LONG":
                existing_val = existing_pos.get("quantity", 0) * current_price

            conc_headroom = max(0.0, (total_wealth * max_conc_pct) - existing_val)

            # 3. Liquid cash reserve headroom (preserves at least 20% cash after cost + brokerage fee)
            min_cash_reserve = total_wealth * min_cash_pct
            cash_headroom = max(0.0, available_cash - min_cash_reserve - brokerage)

            # 4. Deployable capital is the most restrictive constraint
            deployable_capital = min(target_amount, conc_headroom, cash_headroom)
            if deployable_capital <= 0:
                return 0

            # 5. Whole integer shares
            quantity = int(deployable_capital // current_price)
            if quantity <= 0:
                return 0

            # 6. Minimum trade value threshold to prevent fee drag
            trade_value = quantity * current_price
            if trade_value < min_trade_val:
                logger.info(
                    f"Position sizing for {ticker}: Trade value ₹{trade_value:,.2f} is below minimum threshold ₹{min_trade_val:,.2f}. Skipping."
                )
                return 0

            # 7. Final boundary safety check (accounting for brokerage)
            total_required = trade_value + brokerage
            if (available_cash - total_required) < min_cash_reserve:
                quantity -= 1
                if quantity <= 0 or (quantity * current_price) < min_trade_val:
                    return 0

            if ((existing_val + quantity * current_price) / total_wealth) > max_conc_pct:
                quantity -= 1
                if quantity <= 0 or (quantity * current_price) < min_trade_val:
                    return 0

            return quantity

    def on_price_tick(
        self,
        tick_data: Dict[str, Any],
        simulated_date: str = "",
        is_demo: bool = False,
        event_timestamp: str = "",
        event_source: str = "",
        **kwargs
    ):
        """Processes a price tick event from market.ticks."""
        if not simulated_date and "sim_date" in kwargs:
            simulated_date = kwargs["sim_date"]
        if not event_source:
            event_source = "DEMO_MOCK" if (is_demo or getattr(config, "DEMO_MODE", False)) else "LIVE_KAFKA"
        if not event_timestamp:
            event_timestamp = tick_data.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ")
        ticker = tick_data.get("ticker")
        if not ticker:
            return

        close_raw = tick_data.get("close")
        if close_raw is None:
            return
        try:
            close_price = float(close_raw)
        except (ValueError, TypeError):
            return
        if not math.isfinite(close_price) or close_price <= 0:
            return

        open_raw = tick_data.get("open")
        try:
            open_price = float(open_raw) if open_raw is not None else close_price
        except (ValueError, TypeError):
            open_price = close_price

        high_raw = tick_data.get("high")
        try:
            high_price = float(high_raw) if high_raw is not None else max(open_price, close_price)
        except (ValueError, TypeError):
            high_price = max(open_price, close_price)

        low_raw = tick_data.get("low")
        try:
            low_price = float(low_raw) if low_raw is not None else min(open_price, close_price)
        except (ValueError, TypeError):
            low_price = min(open_price, close_price)

        vol_raw = tick_data.get("volume")
        try:
            volume = int(vol_raw) if vol_raw is not None else 0
        except (ValueError, TypeError):
            volume = 0

        with state.lock:
            # 1. Update Market Prices
            state.market_prices[ticker] = {
                "ticker": ticker,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "date": simulated_date,
                "is_demo": is_demo,
                "event_source": event_source,
                "event_timestamp": event_timestamp,
                "updated_at": time.strftime("%H:%M:%S")
            }

            # 2. Append to rolling price buffer
            if ticker not in state.price_history:
                state.price_history[ticker] = []
            elif len(state.price_history[ticker]) == 1 and state.price_history[ticker][0].get("date") == "Awaiting Ticks":
                state.price_history[ticker] = []
            
            state.price_history[ticker].append({
                "date": simulated_date,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume
            })

            # Cap history buffer to 120 days
            if len(state.price_history[ticker]) > 120:
                state.price_history[ticker] = state.price_history[ticker][-120:]

            # 3. Multi-Agent Intelligence Hub: Agnes Analysis & Jeff Decision
            agnes_report = agnes.analyze(
                ticker=ticker,
                current_price=close_price,
                price_history=state.price_history[ticker],
                news_feed=state.news_feed,
                simulated_date=simulated_date,
                event_timestamp=event_timestamp,
                event_source=event_source,
            )

            current_pos = state.holdings.get(ticker, {})
            jeff_decision = jeff.decide(
                agnes_report=agnes_report,
                current_holding=current_pos,
                simulated_date=simulated_date,
            )

            # Record in state for telemetry and dashboard
            state.agent_decisions[ticker] = {
                "ticker": ticker,
                "event_source": jeff_decision.get("event_source", event_source),
                "event_timestamp": jeff_decision.get("event_timestamp", event_timestamp),
                "analysis_timestamp": jeff_decision.get("analysis_timestamp", time.strftime("%H:%M:%S")),
                "latency_ms": jeff_decision.get("decision_latency_ms", 0.0),
                "condition_change_reason": jeff_decision.get("condition_change_reason", "Updated"),
                "agnes": agnes_report,
                "jeff": jeff_decision,
                "updated_at": time.strftime("%H:%M:%S"),
                "simulated_date": simulated_date,
            }

            state.strategy_signals[ticker] = {
                "fast_ma": agnes_report.get("fast_ma"),
                "slow_ma": agnes_report.get("slow_ma"),
                "rsi": agnes_report.get("rsi"),
                "drop_3d_pct": agnes_report.get("drop_3d_pct"),
                "sentiment": agnes_report.get("sentiment"),
                "signal": jeff_decision.get("action"),
                "confidence": jeff_decision.get("confidence"),
                "reason": jeff_decision.get("explanation"),
                "provider": jeff_decision.get("provider"),
                "event_source": jeff_decision.get("event_source", event_source),
                "event_timestamp": jeff_decision.get("event_timestamp", event_timestamp),
                "analysis_timestamp": jeff_decision.get("analysis_timestamp", time.strftime("%H:%M:%S")),
                "latency_ms": jeff_decision.get("decision_latency_ms", 0.0),
                "condition_changed": jeff_decision.get("condition_change_reason", "Updated"),
                "updated_at": time.strftime("%H:%M:%S")
            }

        # 5. Check Stop Losses & Take Profits first
        exit_orders = risk_manager.check_stop_losses() + risk_manager.check_take_profits()
        for eo in exit_orders:
            target_ticker = eo["ticker"]
            with state.lock:
                target_info = state.market_prices.get(target_ticker, {})
                target_price = target_info.get("close")

            if target_price is None or not isinstance(target_price, (int, float)) or target_price <= 0:
                logger.warning(
                    f"Skipping exit execution for {target_ticker}: latest market price is missing or invalid ({target_price}). Awaiting fresh tick."
                )
                continue

            execution_engine.execute_order(
                ticker=target_ticker,
                action=eo["action"],
                quantity=eo["quantity"],
                current_price=float(target_price),
                simulated_date=simulated_date,
                strategy_reason=eo["reason"]
            )

        # 6. Check if Trading is active
        # Trading is active when stream status is RUNNING and stage is in ("simulation", "development")
        # allowing automated real-time strategy execution in both practice sandbox and official competition.
        is_stream_active = (
            str(state.sim_status).upper() == "RUNNING" and 
            str(state.sim_stage).lower() in ("simulation", "development")
        )

        can_trade = (
            state.is_running and 
            not state.emergency_stop and
            (state.is_demo_mode or is_stream_active)
        )

        if not can_trade:
            return

        pos = state.holdings.get(ticker, {})
        current_qty = pos.get("quantity", 0)
        pos_type = pos.get("position_type", "LONG")

        # 6b. End-of-Simulation Portfolio Unwinding (Problem Statement Section 5 & 7)
        # When simulation approaches its final day, automatically liquidate positions to pure cash
        # to lock in realized gains and avoid late-stage drawdown.
        is_unwinding = (
            str(state.sim_stage).lower() == "simulation" and
            state.sim_total_days > 0 and
            state.sim_days_completed >= (state.sim_total_days - 1)
        )

        if is_unwinding:
            if current_qty > 0:
                unwind_action = "SELL" if pos_type == "LONG" else "COVER"
                execution_engine.execute_order(
                    ticker=ticker,
                    action=unwind_action,
                    quantity=current_qty,
                    current_price=close_price,
                    simulated_date=simulated_date,
                    strategy_reason=f"[SIM_UNWIND] End-of-simulation portfolio liquidation (Day {state.sim_days_completed}/{state.sim_total_days}) to lock in pure cash profits"
                )
            return  # Strictly block new entries during unwinding phase

        signal = jeff_decision.get("action")
        confidence_val = float(jeff_decision.get("confidence", 0.75))
        confidence_pct = int(confidence_val * 100)
        provider_tag = jeff_decision.get("provider", "DETERMINISTIC")
        reason = f"[{provider_tag}] Jeff ({confidence_pct}% conf): {jeff_decision.get('explanation')}"

        if signal == "BUY":
            # If we hold a short, BUY will cover it, else open long
            if pos_type == "SHORT" and current_qty > 0:
                execution_engine.execute_order(
                    ticker=ticker,
                    action="COVER",
                    quantity=current_qty,
                    current_price=close_price,
                    simulated_date=simulated_date,
                    strategy_reason=f"Cover Short on BUY Signal: {reason}"
                )
            else:
                buy_qty = self.calculate_buy_quantity(
                    ticker,
                    close_price,
                    simulated_date=simulated_date,
                    confidence=confidence_val
                )
                if buy_qty > 0:
                    execution_engine.execute_order(
                        ticker=ticker,
                        action="BUY",
                        quantity=buy_qty,
                        current_price=close_price,
                        simulated_date=simulated_date,
                        strategy_reason=reason
                    )

        elif signal == "SELL" and pos_type == "LONG" and current_qty > 0:
            execution_engine.execute_order(
                ticker=ticker,
                action="SELL",
                quantity=current_qty,
                current_price=close_price,
                simulated_date=simulated_date,
                strategy_reason=reason
            )

        elif signal == "SHORT" and current_qty == 0:
            short_qty = self.calculate_buy_quantity(
                ticker,
                close_price,
                simulated_date=simulated_date,
                confidence=confidence_val
            )
            if short_qty > 0:
                execution_engine.execute_order(
                    ticker=ticker,
                    action="SHORT",
                    quantity=short_qty,
                    current_price=close_price,
                    simulated_date=simulated_date,
                    strategy_reason=reason
                )

    def on_news_flash(
        self,
        news_data: Dict[str, Any],
        is_demo: bool = False,
        event_timestamp: str = "",
        event_source: str = "",
        **kwargs
    ):
        """Processes a corporate news flash from market.news."""
        if not event_source:
            event_source = "DEMO_MOCK" if (is_demo or getattr(config, "DEMO_MODE", False)) else "LIVE_KAFKA"
        if not event_timestamp:
            event_timestamp = news_data.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ")
        ticker = news_data.get("ticker", "UNKNOWN")
        headline = news_data.get("headline", "")
        description = news_data.get("description", "")
        sim_date = news_data.get("date", news_data.get("simulated_date", time.strftime("%Y-%m-%d")))

        sentiment, score, details = sentiment_analyzer.analyze(headline, description)

        news_item = {
            "id": f"news_{int(time.time()*1000)}",
            "ticker": ticker,
            "headline": headline,
            "description": description,
            "date": sim_date,
            "sentiment": sentiment,
            "score": score,
            "matched_keywords": details.get("bullish_matches") if sentiment == "BULLISH" else details.get("bearish_matches"),
            "event_source": event_source,
            "event_timestamp": event_timestamp,
            "timestamp": time.strftime("%H:%M:%S"),
            "is_demo": is_demo
        }

        with state.lock:
            state.news_feed.append(news_item)
            if len(state.news_feed) > 100:
                state.news_feed = state.news_feed[-100:]

        # Reactive trading on news (arrives T + 150ms)
        if getattr(config, "SUBMIT_LIVE_ORDERS", False):
            is_stream_active = (
                str(state.sim_stage).lower() == "simulation" and 
                str(state.sim_status).upper() == "RUNNING"
            )
        else:
            is_stream_active = (
                str(state.sim_status).upper() == "RUNNING" and 
                str(state.sim_stage).lower() in ("simulation", "development")
            )

        can_trade = (
            state.is_running and 
            not state.emergency_stop and
            (state.is_demo_mode or is_stream_active)
        )

        if can_trade and ticker in state.market_prices:
            curr_p = state.market_prices[ticker]["close"]
            pos = state.holdings.get(ticker, {})

            # Multi-Agent evaluation of news flash in market context
            agnes_report = agnes.analyze(
                ticker=ticker,
                current_price=curr_p,
                price_history=state.price_history.get(ticker, []),
                news_feed=state.news_feed,
                simulated_date=sim_date,
                event_timestamp=event_timestamp,
                event_source=event_source,
            )
            jeff_decision = jeff.decide(
                agnes_report=agnes_report,
                current_holding=pos,
                simulated_date=sim_date,
            )

            with state.lock:
                state.agent_decisions[ticker] = {
                    "ticker": ticker,
                    "event_source": jeff_decision.get("event_source", event_source),
                    "event_timestamp": jeff_decision.get("event_timestamp", event_timestamp),
                    "analysis_timestamp": jeff_decision.get("analysis_timestamp", time.strftime("%H:%M:%S")),
                    "latency_ms": jeff_decision.get("decision_latency_ms", 0.0),
                    "condition_change_reason": jeff_decision.get("condition_change_reason", "News Catalyst"),
                    "agnes": agnes_report,
                    "jeff": jeff_decision,
                    "updated_at": time.strftime("%H:%M:%S"),
                    "simulated_date": sim_date,
                }

            news_action = jeff_decision.get("action")
            news_conf = float(jeff_decision.get("confidence", 0.75))
            news_reason = f"[{jeff_decision.get('provider')}] Jeff news reaction: {jeff_decision.get('explanation')}"

            if news_action == "BUY":
                buy_qty = self.calculate_buy_quantity(
                    ticker,
                    curr_p,
                    simulated_date=sim_date,
                    confidence=news_conf
                )
                if buy_qty > 0:
                    execution_engine.execute_order(
                        ticker=ticker,
                        action="BUY",
                        quantity=buy_qty,
                        current_price=curr_p,
                        simulated_date=sim_date,
                        strategy_reason=news_reason
                    )
            elif news_action == "SELL" and pos.get("position_type") == "LONG" and pos.get("quantity", 0) > 0:
                execution_engine.execute_order(
                    ticker=ticker,
                    action="SELL",
                    quantity=pos.get("quantity", 0),
                    current_price=curr_p,
                    simulated_date=sim_date,
                    strategy_reason=news_reason
                )


strategy = TradingStrategy()
