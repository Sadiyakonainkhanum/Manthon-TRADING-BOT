import logging
from typing import Dict, Any, List
from engine.config import config
from engine.state import state
from engine.api_client import api_client

logger = logging.getLogger(__name__)

# Fallback dynamic mock universe for DEMO mode
DEFAULT_DEMO_UNIVERSE = [
    {
        "ticker": "AERX",
        "symbol": "AERX",
        "name": "AeroVanguard Defense & Space Corp.",
        "description": "Aerospace manufacturing, precision defense avionics and orbital systems",
        "base_price": 1420.0,
        "is_demo": True
    },
    {
        "ticker": "BLUX",
        "symbol": "BLUX",
        "name": "BlueMatrix Enterprise Systems Inc.",
        "description": "Enterprise cloud infrastructure, cybersecurity, and data analytics provider",
        "base_price": 980.0,
        "is_demo": True
    },
    {
        "ticker": "DSNY",
        "symbol": "DSNY",
        "name": "DreamScape Entertainment Universe",
        "description": "Global streaming content, media networks and themed interactive parks",
        "base_price": 1150.0,
        "is_demo": True
    },
    {
        "ticker": "HAVN",
        "symbol": "HAVN",
        "name": "HavenStay Travel & Accommodations Inc.",
        "description": "Hospitality booking networks, boutique resorts and vacation suites",
        "base_price": 540.0,
        "is_demo": True
    },
    {
        "ticker": "HMDP",
        "symbol": "HMDP",
        "name": "Haven Depot Home Improvement Corp.",
        "description": "Retail hardware, architectural construction supplies and tooling",
        "base_price": 2350.0,
        "is_demo": True
    },
    {
        "ticker": "MOTR",
        "symbol": "MOTR",
        "name": "MotorWorks Global Holdings Corp.",
        "description": "Electric vehicle powertrain engineering, autonomous chassis design",
        "base_price": 820.0,
        "is_demo": True
    },
    {
        "ticker": "ORCX",
        "symbol": "ORCX",
        "name": "Oracrest Cloud Systems Inc.",
        "description": "Database warehousing, mission-critical ERP infrastructure",
        "base_price": 1780.0,
        "is_demo": True
    },
    {
        "ticker": "PLNX",
        "symbol": "PLNX",
        "name": "Polestar Analytics Corp.",
        "description": "Big-data pipeline orchestration, AI model fine-tuning APIs",
        "base_price": 630.0,
        "is_demo": True
    },
    {
        "ticker": "ROUT",
        "symbol": "ROUT",
        "name": "RouteWave Mobility Technologies Inc.",
        "description": "On-demand urban logistics, freight telematics and routing",
        "base_price": 410.0,
        "is_demo": True
    },
    {
        "ticker": "SONA",
        "symbol": "SONA",
        "name": "Sonata Digital Audio Media Inc.",
        "description": "Acoustic signal processing, streaming audio codec licensing",
        "base_price": 310.0,
        "is_demo": True
    }
]


class UniverseManager:
    """Discovers tradable stock universe and warm-starts historical indicator buffers."""

    def load_universe(self) -> List[Dict[str, Any]]:
        """Queries GET /api/v1/stocks or initializes demo universe."""
        base_lookup = {item["ticker"]: item["base_price"] for item in DEFAULT_DEMO_UNIVERSE}
        if not state.is_demo_mode and config.rest_base_url:
            stocks = api_client.get_stocks()
            if stocks and isinstance(stocks, list) and len(stocks) > 0:
                with state.lock:
                    state.universe.clear()
                    for s in stocks:
                        tk = s.get("ticker", s.get("symbol"))
                        if tk:
                            s["is_demo"] = False
                            if "base_price" not in s:
                                s["base_price"] = s.get("price", s.get("close", base_lookup.get(tk, 1000.0)))
                            state.universe[tk] = s
                logger.info(f"Dynamically discovered {len(stocks)} stocks from live competition server.")
                return stocks

        # Demo mode or offline fallback
        with state.lock:
            state.universe.clear()
            for s in DEFAULT_DEMO_UNIVERSE:
                state.universe[s["ticker"]] = s
        logger.info(f"Loaded {len(DEFAULT_DEMO_UNIVERSE)} stocks into DEMO universe.")
        return DEFAULT_DEMO_UNIVERSE

    def warm_start_history(self, lookback_days: int = 90):
        """Fetches historical OHLCV bars via GET /api/v1/stocks/:ticker/history to initialize indicators."""
        tickers = list(state.universe.keys())
        base_lookup = {item["ticker"]: item["base_price"] for item in DEFAULT_DEMO_UNIVERSE}
        loaded_count = 0

        if not state.is_demo_mode and config.rest_base_url:
            for ticker in tickers:
                prices = api_client.get_stock_history(ticker, days=lookback_days)
                if prices:
                    with state.lock:
                        state.price_history[ticker] = prices
                        last_bar = prices[-1]
                        state.market_prices[ticker] = {
                            "ticker": ticker,
                            "open": last_bar.get("open", last_bar.get("close", 0.0)),
                            "high": last_bar.get("high", last_bar.get("close", 0.0)),
                            "low": last_bar.get("low", last_bar.get("close", 0.0)),
                            "close": last_bar.get("close", 0.0),
                            "volume": last_bar.get("volume", 0),
                            "date": last_bar.get("date", "warm-start"),
                            "is_demo": False,
                            "updated_at": "warm-start"
                        }
                    loaded_count += 1
            if loaded_count > 0:
                logger.info(f"Warm-started indicator buffers for {loaded_count}/{len(tickers)} live stocks.")
                return

        # DEMO mode or Live fallback when history endpoint is empty (e.g. development stage)
        import numpy as np
        logger.info("Initializing baseline/synthetic price history for universe tickers.")
        for ticker in tickers:
            base = state.universe.get(ticker, {}).get("base_price", base_lookup.get(ticker, 1000.0))
            if ticker not in state.price_history or not state.price_history[ticker]:
                history = []
                curr = float(base)
                for d in range(30, 0, -1):
                    prev = curr
                    change = curr * float(np.random.normal(0.0005, 0.016))
                    curr = max(10.0, curr + change)
                    # Realistic open near previous close with occasional overnight gaps
                    day_open = round(prev * float(np.random.uniform(0.997, 1.003)), 2)
                    day_close = round(curr, 2)
                    day_high = round(max(day_open, day_close) * float(np.random.uniform(1.002, 1.012)), 2)
                    day_low = round(min(day_open, day_close) * float(np.random.uniform(0.988, 0.998)), 2)
                    history.append({
                        "date": f"2021-03-{31 - d:02d}",
                        "open": day_open,
                        "high": day_high,
                        "low": day_low,
                        "close": day_close,
                        "volume": int(np.random.randint(500000, 2000000)),
                        "is_demo": state.is_demo_mode
                    })
                with state.lock:
                    state.price_history[ticker] = history
                    state.market_prices[ticker] = {
                        "ticker": ticker,
                        "open": history[-1]["open"],
                        "high": history[-1]["high"],
                        "low": history[-1]["low"],
                        "close": history[-1]["close"],
                        "volume": history[-1]["volume"],
                        "date": history[-1]["date"],
                        "is_demo": state.is_demo_mode,
                        "updated_at": "warm-start"
                    }


universe_manager = UniverseManager()

