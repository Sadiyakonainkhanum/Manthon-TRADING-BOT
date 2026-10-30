from typing import List, Dict, Optional, Tuple, Any
import numpy as np


class TechnicalIndicators:
    """Computes moving averages, momentum, mean reversion, and RSI on OHLCV series."""

    @staticmethod
    def calculate_ma(prices: List[float], period: int) -> Optional[float]:
        if len(prices) < period:
            return None
        return round(float(np.mean(prices[-period:])), 2)

    @staticmethod
    def calculate_3day_drop(prices: List[float]) -> Optional[float]:
        """Calculates percentage change over the last 3 days."""
        if len(prices) < 4:
            return None
        p_start = prices[-4]
        p_now = prices[-1]
        if p_start <= 0:
            return None
        pct_change = (p_now - p_start) / p_start * 100.0
        return round(pct_change, 2)

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        """Calculates 14-period Relative Strength Index."""
        if len(prices) < period + 1:
            return None

        diffs = np.diff(prices[-period - 1:])
        gains = np.maximum(diffs, 0)
        losses = np.abs(np.minimum(diffs, 0))

        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return round(float(rsi), 2)

    @classmethod
    def evaluate_signals(cls, prices: List[float], current_news_sentiment: str = "NEUTRAL") -> Dict[str, Any]:
        """
        Evaluates Strategy 1 (MA Crossover), Strategy 2 (Mean Reversion), and Strategy 3 (News).
        Returns calculated indicators and final action recommendation.
        """
        if len(prices) < 4:
            return {
                "fast_ma": None,
                "slow_ma": None,
                "rsi": None,
                "drop_3d_pct": None,
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": "Insufficient price history buffer (<4 days)"
            }

        fast_ma = cls.calculate_ma(prices, period=5)
        slow_ma = cls.calculate_ma(prices, period=20)
        drop_3d = cls.calculate_3day_drop(prices)
        rsi = cls.calculate_rsi(prices, period=14)

        # Signal logic synthesis
        signal = "HOLD"
        reason = "No clear directional breakout or mean reversion trigger"
        confidence = 0.5

        # 1. Mean Reversion Trigger (Strategy 2)
        if drop_3d is not None and drop_3d <= -4.0:
            if current_news_sentiment != "BEARISH":
                signal = "BUY"
                reason = f"Oversold Dip: Stock dropped {abs(drop_3d)}% in 3 days with no negative news."
                confidence = 0.85
                return {
                    "fast_ma": fast_ma,
                    "slow_ma": slow_ma,
                    "rsi": rsi,
                    "drop_3d_pct": drop_3d,
                    "signal": signal,
                    "confidence": confidence,
                    "reason": reason
                }

        # 2. Moving Average Crossover (Strategy 1)
        if fast_ma is not None and slow_ma is not None:
            # Check previous MA to detect crossover
            prev_prices = prices[:-1]
            prev_fast = cls.calculate_ma(prev_prices, period=5)
            prev_slow = cls.calculate_ma(prev_prices, period=20)

            if prev_fast is not None and prev_slow is not None:
                # Bullish Crossover (Golden Cross)
                if prev_fast <= prev_slow and fast_ma > slow_ma:
                    if rsi is not None and rsi >= 70.0:
                        signal = "HOLD_LONG"
                        reason = f"MA Bullish Cross with High RSI ({rsi:.1f}): Holding to avoid overbought top"
                        confidence = 0.60
                    else:
                        signal = "BUY"
                        reason = f"MA Crossover: Fast MA (₹{fast_ma}) crossed above Slow MA (₹{slow_ma})"
                        confidence = 0.75
                # Bearish Cross (Death Cross)
                elif prev_fast >= prev_slow and fast_ma < slow_ma:
                    signal = "SELL"
                    reason = f"MA Crossover: Fast MA (₹{fast_ma}) crossed below Slow MA (₹{slow_ma})"
                    confidence = 0.75
                elif fast_ma > slow_ma:
                    # In positive momentum
                    signal = "HOLD_LONG"
                    reason = f"Bullish trend maintained (Fast MA ₹{fast_ma} > Slow MA ₹{slow_ma})"
                    confidence = 0.6
                else:
                    signal = "HOLD_NEUTRAL"
                    reason = f"Weak trend (Fast MA ₹{fast_ma} < Slow MA ₹{slow_ma})"
                    confidence = 0.6

        # 3. News Sentiment Overlay (Strategy 3)
        if current_news_sentiment == "BULLISH":
            if signal in ("BUY", "HOLD_LONG", "HOLD"):
                signal = "BUY"
                reason = f"Strong Bullish News Catalyst aligns with trend ({reason})"
                confidence = 0.90
        elif current_news_sentiment == "BEARISH":
            if signal == "BUY":
                signal = "HOLD"
                reason = "News Bearish Warning: Buy signal vetoed due to adverse headlines"
                confidence = 0.70
            elif signal in ("SELL", "HOLD_NEUTRAL", "HOLD"):
                signal = "SHORT"
                reason = "Bearish News Trigger: Initiating short exposure on negative disclosures"
                confidence = 0.80

        return {
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "rsi": rsi,
            "drop_3d_pct": drop_3d,
            "signal": signal,
            "confidence": confidence,
            "reason": reason
        }
