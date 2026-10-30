import pytest
from engine.indicators import TechnicalIndicators


def test_moving_averages_calculation():
    prices = [100.0, 102.0, 104.0, 106.0, 108.0]
    fast_ma = TechnicalIndicators.calculate_ma(prices, period=5)
    assert fast_ma == 104.0

    short_prices = [100.0, 102.0]
    assert TechnicalIndicators.calculate_ma(short_prices, period=5) is None


def test_3day_drop_calculation():
    # 4 prices: start is 100, then drops to 95 -> -5% drop
    prices = [100.0, 98.0, 96.0, 95.0]
    drop = TechnicalIndicators.calculate_3day_drop(prices)
    assert drop == -5.0


def test_mean_reversion_dip_signal():
    # Drop of > 4% in 3 days triggers oversold BUY
    prices = [100.0, 98.0, 96.0, 94.0]
    res = TechnicalIndicators.evaluate_signals(prices, current_news_sentiment="NEUTRAL")
    assert res["signal"] == "BUY"
    assert "Oversold Dip" in res["reason"]


def test_bearish_news_vetoes_buy():
    # Dip with bad news should not buy
    prices = [100.0, 98.0, 96.0, 94.0]
    res = TechnicalIndicators.evaluate_signals(prices, current_news_sentiment="BEARISH")
    assert res["signal"] != "BUY"


def test_rsi_overbought_filter_blocks_golden_cross():
    # Build price series with an exact Golden Cross where RSI >= 70
    # prev_fast (99.6) <= prev_slow (99.9), but current fast (101.6) > slow (100.4) with RSI 85.7
    prices = [100.0] * 16 + [98.0, 99.0, 100.0, 101.0, 110.0]
    res = TechnicalIndicators.evaluate_signals(prices, current_news_sentiment="NEUTRAL")
    assert res["rsi"] is not None
    assert res["rsi"] >= 70.0
    # Overbought RSI should prevent a BUY entry at the market top
    assert res["signal"] != "BUY"
    assert res["signal"] == "HOLD_LONG"
    assert "High RSI" in res["reason"]

