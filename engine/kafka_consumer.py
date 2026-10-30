import json
import time
import threading
import logging
from typing import Optional
import numpy as np

from engine.config import config, get_current_wifi_ssid
from engine.state import state
from engine.strategy import strategy
from engine.heartbeat_worker import heartbeat_worker

logger = logging.getLogger(__name__)


class KafkaStreamService:
    """Manages real-time ingestion from Kafka topics 'market.ticks' and 'market.news', plus DEMO replay."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._demo_thread: Optional[threading.Thread] = None

    def start(self):
        self._stop_event.clear()
        if not state.is_demo_mode and config.kafka_broker:
            self._thread = threading.Thread(target=self._run_live_kafka, daemon=True, name="KafkaConsumer")
            self._thread.start()
        else:
            self._demo_thread = threading.Thread(target=self._run_demo_stream, daemon=True, name="DemoStreamSimulator")
            self._demo_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._demo_thread:
            self._demo_thread.join(timeout=2.0)

    def _run_live_kafka(self):
        """Official Kafka Consumer conforming to Section 3 specifications with resilient reconnect."""
        try:
            from kafka import KafkaConsumer
        except ImportError:
            logger.error("kafka-python-ng is not installed.")
            with state.lock:
                state.kafka_status = "ERROR"
                state.kafka_error = "kafka package missing: run 'pip install kafka-python-ng'"
            return

        broker = config.kafka_broker
        group_id = config.consumer_group_id

        def safe_json_deserializer(m):
            if m is None:
                return None
            try:
                return json.loads(m.decode("utf-8"))
            except Exception:
                return None

        # Connection retry loop so engine recovers immediately upon joining Venue Wi-Fi
        while not self._stop_event.is_set():
            ssid = get_current_wifi_ssid()
            with state.lock:
                state.wifi_ssid = ssid
                state.kafka_status = "CONNECTING"
                state.kafka_error = None

            logger.info(f"Attempting Kafka connection to {broker} with group '{group_id}' (SSID: {ssid})...")
            try:
                consumer = KafkaConsumer(
                    "market.ticks",
                    "market.news",
                    bootstrap_servers=[broker],
                    group_id=group_id,
                    auto_offset_reset="latest",
                    enable_auto_commit=False,
                    value_deserializer=safe_json_deserializer,
                    consumer_timeout_ms=1000,
                    session_timeout_ms=10000,
                    request_timeout_ms=15000,
                    connections_max_idle_ms=30000
                )

                with state.lock:
                    state.kafka_status = "CONNECTED"
                    state.kafka_error = None
                logger.info(f"Kafka consumer successfully CONNECTED to {broker} on topics market.ticks, market.news.")

                # Ingestion loop
                while not self._stop_event.is_set():
                    records = consumer.poll(timeout_ms=150)
                    now = time.time()

                    for tp, msgs in records.items():
                        topic = tp.topic
                        for msg in msgs:
                            try:
                                data = msg.value
                                if not data or not isinstance(data, dict):
                                    continue
                                event_type = data.get("event_type", data.get("event"))

                                if topic == "market.ticks":
                                    # Preflight Heartbeat Tick: coordinate ACK sequence
                                    if event_type == "preflight_tick":
                                        seq = data.get("seq")
                                        if seq is None and isinstance(data.get("data"), dict):
                                            seq = data["data"].get("seq", 0)
                                        try:
                                            seq_num = int(seq or 0)
                                        except (ValueError, TypeError):
                                            seq_num = 0
                                        logger.info(f"Received preflight_tick on market.ticks: seq={seq_num}")
                                        heartbeat_worker.acknowledge_sequence(seq_num)
                                    # Daily OHLCV Price Tick
                                    elif event_type == "price_tick":
                                        sim_date = data.get("simulated_date") or time.strftime("%Y-%m-%d")
                                        candle = data.get("data")
                                        if not isinstance(candle, dict):
                                            candle = data
                                        event_ts = data.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ")
                                        is_demo = bool(data.get("is_demo", False))
                                        event_src = "DEMO_MOCK" if is_demo else "LIVE_KAFKA"
                                        strategy.on_price_tick(
                                            candle,
                                            simulated_date=sim_date,
                                            is_demo=is_demo,
                                            event_timestamp=event_ts,
                                            event_source=event_src,
                                        )
                                        with state.lock:
                                            state.kafka_last_tick_time = now
                                            if msg.timestamp and isinstance(msg.timestamp, (int, float)):
                                                state.kafka_lag_ms = max(0.0, (now - msg.timestamp / 1000.0) * 1000.0)

                                elif topic == "market.news":
                                    # Corporate News Flash
                                    if event_type == "news_flash":
                                        news_content = data.get("data")
                                        if not isinstance(news_content, dict):
                                            news_content = data
                                        event_ts = data.get("timestamp") or time.strftime("%Y-%m-%dT%H:%M:%SZ")
                                        is_demo = bool(data.get("is_demo", False))
                                        event_src = "DEMO_MOCK" if is_demo else "LIVE_KAFKA"
                                        strategy.on_news_flash(
                                            news_content,
                                            is_demo=is_demo,
                                            event_timestamp=event_ts,
                                            event_source=event_src,
                                        )
                            except Exception as item_err:
                                logger.error(f"Error handling message on {topic}: {item_err}", exc_info=True)

                consumer.close()
                break

            except Exception as e:
                import traceback
                diag = f"Broker {broker} unreachable ({type(e).__name__})."
                if ssid and "iphone" in ssid.lower():
                    diag += f" Laptop connected to '{ssid}'. Switch to Venue Wi-Fi."
                elif not ssid:
                    diag += " Wi-Fi interface disconnected."

                with state.lock:
                    state.kafka_status = "DISCONNECTED"
                    state.kafka_error = diag
                logger.warning(f"Kafka connection attempt failed: {diag}\n{traceback.format_exc()}")

                # Wait 4 seconds before next reconnect attempt
                self._stop_event.wait(4.0)

    def _run_demo_stream(self):
        """
        High-fidelity DEMO market simulation stream.
        Runs when DEMO_MODE is true.
        Clearly tags all data with is_demo: True.
        """
        with state.lock:
            state.kafka_status = "DEMO"
            state.kafka_error = "Running synthetic sandbox stream (Demo Mode)"
            state.sim_stage = "preflight"
            state.sim_status = "RUNNING"
            state.rest_status = "DEMO"
            state.heartbeat_status = "DEMO"

        logger.info("Starting DEMO simulation stream (1 trading day = 3.5 seconds)...")
        
        # In DEMO mode, simulate 2 preflight sequences first
        for demo_seq in (1, 2):
            if self._stop_event.is_set():
                return
            heartbeat_worker.acknowledge_sequence(demo_seq)
            time.sleep(1.0)

        with state.lock:
            state.sim_stage = "simulation"
            state.sim_status = "RUNNING"

        day_counter = 1
        
        sample_headlines = [
            ("ALPHACORP", "ALPHACORP Q3 NET PROFIT SURGES 24% YOY", "Company announces record exports and declares interim dividend.", "BULLISH"),
            ("BETATECH", "BETATECH WINS MAJOR EXPANSION CONTRACT FOR ENTERPRISE CLOUD", "Secured global partnership with multi-million dollar annual recurrences.", "BULLISH"),
            ("GAMMAPHARMA", "REGULATORY SCRUTINY AND AUDIT PROBE INTO MANUFACTURING QUALITY", "Inspectors report deficiency notices for active batch lines.", "BEARISH"),
            ("DELTABANK", "DELTABANK POSTS RECORD OPERATING GROWTH AND MARGIN EXPANSION", "Asset quality strengthens with decline in gross NPA ratios.", "BULLISH"),
            ("SIGMAENERGY", "SUDDEN LOSS AND COST OVERRUN ON WIND TURBINE GRID CONNECTIONS", "Project delays prompt broker downgrade across renewable holdings.", "BEARISH"),
            ("ALPHACORP", "ALPHACORP EXPANSION INTO HIGH-TECH SEMICONDUCTOR ALLOY DIVISION", "Joint venture partnership finalized with global tier-1 tech supplier.", "BULLISH")
        ]

        while not self._stop_event.is_set():
            sim_date = f"2021-04-{day_counter:02d}" if day_counter <= 30 else f"2021-05-{day_counter-30:02d}"
            
            with state.lock:
                state.sim_current_date = sim_date
                state.sim_days_completed = day_counter
                state.sim_total_days = 60
                state.sim_day_counter = day_counter

            # 1. T + 0s: Dispatch Daily OHLCV Price Ticks for all stocks
            for ticker, item in list(state.universe.items()):
                prev_price = state.market_prices.get(ticker, {}).get("close", 1000.0)
                # Volatility jump
                volatility = 0.018
                drift = 0.002
                pct_return = float(np.random.normal(drift, volatility))
                close_price = round(max(10.0, prev_price * (1.0 + pct_return)), 2)
                open_price = round(prev_price * (1.0 + float(np.random.normal(0, 0.003))), 2)
                high_price = round(max(open_price, close_price) * (1.0 + abs(float(np.random.normal(0, 0.006)))), 2)
                low_price = round(min(open_price, close_price) * (1.0 - abs(float(np.random.normal(0, 0.006)))), 2)
                volume = int(np.random.randint(600000, 2500000))

                candle = {
                    "ticker": ticker,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": volume
                }
                strategy.on_price_tick(
                    candle,
                    simulated_date=sim_date,
                    is_demo=True,
                    event_timestamp=time.strftime("%H:%M:%S"),
                    event_source="DEMO_MOCK",
                )

            with state.lock:
                state.kafka_last_tick_time = time.time()
                state.kafka_lag_ms = 4.2

            # 2. T + 150ms: Corporate News Flash (every 2-3 days)
            time.sleep(0.15)
            if day_counter % 2 == 0 or np.random.rand() > 0.4:
                idx = np.random.randint(0, len(sample_headlines))
                tk, hl, desc, _ = sample_headlines[idx]
                news_data = {
                    "ticker": tk,
                    "headline": hl,
                    "description": desc,
                    "date": sim_date
                }
                strategy.on_news_flash(news_data, is_demo=True)

            # 3. Simulate 10-day short settlement auto square-off
            if day_counter % 10 == 0:
                with state.lock:
                    for tk, pos in list(state.holdings.items()):
                        if pos.get("position_type") == "SHORT" and pos.get("quantity", 0) > 0:
                            logger.info(f"Day {day_counter}: 10-Day mandatory settlement square-off for {tk}")
                            strategy.on_price_tick({
                                "ticker": tk,
                                "close": state.market_prices[tk]["close"]
                            }, simulated_date=sim_date, is_demo=True)

            day_counter += 1
            # Sleep remainder of simulated day (~3.35s)
            time.sleep(3.35)


kafka_stream = KafkaStreamService()
