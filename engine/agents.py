import os
import time
import math
import json
import logging
import urllib.request
from typing import Dict, Any, Optional, List, Tuple

from engine.config import config
from engine.indicators import TechnicalIndicators
from engine.sentiment_analyzer import sentiment_analyzer

logger = logging.getLogger("MultiAgentHub")


class AgnesAnalyst:
    """
    Agnes: Quantitative Market & Sentiment Intelligence Analyst for MANTHAN 2026.
    Analyzes live Kafka price series, moving averages, momentum (RSI), 3-day drops,
    and same-day corporate news sentiment to produce structured numerical analysis and briefs.
    Distinguishes live Kafka events from demo/mock data and guards against stale events.
    """

    def __init__(self):
        self.name = "Agnes"
        self.role = "Market & Sentiment Intelligence Analyst"

    def analyze(
        self,
        ticker: str,
        current_price: float,
        price_history: List[Dict[str, Any]],
        news_feed: List[Dict[str, Any]],
        simulated_date: str = "",
        event_timestamp: str = "",
        event_source: str = "LIVE_KAFKA",
    ) -> Dict[str, Any]:
        """
        Synthesizes technical indicators and corporate news sentiment into a comprehensive market brief.
        """
        start_time = time.time()
        analysis_ts = time.strftime("%H:%M:%S")

        # Normalize event timestamp
        if not event_timestamp:
            event_timestamp = time.strftime("%H:%M:%S")
        elif "T" in event_timestamp:
            try:
                # Extract HH:MM:SS from ISO timestamp
                event_timestamp = event_timestamp.split("T")[1].split(".")[0]
            except Exception:
                pass

        # Price validation
        if (
            current_price is None
            or isinstance(current_price, bool)
            or not isinstance(current_price, (int, float))
            or not math.isfinite(current_price)
            or current_price <= 0
        ):
            latency = (time.time() - start_time) * 1000.0
            return {
                "agent": self.name,
                "ticker": ticker,
                "is_valid": False,
                "error": f"Invalid price data: {current_price}",
                "current_price": None,
                "event_source": event_source,
                "event_timestamp": event_timestamp,
                "analysis_timestamp": analysis_ts,
                "processing_latency_ms": round(latency, 2),
                "trend_direction": "UNKNOWN",
                "rsi": None,
                "rsi_regime": "UNKNOWN",
                "drop_3d_pct": None,
                "sentiment": "NEUTRAL",
                "market_context": f"Price data for {ticker} is non-finite or invalid ({current_price}).",
            }

        closes = [p["close"] for p in price_history if "close" in p and math.isfinite(p["close"])]
        if not closes or closes[-1] != current_price:
            closes.append(current_price)

        # 1. Technical Indicators
        fast_ma = TechnicalIndicators.calculate_ma(closes, period=5)
        slow_ma = TechnicalIndicators.calculate_ma(closes, period=20)
        drop_3d = TechnicalIndicators.calculate_3day_drop(closes)
        rsi = TechnicalIndicators.calculate_rsi(closes, period=14)

        # Trend & Cross evaluation
        trend_direction = "NEUTRAL"
        is_golden_cross = False
        is_death_cross = False

        if fast_ma is not None and slow_ma is not None:
            if fast_ma > slow_ma:
                trend_direction = "BULLISH"
            elif fast_ma < slow_ma:
                trend_direction = "BEARISH"

            # Check crossover using previous bar
            if len(closes) >= 21:
                prev_fast = TechnicalIndicators.calculate_ma(closes[:-1], period=5)
                prev_slow = TechnicalIndicators.calculate_ma(closes[:-1], period=20)
                if prev_fast is not None and prev_slow is not None:
                    if prev_fast <= prev_slow and fast_ma > slow_ma:
                        is_golden_cross = True
                    elif prev_fast >= prev_slow and fast_ma < slow_ma:
                        is_death_cross = True

        # RSI Regime
        rsi_regime = "NEUTRAL"
        if rsi is not None:
            if rsi >= 70.0:
                rsi_regime = "OVERBOUGHT"
            elif rsi <= 30.0:
                rsi_regime = "OVERSOLD"

        # 2. Corporate News Sentiment (strictly scoped to current simulated date)
        matched_news = None
        recent_sentiment = "NEUTRAL"
        news_score = 0.0
        news_headline = ""

        for news in reversed(news_feed):
            if news.get("ticker") == ticker:
                news_date = news.get("date")
                if not simulated_date or not news_date or news_date == simulated_date:
                    matched_news = news
                    recent_sentiment = news.get("sentiment", "NEUTRAL")
                    news_score = float(news.get("score", 0.0))
                    news_headline = news.get("headline", "")
                    break

        # 3. Analytical Synthesis Brief
        context_parts = [
            f"Asset {ticker} trades at ₹{current_price:,.2f} on {simulated_date or 'latest tick'}.",
        ]

        if fast_ma and slow_ma:
            cross_desc = "Golden Cross (Bullish breakout)" if is_golden_cross else ("Death Cross (Bearish breakdown)" if is_death_cross else f"Trend {trend_direction}")
            context_parts.append(f"Fast MA(5) ₹{fast_ma} vs Slow MA(20) ₹{slow_ma} [{cross_desc}].")

        if drop_3d is not None:
            context_parts.append(f"3-Day price change: {drop_3d:+.2f}%.")

        if rsi is not None:
            context_parts.append(f"14-Period RSI: {rsi:.1f} ({rsi_regime}).")

        if matched_news:
            context_parts.append(f"News Flash ({recent_sentiment}, score {news_score:+.2f}): '{news_headline}'.")
        else:
            context_parts.append("No active news catalyst for current session.")

        market_context = " ".join(context_parts)
        latency = (time.time() - start_time) * 1000.0

        return {
            "agent": self.name,
            "ticker": ticker,
            "is_valid": True,
            "current_price": current_price,
            "event_source": event_source,
            "event_timestamp": event_timestamp,
            "analysis_timestamp": analysis_ts,
            "processing_latency_ms": round(latency, 2),
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "trend_direction": trend_direction,
            "is_golden_cross": is_golden_cross,
            "is_death_cross": is_death_cross,
            "rsi": rsi,
            "rsi_regime": rsi_regime,
            "drop_3d_pct": drop_3d,
            "sentiment": recent_sentiment,
            "sentiment_score": news_score,
            "news_headline": news_headline,
            "market_context": market_context,
            "simulated_date": simulated_date,
        }


