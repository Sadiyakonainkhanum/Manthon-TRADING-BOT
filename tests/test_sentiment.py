import pytest
from engine.sentiment_analyzer import sentiment_analyzer


def test_bullish_sentiment():
    headline = "ALPHACORP Q3 NET PROFIT SURGES 24% YOY ON RECORD EXPANSION"
    sentiment, score, details = sentiment_analyzer.analyze(headline)
    assert sentiment == "BULLISH"
    assert score > 0.0
    assert "PROFIT" in details["bullish_matches"]
    assert "SURGE" in details["bullish_matches"]
    assert "RECORD" in details["bullish_matches"]


def test_bearish_sentiment():
    headline = "REGULATORY SCRUTINY AND AUDIT PROBE INTO MANUFACTURING LOSS"
    sentiment, score, details = sentiment_analyzer.analyze(headline)
    assert sentiment == "BEARISH"
    assert score < 0.0
    assert "LOSS" in details["bearish_matches"]
    assert "SCRUTINY" in details["bearish_matches"]
    assert "PROBE" in details["bearish_matches"]


def test_neutral_sentiment():
    headline = "COMPANY SCHEDULES ANNUAL GENERAL MEETING FOR NEXT MONTH"
    sentiment, score, details = sentiment_analyzer.analyze(headline)
    assert sentiment == "NEUTRAL"
    assert score == 0.0
    assert len(details["bullish_matches"]) == 0
    assert len(details["bearish_matches"]) == 0

