import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from engine.tax_calculator import tax_calculator


class BotState:
    """Thread-safe central state for the MANTHAN 2026 trading engine and telemetry hub."""

    def __init__(self):
        self.lock = threading.RLock()

        # Mode and Connection Flags
        self.is_demo_mode: bool = True
        self.is_running: bool = False
        self.emergency_stop: bool = False

        # Capital & Wealth Tracking (Section 7 & Section 8)
        self.starting_capital: float = 1_000_000.00
        self.available_cash: float = 1_000_000.00
        self.margin_locked: float = 0.00
        self.realized_pnl: float = 0.00
        self.total_brokerage_paid: float = 0.00
        self.total_dp_charges_paid: float = 0.00
        self.peak_wealth: float = 1_000_000.00
        self.current_drawdown_pct: float = 0.00
        self.portfolio_source: str = "LOCAL CALCULATION (DEMO)"  # "OFFICIAL EXCHANGE API" | "LOCAL CALCULATION (DEMO)"

        # Simulation Lifecycle Status
        self.sim_stage: str = "disconnected"  # "development" | "ready" | "preflight" | "simulation" | "disconnected"
        self.sim_status: str = "OFFLINE"       # "IDLE" | "RUNNING" | "PAUSED" | "COMPLETED" | "OFFLINE"
        self.sim_current_date: str = "2021-01-01"
        self.sim_total_days: int = 0
        self.sim_days_completed: int = 0
        self.sim_interval_seconds: int = 4
        self.sim_day_counter: int = 0          # Used for 10-day short settlement tracking

        # Connection Telemetry
        self.kafka_status: str = "DISCONNECTED"  # "CONNECTED" | "DISCONNECTED" | "ERROR" | "DEMO"
        self.kafka_error: Optional[str] = "Server IP not configured"
        self.kafka_last_tick_time: Optional[float] = None
        self.kafka_lag_ms: float = 0.0

        self.rest_status: str = "DISCONNECTED"   # "ONLINE" | "DISCONNECTED" | "ERROR" | "RATE_LIMITED"
        self.rest_error: Optional[str] = "Server IP not configured"
        self.rest_last_ping_time: Optional[float] = None
        self.rest_latency_ms: float = 0.0

        self.heartbeat_status: str = "WAITING"    # "WAITING" | "ACKED" | "ERROR" | "DEMO"
        self.last_heartbeat_seq: int = 0
        self.last_heartbeat_time: Optional[float] = None
        self.last_heartbeat_ack_success: bool = False
        self.last_heartbeat_error: Optional[str] = None
        self.last_heartbeat_latency_ms: float = 0.0
        self.wifi_ssid: Optional[str] = None

        # Stock Universe (discovered dynamically via /api/v1/stocks)
        # Format: {ticker: {"ticker": str, "name": str, "description": str, "is_demo": bool}}
        self.universe: Dict[str, Dict[str, Any]] = {}

        # Latest Market Data (OHLCV candles received via Kafka market.ticks)
        # Format: {ticker: {"open": float, "high": float, "low": float, "close": float, "volume": int, "date": str, "is_demo": bool}}
        self.market_prices: Dict[str, Dict[str, Any]] = {}

        # Rolling Historical Buffer for Indicators (up to 90 days per stock)
        # Format: {ticker: [{"date": str, "close": float, "open": float, ...}]}
        self.price_history: Dict[str, List[Dict[str, Any]]] = {}

        # Portfolio Holdings
        # Format: {ticker: {"quantity": int, "avg_price": float, "position_type": "LONG"|"SHORT", "margin_locked": float}}
        self.holdings: Dict[str, Dict[str, Any]] = {}

        # Corporate News Feed (Kafka market.news)
        # List of news dicts: [{id, ticker, headline, description, date, sentiment, score, is_demo}]
        self.news_feed: List[Dict[str, Any]] = []

        # Strategy & Indicator Monitor
        # Format: {ticker: {"fast_ma": float, "slow_ma": float, "rsi": float, "drop_3d_pct": float, "sentiment": str, "signal": str, "reason": str, "updated_at": str}}
        self.strategy_signals: Dict[str, Dict[str, Any]] = {}

        # Order Audit & Duplicate Prevention Cache
        self.order_log: List[Dict[str, Any]] = []
        self.daily_executed_orders: Set[str] = set()  # Tracks ticker:simulated_date
        self.decision_audit_trail: List[Dict[str, Any]] = []  # Detailed decision records per tick

        # Multi-Agent Intelligence Hub (Agnes & Jeff)
        self.agent_decisions: Dict[str, Dict[str, Any]] = {}

        # Rate Limiting Tracker
        self.order_timestamps: List[float] = []

    def reset_capital(self):
        """Resets virtual testing capital to default ₹10,00,000."""
        with self.lock:
            self.starting_capital = 1_000_000.00
            self.available_cash = 1_000_000.00
            self.margin_locked = 0.00
            self.realized_pnl = 0.00
            self.total_brokerage_paid = 0.00
            self.total_dp_charges_paid = 0.00
            self.holdings.clear()
            self.order_log.clear()
            self.daily_executed_orders.clear()
            self.decision_audit_trail.clear()
            self.agent_decisions.clear()
            self.sim_stage = "disconnected"
            self.sim_status = "OFFLINE"
            self.peak_wealth = 1_000_000.00
            self.current_drawdown_pct = 0.00
            tax_calculator.reset()

    def compute_wealth_metrics(self) -> Dict[str, float]:
        """Calculates portfolio valuation and metrics according to Section 7 & 8."""
        with self.lock:
            long_market_value = 0.0
            short_market_value = 0.0
            unrealized_pnl = 0.0

            for ticker, pos in self.holdings.items():
                qty = pos.get("quantity", 0)
                if qty == 0:
                    continue
                avg_p = pos.get("avg_price", 0.0)
                pos_type = pos.get("position_type", "LONG")
                curr_p = self.market_prices.get(ticker, {}).get("close", avg_p)

                if pos_type == "LONG":
                    val = qty * curr_p
                    long_market_value += val
                    unrealized_pnl += (curr_p - avg_p) * qty
                elif pos_type == "SHORT":
                    # For short, market value is based on current cover cost
                    val = qty * curr_p
                    short_market_value += val
                    # Short profit = (entry_price - current_price) * quantity
                    unrealized_pnl += (avg_p - curr_p) * qty

            # Total Wealth formula: Available Cash + Margin Locked + Long Market Value + Short Market Value
            # Note: For shorts, margin is locked in cash collateral.
            total_wealth = self.available_cash + self.margin_locked + long_market_value

            if total_wealth > self.peak_wealth:
                self.peak_wealth = total_wealth
            
            drawdown = 0.0
            if self.peak_wealth > 0:
                drawdown = max(0.0, (self.peak_wealth - total_wealth) / self.peak_wealth * 100.0)
            self.current_drawdown_pct = drawdown

            # Cash cushion %
            cash_cushion_pct = (self.available_cash / total_wealth * 100.0) if total_wealth > 0 else 0.0

            # Tax Analytics (Income-tax Act 1961: STCG 15%, LTCG 10%, Sec 70/71 loss offset)
            tax_report = tax_calculator.compute_tax_report()
            total_tax_liability = tax_report["total_tax_liability"]
            after_tax_wealth = max(0.0, total_wealth - total_tax_liability)

            return {
                "starting_capital": self.starting_capital,
                "available_cash": round(self.available_cash, 2),
                "margin_locked": round(self.margin_locked, 2),
                "long_market_value": round(long_market_value, 2),
                "short_market_value": round(short_market_value, 2),
                "total_wealth": round(total_wealth, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "realized_pnl": round(self.realized_pnl, 2),
                "total_brokerage": round(self.total_brokerage_paid, 2),
                "total_dp_charges": round(self.total_dp_charges_paid, 2),
                "tax_liability": round(total_tax_liability, 2),
                "after_tax_wealth": round(after_tax_wealth, 2),
                "drawdown_pct": round(drawdown, 2),
                "cash_cushion_pct": round(cash_cushion_pct, 2),
                "source": self.portfolio_source,
            }

    def get_readiness_status(self) -> Dict[str, Any]:
        """
        Computes the definitive pre-flight bot readiness state adhering to MANTHAN 2026 specifications:
        - READY: Kafka is CONNECTED and a recent pre-flight heartbeat ACK was confirmed (<15s)
        - WAITING: In live mode, but waiting for Kafka connection or preflight tick ACK
        - ERROR: Network unreachable, connection refused, or heartbeat ACK failed
        - DEMO: Offline synthetic sandbox mode (NOT competition ready)
        """
        now = time.time()

        if self.is_demo_mode:
            return {
                "status": "DEMO",
                "label": "DEMO",
                "sublabel": "NOT COMPETITION-READY (MOCK DATA)",
                "is_ready": False,
                "diagnostic": "Running with synthetic test data. Not connected to competition exchange.",
                "color": "amber"
            }

        # Check for hard connection errors
        if self.kafka_status in ("DISCONNECTED", "ERROR") or self.rest_status in ("DISCONNECTED", "ERROR"):
            err_msg = self.kafka_error or self.rest_error or "Network connection to competition server failed"
            return {
                "status": "ERROR",
                "label": "ERROR",
                "sublabel": "DISCONNECTED",
                "is_ready": False,
                "diagnostic": err_msg,
                "color": "rose"
            }

        if self.last_heartbeat_time is not None and not self.last_heartbeat_ack_success:
            return {
                "status": "ERROR",
                "label": "ERROR",
                "sublabel": "HEARTBEAT ACK FAILED",
                "is_ready": False,
                "diagnostic": self.last_heartbeat_error or "Heartbeat acknowledgment rejected or timed out",
                "color": "rose"
            }

        # Check for confirmed READY state
        is_kafka_connected = (self.kafka_status == "CONNECTED")
        has_recent_ack = (
            self.last_heartbeat_ack_success and 
            self.last_heartbeat_time is not None and 
            (now - self.last_heartbeat_time) < 15.0
        )

        if is_kafka_connected and has_recent_ack:
            return {
                "status": "READY",
                "label": "READY",
                "sublabel": f"PRE-FLIGHT CONFIRMED (Seq #{self.last_heartbeat_seq})",
                "is_ready": True,
                "diagnostic": f"Connected to Kafka; Heartbeat seq #{self.last_heartbeat_seq} acknowledged in {self.last_heartbeat_latency_ms:.1f}ms.",
                "color": "emerald"
            }

        # If connected and simulation is actively RUNNING
        if is_kafka_connected and str(self.sim_stage).lower() == "simulation" and str(self.sim_status).upper() == "RUNNING":
            return {
                "status": "READY",
                "label": "READY",
                "sublabel": f"SIMULATION RUNNING (Day {self.sim_days_completed}/{self.sim_total_days})",
                "is_ready": True,
                "diagnostic": "Trading active in simulation stage.",
                "color": "emerald"
            }

        # Otherwise WAITING
        waiting_reasons = []
        if not is_kafka_connected:
            waiting_reasons.append("Kafka connecting")
        if not has_recent_ack:
            if self.last_heartbeat_seq == 0:
                waiting_reasons.append("Awaiting preflight_tick on market.ticks")
            else:
                waiting_reasons.append("Awaiting heartbeat ACK confirmation")

        return {
            "status": "WAITING",
            "label": "WAITING",
            "sublabel": "AWAITING HEARTBEAT / KAFKA",
            "is_ready": False,
            "diagnostic": f"Waiting for: {', '.join(waiting_reasons)}",
            "color": "amber"
        }

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns a complete snapshot for the UI telemetry WebSocket / API."""
        with self.lock:
            wealth = self.compute_wealth_metrics()

            # Format holdings with individual P&L and market values
            holdings_list = []
            for ticker, pos in self.holdings.items():
                qty = pos.get("quantity", 0)
                if qty == 0:
                    continue
                avg_p = pos.get("avg_price", 0.0)
                pos_type = pos.get("position_type", "LONG")
                curr_p = self.market_prices.get(ticker, {}).get("close", avg_p)
                
                if pos_type == "LONG":
                    mkt_val = qty * curr_p
                    u_pnl = (curr_p - avg_p) * qty
                    pnl_pct = ((curr_p - avg_p) / avg_p * 100.0) if avg_p > 0 else 0.0
                else:
                    mkt_val = qty * curr_p
                    u_pnl = (avg_p - curr_p) * qty
                    pnl_pct = ((avg_p - curr_p) / avg_p * 100.0) if avg_p > 0 else 0.0

                exposure_pct = (mkt_val / wealth["total_wealth"] * 100.0) if wealth["total_wealth"] > 0 else 0.0

                holdings_list.append({
                    "ticker": ticker,
                    "company_name": self.universe.get(ticker, {}).get("name", ticker),
                    "quantity": qty,
                    "position_type": pos_type,
                    "avg_price": round(avg_p, 2),
                    "current_price": round(curr_p, 2),
                    "market_value": round(mkt_val, 2),
                    "unrealized_pnl": round(u_pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "exposure_pct": round(exposure_pct, 2),
                    "is_demo": pos.get("is_demo", self.is_demo_mode)
                })

            # Calculate order error rate
            total_orders = len(self.order_log)
            rejected_orders = sum(1 for o in self.order_log if o.get("status") == "REJECTED")
            error_rate = (rejected_orders / total_orders * 100.0) if total_orders > 0 else 0.0

            readiness = self.get_readiness_status()

            return {
                "mode": "DEMO" if self.is_demo_mode else "LIVE",
                "is_running": self.is_running,
                "emergency_stop": self.emergency_stop,
                "readiness": readiness,
                "wealth": wealth,
                "tax_analytics": tax_calculator.compute_tax_report(),
                "holdings": holdings_list,
                "market_prices": self.market_prices,
                "price_history": {tk: bars[-40:] for tk, bars in self.price_history.items()},
                "universe": list(self.universe.values()),
                "news_feed": self.news_feed[-30:],
                "strategy_signals": self.strategy_signals,
                "agent_decisions": self.agent_decisions,
                "order_log": self.order_log[-50:],
                "order_stats": {
                    "total": total_orders,
                    "filled": total_orders - rejected_orders,
                    "rejected": rejected_orders,
                    "error_rate_pct": round(error_rate, 2),
                },
                "connections": {
                    "wifi": {
                        "ssid": self.wifi_ssid,
                        "is_venue_wifi": bool(self.wifi_ssid and "iphone" not in self.wifi_ssid.lower() and "hotspot" not in self.wifi_ssid.lower())
                    },
                    "kafka": {
                        "status": self.kafka_status,
                        "error": self.kafka_error,
                        "lag_ms": round(self.kafka_lag_ms, 1),
                        "last_tick": self.kafka_last_tick_time
                    },
                    "rest_api": {
                        "status": self.rest_status,
                        "error": self.rest_error,
                        "latency_ms": round(self.rest_latency_ms, 1),
                        "last_ping": self.rest_last_ping_time
                    },
                    "heartbeat": {
                        "status": self.heartbeat_status,
                        "last_seq": self.last_heartbeat_seq,
                        "last_ack_time": self.last_heartbeat_time,
                        "last_latency_ms": round(self.last_heartbeat_latency_ms, 1),
                        "success": self.last_heartbeat_ack_success,
                        "error": self.last_heartbeat_error
                    },
                    "simulation": {
                        "stage": self.sim_stage,
                        "status": self.sim_status,
                        "current_date": self.sim_current_date,
                        "total_days": self.sim_total_days,
                        "days_completed": self.sim_days_completed,
                        "days_until_settlement": (10 - (self.sim_day_counter % 10))
                    }
                },
                "timestamp": datetime.now().isoformat()
            }


state = BotState()

