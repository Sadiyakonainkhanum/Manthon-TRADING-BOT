import logging
import threading
import time
from typing import Dict, Any

from engine.config import config
from engine.state import state
from engine.universe_manager import universe_manager
from engine.heartbeat_worker import heartbeat_worker
from engine.kafka_consumer import kafka_stream

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TradingBotMaster")


class BotMasterService:
    """Master controller that orchestrates the lifecycle, consumers, heartbeats, and state of the trading bot."""

    def __init__(self):
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._running:
                logger.warning("BotMasterService already running.")
                return

            logger.info("Initializing MANTHAN 2026 Autonomous Trading System...")
            state.is_running = True
            state.is_demo_mode = config.DEMO_MODE
            self._running = True

            # Launch discovery, warm-up, and background workers in an asynchronous thread
            # so web server starts immediately without blocking on external timeouts
            init_thread = threading.Thread(target=self._init_and_run, daemon=True, name="BotInitWorker")
            init_thread.start()
            logger.info("Trading Bot Master initialization thread launched.")

    def _init_and_run(self):
        """Asynchronously discovers universe, warms up history, and connects workers."""
        try:
            # 1. Discover Universe (GET /api/v1/stocks or DEMO universe)
            universe_manager.load_universe()

            # 2. Warm-start historical buffers for indicators (GET /stocks/:ticker/history)
            universe_manager.warm_start_history(lookback_days=30)

            # 3. Start Heartbeat & Lifecycle Worker (POST /api/v1/bot/heartbeat)
            heartbeat_worker.start()

            # 4. Start Kafka Market Stream (or DEMO simulator)
            kafka_stream.start()

            logger.info("Trading Bot Master fully active and listening.")
        except Exception as e:
            logger.error(f"Error during Bot Master initialization: {e}")

    def stop(self):
        with self._lock:
            if not self._running:
                return
            logger.info("Stopping Trading Bot Master...")
            state.is_running = False
            kafka_stream.stop()
            heartbeat_worker.stop()
            self._running = False
            logger.info("Trading Bot Master stopped.")

    def set_emergency_stop(self, stop_active: bool):
        with state.lock:
            state.emergency_stop = stop_active
        logger.warning(f"Emergency stop state set to: {stop_active}")

    def switch_mode(self, demo_mode: bool):
        with self._lock:
            if self._running:
                self.stop()
            config.DEMO_MODE = demo_mode
            state.is_demo_mode = demo_mode
            self.start()


bot_master = BotMasterService()

