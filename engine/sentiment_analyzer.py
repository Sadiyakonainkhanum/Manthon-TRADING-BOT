import re
from typing import Dict, Any, Tuple

# Official MANTHAN 2026 Strategy 3 Keywords
BULLISH_KEYWORDS = [
    "PROFIT", "SURGE", "GROWTH", "RECORD", "BEAT", 
    "EXPANSION", "DIVIDEND", "PARTNERSHIP", "ACQUISITION", 
    "OUTPERFORM", "ORDER WIN", "BULLISH", "UPGRADE"
]

BEARISH_KEYWORDS = [
    "LOSS", "PLUNGE", "DROP", "FRAUD", "SCRUTINY", 
    "RESIGNATION", "PROBE", "DOWNGRADE", "SLUMP", 
    "INVESTIGATION", "PENALTY", "DEFAULT", "BEARISH"
]


class SentimentAnalyzer:
    """Analyzes headline and description text based on the official keyword matching rules."""

    def __init__(self):
        self.bullish_patterns = [re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE) for word in BULLISH_KEYWORDS]
        self.bearish_patterns = [re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE) for word in BEARISH_KEYWORDS]

    def analyze(self, headline: str, description: str = "") -> Tuple[str, float, Dict[str, Any]]:
        """
        Analyzes the headline (and optionally description).
        Returns:
            sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
            score: normalized float between -1.0 and +1.0
            details: matched keywords and occurrences
        """
        text = f"{headline} {description}".upper()

        matched_bullish = []
        for word in BULLISH_KEYWORDS:
            if re.search(r'\b' + re.escape(word) + r'[A-Z]*\b', text):
                matched_bullish.append(word)

        matched_bearish = []
        for word in BEARISH_KEYWORDS:
            if re.search(r'\b' + re.escape(word) + r'[A-Z]*\b', text):
                matched_bearish.append(word)

        pos_count = len(matched_bullish)
        neg_count = len(matched_bearish)

        if pos_count > neg_count:
            sentiment = "BULLISH"
            score = round((pos_count - neg_count) / max(1, pos_count + neg_count), 2)
        elif neg_count > pos_count:
            sentiment = "BEARISH"
            score = round((pos_count - neg_count) / max(1, pos_count + neg_count), 2)
        else:
            sentiment = "NEUTRAL"
            score = 0.0

        details = {
            "bullish_matches": matched_bullish,
            "bearish_matches": matched_bearish,
            "positive_count": pos_count,
            "negative_count": neg_count
        }

        return sentiment, score, details


sentiment_analyzer = SentimentAnalyzer()