class JeffDecisionAgent:
    """
    Jeff: Strategic Decision Agent for MANTHAN 2026.
    Takes Agnes's analytical brief and recommends BUY, SELL, or HOLD
    with calibrated confidence and an executive rationale.
    
    Performance & Efficiency Optimization:
    - Avoids unnecessary LLM calls on every incoming tick.
    - Evaluates when meaningful market conditions change:
      crossovers, dip threshold breaches, RSI regime flips, new news catalysts,
      or significant price movement (>= 1.0%).
    - Automatically falls back to deterministic decision logic on LLM timeout (1.5s) or error.
    """

    def __init__(self):
        self.name = "Jeff"
        self.role = "Strategic Decision Agent"
        self.llm_timeout_seconds = 1.5
        self.last_decisions: Dict[str, Dict[str, Any]] = {}

    def has_market_condition_changed(
        self,
        ticker: str,
        agnes_report: Dict[str, Any],
        current_holding: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Determines whether market conditions have meaningfully changed since last decision,
        preventing redundant LLM calls or duplicate evaluations.
        """
        cached = self.last_decisions.get(ticker)
        if not cached:
            return True, "Initial analysis for ticker"

        # 1. Structural Signal Crossover / Dip Events
        if agnes_report.get("is_golden_cross") and not cached.get("was_golden_cross", False):
            return True, "Bullish Golden Cross breakout detected"

        if agnes_report.get("is_death_cross") and not cached.get("was_death_cross", False):
            return True, "Bearish Death Cross breakdown detected"

        drop_3d = agnes_report.get("drop_3d_pct")
        last_drop = cached.get("last_drop_3d")
        if drop_3d is not None:
            if drop_3d <= -4.0 and (last_drop is None or last_drop > -4.0):
                return True, f"Oversold 3-day dip entered ({drop_3d:+.1f}%)"
            elif drop_3d > -4.0 and (last_drop is not None and last_drop <= -4.0):
                return True, "Oversold dip recovered"

        # 2. RSI Regime Shift
        curr_rsi_regime = agnes_report.get("rsi_regime", "NEUTRAL")
        if curr_rsi_regime != cached.get("last_rsi_regime", "NEUTRAL"):
            return True, f"RSI regime shifted to {curr_rsi_regime}"

        # 3. New Corporate News catalyst
        curr_headline = agnes_report.get("news_headline", "")
        if curr_headline and curr_headline != cached.get("last_news_headline", ""):
            return True, f"Fresh corporate news catalyst: '{curr_headline[:40]}...'"

        # 4. Significant Price Movement (>= 1.0% since last decided price)
        curr_price = agnes_report.get("current_price", 0.0)
        last_price = cached.get("last_price", 0.0)
        if last_price > 0 and curr_price > 0:
            move_pct = abs(curr_price - last_price) / last_price * 100.0
            if move_pct >= 1.0:
                return True, f"Price moved {move_pct:.1f}% from last decision price"

        # 5. Position Quantity Changed (fill or exit)
        curr_qty = current_holding.get("quantity", 0)
        if curr_qty != cached.get("last_qty", 0):
            return True, f"Holding quantity changed to {curr_qty}"

        # 6. Periodic Heartbeat Refresh (>= 60 seconds)
        if (time.time() - cached.get("last_decision_epoch", 0.0)) >= 60.0:
            return True, "Periodic 60-second strategy review"

        return False, "Market conditions unchanged"

    def decide(
        self,
        agnes_report: Dict[str, Any],
        current_holding: Dict[str, Any],
        simulated_date: str = "",
    ) -> Dict[str, Any]:
        """
        Formulates an actionable recommendation (BUY, SELL, or HOLD) based on Agnes's report.
        """
        start_time = time.time()
        ticker = agnes_report.get("ticker", "UNKNOWN")
        event_src = agnes_report.get("event_source", "LIVE_KAFKA")
        event_ts = agnes_report.get("event_timestamp", time.strftime("%H:%M:%S"))
        analysis_ts = agnes_report.get("analysis_timestamp", time.strftime("%H:%M:%S"))

        # Check for Agnes validity
        if not agnes_report.get("is_valid", False):
            latency = (time.time() - start_time) * 1000.0
            return {
                "agent": self.name,
                "ticker": ticker,
                "action": "HOLD",
                "confidence": 0.0,
                "explanation": f"Decision withheld: {agnes_report.get('error', 'Invalid market brief')}",
                "provider": "DETERMINISTIC_FALLBACK",
                "event_source": event_src,
                "event_timestamp": event_ts,
                "analysis_timestamp": analysis_ts,
                "decision_latency_ms": round(latency, 2),
                "condition_change_reason": "Invalid market brief",
                "timestamp": time.strftime("%H:%M:%S"),
            }

        # Check if meaningful market condition changed
        changed, change_reason = self.has_market_condition_changed(ticker, agnes_report, current_holding)

        # If conditions are unchanged, reuse cached decision without invoking LLM
        if not changed:
            cached = self.last_decisions.get(ticker)
            if cached:
                latency = (time.time() - start_time) * 1000.0
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": cached["action"],
                    "confidence": cached["confidence"],
                    "explanation": cached["explanation"],
                    "provider": cached["provider"],
                    "event_source": event_src,
                    "event_timestamp": event_ts,
                    "analysis_timestamp": analysis_ts,
                    "decision_latency_ms": round(latency, 2),
                    "condition_change_reason": "Unchanged (Cached)",
                    "timestamp": time.strftime("%H:%M:%S"),
                }

        # Attempt LLM evaluation only when conditions meaningfully changed
        decision_record = self._try_llm_decision(agnes_report, current_holding)
        if decision_record is None:
            # Deterministic Fallback Engine
            decision_record = self._deterministic_decision(agnes_report, current_holding)

        latency = (time.time() - start_time) * 1000.0
        decision_record["decision_latency_ms"] = round(latency, 2)
        decision_record["event_source"] = event_src
        decision_record["event_timestamp"] = event_ts
        decision_record["analysis_timestamp"] = analysis_ts
        decision_record["condition_change_reason"] = change_reason
        decision_record["timestamp"] = time.strftime("%H:%M:%S")

        # Cache decision state for subsequent tick evaluations
        self.last_decisions[ticker] = {
            "action": decision_record["action"],
            "confidence": decision_record["confidence"],
            "explanation": decision_record["explanation"],
            "provider": decision_record["provider"],
            "last_price": agnes_report.get("current_price", 0.0),
            "last_drop_3d": agnes_report.get("drop_3d_pct"),
            "last_rsi_regime": agnes_report.get("rsi_regime", "NEUTRAL"),
            "last_news_headline": agnes_report.get("news_headline", ""),
            "last_qty": current_holding.get("quantity", 0),
            "was_golden_cross": agnes_report.get("is_golden_cross", False),
            "was_death_cross": agnes_report.get("is_death_cross", False),
            "last_decision_epoch": time.time(),
        }

        return decision_record

    def _try_llm_decision(
        self,
        agnes_report: Dict[str, Any],
        current_holding: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Calls external or local LLM endpoint if configured in environment.
        Gracefully returns None on timeouts (1.5s), connection errors, or malformed JSON.
        """
        provider = getattr(config, "LLM_PROVIDER", None) or os.getenv("LLM_PROVIDER")
        api_url = getattr(config, "LLM_API_URL", None) or os.getenv("LLM_API_URL")
        api_key = getattr(config, "LLM_API_KEY", None) or os.getenv("LLM_API_KEY")

        if not provider or not api_url:
            return None

        prompt = (
            f"You are Jeff, the Strategic Trading Decision Agent for MANTHAN 2026. "
            f"Analyze this quantitative brief from Agnes and recommend BUY, SELL, or HOLD.\n\n"
            f"Market Brief:\n{agnes_report.get('market_context', '')}\n\n"
            f"Current Position:\nQuantity: {current_holding.get('quantity', 0)}, "
            f"Avg Price: ₹{current_holding.get('avg_price', 0.0)}\n\n"
            f"Return strictly valid JSON:\n"
            f"{{\"action\": \"BUY\"|\"SELL\"|\"HOLD\", \"confidence\": float (0.0 to 1.0), \"explanation\": \"short sentence\"}}"
        )

        try:
            req_data = json.dumps({
                "prompt": prompt,
                "max_tokens": 100,
                "temperature": 0.1
            }).encode("utf-8")

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            req = urllib.request.Request(api_url, data=req_data, headers=headers)
            with urllib.request.urlopen(req, timeout=self.llm_timeout_seconds) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                content = resp_json.get("response") or resp_json.get("text") or resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = json.loads(content)

                action = str(parsed.get("action", "HOLD")).upper()
                if action not in ["BUY", "SELL", "HOLD"]:
                    action = "HOLD"

                confidence = float(parsed.get("confidence", 0.5))
                confidence = max(0.0, min(1.0, confidence))
                explanation = str(parsed.get("explanation", "LLM strategy recommendation"))

                return {
                    "agent": self.name,
                    "ticker": agnes_report["ticker"],
                    "action": action,
                    "confidence": round(confidence, 2),
                    "explanation": f"[LLM-{provider}] {explanation}",
                    "provider": f"LLM_{provider.upper()}",
                }
        except Exception as e:
            logger.debug(f"LLM call timed out / unavailable ({type(e).__name__}). Using deterministic fallback.")
            return None

    def _deterministic_decision(
        self,
        agnes: Dict[str, Any],
        holding: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        High-performance quantitative decision engine enforcing MANTHAN 2026 rule hierarchy.
        """
        ticker = agnes["ticker"]
        current_qty = holding.get("quantity", 0)
        pos_type = holding.get("position_type", "LONG")
        is_holding_long = current_qty > 0 and pos_type == "LONG"

        drop_3d = agnes.get("drop_3d_pct")
        sentiment = agnes.get("sentiment", "NEUTRAL")
        is_golden_cross = agnes.get("is_golden_cross", False)
        is_death_cross = agnes.get("is_death_cross", False)
        rsi = agnes.get("rsi")
        fast_ma = agnes.get("fast_ma")
        slow_ma = agnes.get("slow_ma")

        # 1. Extreme 3-Day Oversold Dip (Mean Reversion Strategy 2)
        if drop_3d is not None and drop_3d <= -4.0:
            if sentiment == "BEARISH":
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "HOLD",
                    "confidence": 0.80,
                    "explanation": f"Oversold dip ({drop_3d:+.1f}%) vetoed by adverse news sentiment ('{agnes.get('news_headline', '')}'). Avoiding falling knife.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }
            else:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "BUY",
                    "confidence": 0.85,
                    "explanation": f"Agnes confirmed oversold dip ({drop_3d:+.1f}% in 3 days) with non-negative news. High-probability mean-reversion rebound.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }

        # 1b. Deep RSI Oversold Mean-Reversion (Strategy 2 Extension)
        if rsi is not None and rsi <= 30.0 and not is_holding_long:
            if sentiment == "BEARISH":
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "HOLD",
                    "confidence": 0.75,
                    "explanation": f"Oversold RSI ({rsi:.1f} <= 30) vetoed by adverse news sentiment ('{agnes.get('news_headline', '')}'). Avoiding falling knife.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }
            else:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "BUY",
                    "confidence": 0.80,
                    "explanation": f"Agnes confirmed deep oversold RSI ({rsi:.1f} <= 30) with non-negative news. High-probability mean-reversion rebound.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }

        # 2. Moving Average Golden Cross (Trend Following Strategy 1)
        if is_golden_cross:
            # Overbought RSI Guard
            if rsi is not None and rsi >= 70.0:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "HOLD",
                    "confidence": 0.65,
                    "explanation": f"Golden Cross active (Fast MA ₹{fast_ma} > Slow MA ₹{slow_ma}), but entry blocked by overbought RSI ({rsi:.1f} >= 70). Preserving capital.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }
            elif sentiment == "BEARISH":
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "HOLD",
                    "confidence": 0.75,
                    "explanation": f"Golden Cross vetoed by bearish corporate news ('{agnes.get('news_headline', '')}'). Standing aside.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }
            else:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "BUY",
                    "confidence": 0.75,
                    "explanation": f"Agnes confirmed Bullish Golden Cross (Fast MA ₹{fast_ma} crossed Slow MA ₹{slow_ma}) with healthy RSI {rsi or 50.0:.1f}. Trend entry initiated.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }

        # 3. Moving Average Death Cross (Trend Breakdown)
        if is_death_cross:
            if is_holding_long:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "SELL",
                    "confidence": 0.75,
                    "explanation": f"Agnes confirmed Bearish Death Cross (Fast MA ₹{fast_ma} crossed below Slow MA ₹{slow_ma}). Exiting {current_qty} long shares to preserve capital.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }
            elif sentiment == "BEARISH" and current_qty == 0:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "SHORT",
                    "confidence": 0.75,
                    "explanation": f"Agnes confirmed Bearish Death Cross breakdown with adverse news sentiment ('{agnes.get('news_headline', '')}'). Entering short to capture downward alpha.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }
            else:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "HOLD",
                    "confidence": 0.70,
                    "explanation": f"Bearish Death Cross active, but no long position is currently held. Maintaining cash.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }

        # 4. Same-Day Bullish News Catalyst (Strategy 3)
        if sentiment == "BULLISH" and not is_holding_long:
            if rsi is not None and rsi < 70.0:
                return {
                    "agent": self.name,
                    "ticker": ticker,
                    "action": "BUY",
                    "confidence": 0.70,
                    "explanation": f"Positive news catalyst confirmed ('{agnes.get('news_headline', '')}') with momentum intact (RSI {rsi:.1f}). Initiating news momentum buy.",
                    "provider": "DETERMINISTIC_FALLBACK",
                }

        # 5. Default Baseline Hold
        return {
            "agent": self.name,
            "ticker": ticker,
            "action": "HOLD",
            "confidence": 0.50,
            "explanation": f"Agnes reports market in consolidation ({agnes.get('trend_direction', 'NEUTRAL')}, RSI {rsi or 50.0:.1f}). No asymmetric edge; holding.",
            "provider": "DETERMINISTIC_FALLBACK",
        }


# Global singleton agent instances
agnes = AgnesAnalyst()
jeff = JeffDecisionAgent()
