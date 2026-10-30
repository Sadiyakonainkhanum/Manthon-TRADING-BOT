import time
import threading
import requests
from typing import Dict, Any, Optional, List, Tuple
from engine.config import config

Tuple_status = Tuple[bool, float, Optional[str]]


class RateLimiter:
    """Token-bucket rate limiter enforcing max requests per minute, sub-second burst prevention, and HTTP 429 backoff."""

    def __init__(self, max_per_minute: int = 110):
        self.max_per_minute = max_per_minute
        self.interval = 60.0 / max_per_minute
        self.lock = threading.Lock()
        self.timestamps: List[float] = []
        self.backoff_until: float = 0.0

    def trigger_backoff(self, seconds: float = 15.0):
        with self.lock:
            self.backoff_until = max(self.backoff_until, time.time() + seconds)

    def is_backed_off(self) -> bool:
        with self.lock:
            return time.time() < self.backoff_until

    def remaining_backoff_seconds(self) -> float:
        with self.lock:
            return max(0.0, self.backoff_until - time.time())

    def acquire(self) -> bool:
        with self.lock:
            now = time.time()
            if now < self.backoff_until:
                return False
            # Retain only timestamps from the last 60 seconds
            self.timestamps = [t for t in self.timestamps if now - t < 60.0]
            if len(self.timestamps) >= self.max_per_minute:
                return False
            # Prevent sub-second bursts (>3 req in 0.5s)
            recent_half_sec = [t for t in self.timestamps if now - t < 0.5]
            if len(recent_half_sec) >= 3:
                return False
            self.timestamps.append(now)
            return True

    def wait_and_acquire(self, timeout: float = 2.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if self.acquire():
                return True
            time.sleep(0.05)
        return False


class CompetitionAPIClient:
    """Client for the MANTHAN 2026 REST Gateway on Port 3002."""

    def __init__(self):
        self.rate_limiter = RateLimiter(max_per_minute=config.MAX_ORDERS_PER_MINUTE)
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _headers(self, require_auth: bool = True) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if require_auth and config.BOT_ACCESS_TOKEN:
            headers["Authorization"] = f"Bearer {config.BOT_ACCESS_TOKEN}"
        return headers

    def ping_server(self) -> Tuple_status:
        """Lightweight check to test if the Order Gateway server is reachable."""
        if not config.rest_base_url:
            return False, 0.0, "SERVER_IP is not configured"
        if self.rate_limiter.is_backed_off():
            rem = self.rate_limiter.remaining_backoff_seconds()
            return True, 0.0, f"Rate limited (cooling down for {rem:.0f}s)"
        try:
            start = time.time()
            res = self.session.get(f"{config.rest_base_url}/stage", timeout=2.0)
            latency = (time.time() - start) * 1000.0
            if res.status_code == 200:
                return True, latency, None
            if res.status_code == 429:
                try:
                    retry_sec = float(res.json().get("retry_after_seconds", 15.0))
                except Exception:
                    retry_sec = 15.0
                self.rate_limiter.trigger_backoff(retry_sec)
                return True, latency, f"Rate limited (cooling down for {retry_sec:.0f}s)"
            return False, latency, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, 0.0, str(e)

    def get_stage(self) -> Optional[Dict[str, Any]]:
        """GET /api/v1/stage (Public, no auth)"""
        if not config.rest_base_url:
            return None
        if self.rate_limiter.is_backed_off():
            return None
        try:
            res = self.session.get(f"{config.rest_base_url}/stage", timeout=5.0)
            if res.status_code == 200:
                return res.json()
            if res.status_code == 429:
                try:
                    retry_sec = float(res.json().get("retry_after_seconds", 15.0))
                except Exception:
                    retry_sec = 15.0
                self.rate_limiter.trigger_backoff(retry_sec)
        except Exception:
            pass
        return None

    def get_simulation_clock(self) -> Optional[Dict[str, Any]]:
        """GET /api/v1/simulation/clock (Public)"""
        if not config.rest_base_url:
            return None
        if self.rate_limiter.is_backed_off():
            return None
        try:
            res = self.session.get(f"{config.rest_base_url}/simulation/clock", timeout=3.0)
            if res.status_code == 200:
                return res.json()
            if res.status_code == 429:
                try:
                    retry_sec = float(res.json().get("retry_after_seconds", 15.0))
                except Exception:
                    retry_sec = 15.0
                self.rate_limiter.trigger_backoff(retry_sec)
        except Exception:
            pass
        return None

    def send_heartbeat(self, seq: int) -> Tuple_status:
        """POST /api/v1/bot/heartbeat (Bearer JWT)"""
        if not config.rest_base_url:
            return False, 0.0, "No SERVER_IP"
        if not config.BOT_ACCESS_TOKEN:
            return False, 0.0, "No BOT_ACCESS_TOKEN"
        if self.rate_limiter.is_backed_off():
            rem = self.rate_limiter.remaining_backoff_seconds()
            return False, 0.0, f"Rate limited (cooling down for {rem:.0f}s)"

        try:
            start = time.time()
            payload = {"seq": seq}
            res = self.session.post(
                f"{config.rest_base_url}/bot/heartbeat",
                json=payload,
                headers=self._headers(require_auth=True),
                timeout=2.5
            )
            lat = (time.time() - start) * 1000.0
            if res.status_code in (200, 204):
                return True, lat, None
            if res.status_code == 429:
                try:
                    retry_sec = float(res.json().get("retry_after_seconds", 15.0))
                except Exception:
                    retry_sec = 15.0
                self.rate_limiter.trigger_backoff(retry_sec)
                return False, lat, f"HTTP 429: Rate limited (cooldown {retry_sec:.0f}s)"
            return False, lat, f"HTTP {res.status_code}: {res.text[:100]}"
        except Exception as e:
            return False, 0.0, str(e)

    def get_stocks(self) -> Optional[List[Dict[str, Any]]]:
        """GET /api/v1/stocks (Bearer JWT)"""
        if not config.rest_base_url:
            return None
        try:
            res = self.session.get(
                f"{config.rest_base_url}/stocks",
                headers=self._headers(require_auth=True),
                timeout=4.0
            )
            if res.status_code == 200:
                data = res.json()
                return data.get("stocks", [])
        except Exception:
            pass
        return None

    def get_stock_history(self, ticker: str, days: int = 90) -> Optional[List[Dict[str, Any]]]:
        """
        GET /api/v1/stocks/:ticker/history?days=N
        Alternative: /api/v1/stocks/history?ticker=...&days=N
        """
        if not config.rest_base_url:
            return None
        try:
            # Primary format from PDF
            url = f"{config.rest_base_url}/stocks/{ticker}/history?days={days}"
            res = self.session.get(url, headers=self._headers(require_auth=False), timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                return data.get("prices", [])
            
            # Alternative query param format
            alt_url = f"{config.rest_base_url}/stocks/history?ticker={ticker}&days={days}"
            alt_res = self.session.get(alt_url, headers=self._headers(require_auth=False), timeout=5.0)
            if alt_res.status_code == 200:
                alt_data = alt_res.json()
                return alt_data.get("prices", [])
        except Exception:
            pass
        return None

    def get_portfolio(self) -> Optional[Dict[str, Any]]:
        """GET /api/v1/portfolio (Bearer JWT)"""
        if not config.rest_base_url:
            return None
        try:
            res = self.session.get(
                f"{config.rest_base_url}/portfolio",
                headers=self._headers(require_auth=True),
                timeout=5.0
            )
            if res.status_code == 200:
                return res.json()
        except Exception:
            pass
        return None

    def get_cash(self) -> Optional[float]:
        """GET /api/v1/portfolio/cash (Bearer JWT)"""
        if not config.rest_base_url:
            return None
        try:
            res = self.session.get(
                f"{config.rest_base_url}/portfolio/cash",
                headers=self._headers(require_auth=True),
                timeout=2.0
            )
            if res.status_code == 200:
                data = res.json()
                return float(data.get("available_cash", data.get("cash", 0.0)))
        except Exception:
            pass
        return None

    def submit_order(self, ticker: str, action: str, quantity: int, date: Optional[str] = None) -> Dict[str, Any]:
        """
        POST /api/v1/orders (Bearer JWT)
        Payload: {"ticker": ticker, "action": action, "quantity": quantity, "date": date}
        """
        # Defense-in-depth: Never dispatch live HTTP orders unless explicitly unlocked
        if not config.SUBMIT_LIVE_ORDERS:
            return {"success": False, "status": "REJECTED", "rejection_reason": "SAFETY_LOCK: SUBMIT_LIVE_ORDERS is disabled"}

        if not config.rest_base_url:
            return {"success": False, "status": "REJECTED", "rejection_reason": "SERVER_IP not configured"}
        if not config.BOT_ACCESS_TOKEN:
            return {"success": False, "status": "REJECTED", "rejection_reason": "BOT_ACCESS_TOKEN missing"}

        # Respect 120 req/minute rate limit
        if not self.rate_limiter.wait_and_acquire(timeout=1.5):
            return {"success": False, "status": "REJECTED", "rejection_reason": "RATE_LIMITED: 120 req/min exceeded"}

        # Validate inputs per PDF
        if action not in ("BUY", "SELL", "SHORT", "COVER"):
            return {"success": False, "status": "REJECTED", "rejection_reason": f"INVALID_ACTION: {action}"}
        if quantity <= 0 or quantity > 1_000_000:
            return {"success": False, "status": "REJECTED", "rejection_reason": f"INVALID_QUANTITY: {quantity}"}

        payload = {
            "ticker": ticker,
            "action": action,
            "quantity": int(quantity)
        }
        if date:
            payload["date"] = date

        try:
            res = self.session.post(
                f"{config.rest_base_url}/orders",
                json=payload,
                headers=self._headers(require_auth=True),
                timeout=3.0
            )

            if res.status_code in (200, 201):
                data = res.json()
                return {
                    "success": True,
                    "status": "FILLED",
                    "order_id": data.get("order_id", f"ord_{int(time.time()*1000)}"),
                    "fill_price": data.get("fill_price", data.get("price")),
                    "fee": config.BROKERAGE_PER_ORDER,
                    "response": data
                }
            else:
                err_code = "UNKNOWN_ERROR"
                try:
                    err_json = res.json()
                    err_code = err_json.get("error_code") or err_json.get("error") or res.text
                except Exception:
                    err_code = res.text[:120]

                return {
                    "success": False,
                    "status": "REJECTED",
                    "rejection_reason": err_code,
                    "http_status": res.status_code
                }
        except Exception as e:
            return {
                "success": False,
                "status": "REJECTED",
                "rejection_reason": f"CONNECTION_ERROR: {str(e)}"
            }


# Type alias for cleaner code
Tuple_status = tuple[bool, float, Optional[str]]

api_client = CompetitionAPIClient()
