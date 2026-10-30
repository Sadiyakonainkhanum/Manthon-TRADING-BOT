import time
import threading
import logging
from typing import Optional
from engine.config import config, get_current_wifi_ssid
from engine.state import state
from engine.api_client import api_client

logger = logging.getLogger(__name__)


class HeartbeatWorker:
    """Manages pre-flight readiness sequence acknowledgment to POST /api/v1/bot/heartbeat."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_acked_seq: int = -1
        self._last_ack_dispatch_time: float = 0.0
        self._consecutive_stage_failures: int = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="HeartbeatWorker")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def acknowledge_sequence(self, seq: int) -> bool:
        """Immediately sends ACK for an incoming preflight_tick to POST /api/v1/bot/heartbeat, deduplicating bursts."""
        now = time.time()
        # Prevent rapid duplicate ACK dispatch for the same sequence number (avoids 429 flood)
        if seq == self._last_acked_seq and (now - self._last_ack_dispatch_time) < 4.0:
            return True

        with state.lock:
            state.last_heartbeat_seq = seq
            state.last_heartbeat_time = now

        if not state.is_demo_mode and config.rest_base_url:
            success, lat, err = api_client.send_heartbeat(seq)
            with state.lock:
                state.last_heartbeat_ack_success = success
                state.last_heartbeat_latency_ms = lat
                state.last_heartbeat_error = err
                state.heartbeat_status = "ACKED" if success else "ERROR"
            if success:
                self._last_acked_seq = seq
                self._last_ack_dispatch_time = now
                logger.info(f"Pre-flight Heartbeat seq {seq} acknowledged in {lat:.1f}ms -> Status: ACKED")
            else:
                logger.warning(f"Pre-flight Heartbeat seq {seq} ACK failed: {err}")
            return success
        else:
            # DEMO mode heartbeat ACK: clearly tagged as DEMO
            with state.lock:
                state.last_heartbeat_ack_success = True
                state.last_heartbeat_latency_ms = 1.0
                state.last_heartbeat_error = None
                state.heartbeat_status = "DEMO"
            return True

    def _run_loop(self):
        """Monitors platform lifecycle stage and manages heartbeat watchdog."""
        loop_counter = 0
        while not self._stop_event.is_set():
            try:
                loop_counter += 1

                # Update Wi-Fi SSID continuously for real-time diagnostic reporting
                current_ssid = get_current_wifi_ssid()
                with state.lock:
                    state.wifi_ssid = current_ssid

                now = time.time()
                last_time = state.last_heartbeat_time or 0.0

                # In LIVE mode: if coordinator emitted a sequence and we are in preflight,
                # resend ACK if nearing the 5-second deadline
                if not state.is_demo_mode:
                    if state.last_heartbeat_seq > 0 and str(state.sim_stage).lower() == "preflight":
                        if (now - last_time) >= 4.0:
                            self.acknowledge_sequence(state.last_heartbeat_seq)
                    elif state.last_heartbeat_seq == 0 and state.heartbeat_status not in ("ERROR", "ACKED"):
                        with state.lock:
                            state.heartbeat_status = "WAITING"

                # Poll simulation stage every 4.0 seconds
                if not state.is_demo_mode and config.rest_base_url:
                    stage_info = api_client.get_stage()
                    if stage_info:
                        self._consecutive_stage_failures = 0
                        with state.lock:
                            state.sim_stage = str(stage_info.get("stage", state.sim_stage)).lower()
                            state.sim_status = str(stage_info.get("status", state.sim_status)).upper()
                            state.sim_current_date = stage_info.get("current_date", state.sim_current_date)
                            state.sim_total_days = stage_info.get("total_days", state.sim_total_days)
                            state.sim_days_completed = stage_info.get("days_completed", state.sim_days_completed)
                            state.sim_interval_seconds = stage_info.get("interval_seconds", 4)
                            state.rest_status = "ONLINE"
                            state.rest_error = None

                        # Periodically reconcile official exchange cash & holdings (every ~20s)
                        if config.BOT_ACCESS_TOKEN and loop_counter % 5 == 0:
                            port_data = api_client.get_portfolio()
                            if port_data:
                                official_cash = float(port_data.get("available_cash", port_data.get("cash_balance", state.available_cash)))
                                official_margin = float(port_data.get("margin_locked", 0.0))
                                official_realized_pnl = float(port_data.get("realized_pnl", state.realized_pnl))
                                official_holdings_list = port_data.get("holdings", [])

                                with state.lock:
                                    state.available_cash = official_cash
                                    state.margin_locked = official_margin
                                    state.realized_pnl = official_realized_pnl
                                    state.portfolio_source = "OFFICIAL EXCHANGE API"

                                    # Synchronize active holdings with official gateway
                                    new_holdings = {}
                                    for h in official_holdings_list:
                                        tk = h.get("ticker")
                                        qty = int(h.get("quantity", 0))
                                        if not tk or qty == 0:
                                            continue
                                        pos_type = "LONG" if qty > 0 else "SHORT"
                                        avg_p = float(h.get("avg_buy_price", h.get("avg_price", h.get("average_buy_price", h.get("current_price", 0.0)))))
                                        new_holdings[tk] = {
                                            "quantity": abs(qty),
                                            "avg_price": avg_p,
                                            "position_type": pos_type,
                                            "is_demo": False
                                        }
                                    state.holdings = new_holdings
                    else:
                        self._consecutive_stage_failures += 1
                        with state.lock:
                            if api_client.rate_limiter.is_backed_off():
                                state.rest_status = "RATE_LIMITED"
                                rem = max(0, int(api_client.rate_limiter.remaining_backoff_seconds()))
                                state.rest_error = f"Gateway rate limit active. Cooling down for {rem}s."
                            elif state.heartbeat_status == "ACKED" or self._consecutive_stage_failures < 3:
                                state.rest_status = "ONLINE"
                                state.rest_error = None
                            else:
                                state.rest_status = "DISCONNECTED"
                                diag = f"Gateway {config.rest_base_url} unreachable."
                                if current_ssid and "iphone" in current_ssid.lower():
                                    diag += f" Laptop connected to '{current_ssid}'. Switch to Venue Wi-Fi."
                                state.rest_error = diag
                else:
                    with state.lock:
                        state.portfolio_source = "LOCAL CALCULATION (DEMO)"

            except Exception as e:
                logger.error(f"Error in heartbeat worker: {e}")

            time.sleep(4.0)


heartbeat_worker = HeartbeatWorker()
