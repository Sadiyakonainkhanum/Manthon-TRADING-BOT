import os
import base64
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load .env file from workspace root if present
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)


def get_current_wifi_ssid() -> Optional[str]:
    """Detects the currently connected Wi-Fi SSID on Windows safely."""
    try:
        res = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=2.0
        )
        for line in res.stdout.splitlines():
            if "SSID" in line and "BSSID" not in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    ssid = parts[1].strip()
                    if ssid:
                        return ssid
    except Exception:
        pass
    return None


def decode_jwt_claims(token: str) -> Dict[str, Any]:
    """Extracts claims from Bearer JWT payload safely."""
    if not token or "." not in token:
        return {}
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
            data = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
            return json.loads(data.decode("utf-8"))
    except Exception:
        pass
    return {}


class Config:
    """Trading Bot Configuration settings adhering to MANTHAN 2026 specification."""

    def __init__(self):
        self.reload()

    def reload(self):
        if ENV_PATH.exists():
            load_dotenv(dotenv_path=ENV_PATH, override=True)

        self.SERVER_IP: str = os.getenv("SERVER_IP", "").strip()
        self.ORDER_GATEWAY_PORT: int = int(os.getenv("ORDER_GATEWAY_PORT", "3002"))
        self.KAFKA_PORT: int = int(os.getenv("KAFKA_PORT", "9094"))
        self.PARTICIPANT_PORTAL_PORT: int = int(os.getenv("PARTICIPANT_PORTAL_PORT", "3003"))
        
        self.BOT_ACCESS_TOKEN: str = os.getenv("BOT_ACCESS_TOKEN", "").strip()
        
        # Decode claims from JWT token
        claims = decode_jwt_claims(self.BOT_ACCESS_TOKEN)
        jwt_username = claims.get("username", "")
        self.TEAM_ID: str = claims.get("team_id", "")
        self.TEAM_NAME: str = claims.get("team_name", "SynapStrike")
        self.IS_VERIFIED: bool = claims.get("is_verified", False)

        # Team username - fallback to token claim, then env var, then MN2645
        self.TEAM_USERNAME: str = os.getenv("TEAM_USERNAME", jwt_username or "mn2645").strip()

        # Paper / Demo mode by default. SUBMIT_LIVE_ORDERS must be explicitly set to true
        # before real competition orders are posted to /api/v1/orders
        live_orders_str = os.getenv("SUBMIT_LIVE_ORDERS", "false").lower()
        self.SUBMIT_LIVE_ORDERS: bool = live_orders_str in ("1", "true", "yes")

        # Demo mode: if True, generates realistic synthetic ticks & news for sandbox offline testing
        demo_str = os.getenv("DEMO_MODE", "true").lower()
        self.DEMO_MODE: bool = demo_str in ("1", "true", "yes")

        # Capital & Risk Parameters
        self.STARTING_CAPITAL: float = 1_000_000.0  # ₹10,00,000.00 virtual capital
        self.MIN_CASH_BUFFER_PCT: float = float(os.getenv("MIN_CASH_BUFFER_PCT", "0.20"))  # 20%
        self.MAX_STOCK_CONCENTRATION_PCT: float = float(os.getenv("MAX_STOCK_CONCENTRATION_PCT", "0.25"))  # 25%
        self.TARGET_ALLOCATION_PCT: float = float(os.getenv("TARGET_ALLOCATION_PCT", "0.03"))  # 3% target per BUY
        self.MIN_TRADE_VALUE: float = float(os.getenv("MIN_TRADE_VALUE", "5000.0"))  # Skip micro-trades below ₹5,000
        self.STOP_LOSS_PCT: float = float(os.getenv("STOP_LOSS_PCT", "0.035"))  # 3.5%
        self.TAKE_PROFIT_PCT: float = float(os.getenv("TAKE_PROFIT_PCT", "0.05"))  # 5.0%
        
        # Pacing & Rate Limits (Competition max is 120 req/min)
        self.MAX_ORDERS_PER_MINUTE: int = int(os.getenv("MAX_ORDERS_PER_MINUTE", "110"))
        self.DECISION_LATENCY_MAX_MS: int = int(os.getenv("DECISION_LATENCY_MAX_MS", "3000"))

        # Market Frictions
        self.BROKERAGE_PER_ORDER: float = 20.00  # Flat ₹20.00 per order
        self.DP_CHARGE_PER_SELL: float = 15.34   # Flat ₹15.34 on delivery SELL
        
        # Host & Port for Dashboard
        self.DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "127.0.0.1")
        self.DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8000"))

    @property
    def kafka_broker(self) -> Optional[str]:
        if self.SERVER_IP:
            return f"{self.SERVER_IP}:{self.KAFKA_PORT}"
        return None

    @property
    def rest_base_url(self) -> Optional[str]:
        if self.SERVER_IP:
            return f"http://{self.SERVER_IP}:{self.ORDER_GATEWAY_PORT}/api/v1"
        return None

    @property
    def portal_url(self) -> Optional[str]:
        if self.SERVER_IP:
            return f"http://{self.SERVER_IP}:{self.PARTICIPANT_PORTAL_PORT}"
        return None

    @property
    def masked_token(self) -> str:
        """Returns a safely masked representation of the token without exposing secrets."""
        if not self.BOT_ACCESS_TOKEN:
            return "[NOT SET]"
        if len(self.BOT_ACCESS_TOKEN) <= 10:
            return "***[CONFIGURED]***"
        return f"{self.BOT_ACCESS_TOKEN[:6]}...{self.BOT_ACCESS_TOKEN[-4:]}"

    @property
    def consumer_group_id(self) -> str:
        # Exactly required format: group-<your_team_username>
        clean_user = self.TEAM_USERNAME if self.TEAM_USERNAME else "MN2645"
        return f"group-{clean_user}"

    def update(self, server_ip: Optional[str] = None, token: Optional[str] = None, 
               team_username: Optional[str] = None, demo_mode: Optional[bool] = None,
               submit_live_orders: Optional[bool] = None):
        if server_ip is not None:
            self.SERVER_IP = server_ip.strip()
        if token is not None:
            self.BOT_ACCESS_TOKEN = token.strip()
            claims = decode_jwt_claims(self.BOT_ACCESS_TOKEN)
            if claims.get("username"):
                self.TEAM_USERNAME = claims["username"]
            if claims.get("team_id"):
                self.TEAM_ID = claims["team_id"]
            if claims.get("team_name"):
                self.TEAM_NAME = claims["team_name"]
            if "is_verified" in claims:
                self.IS_VERIFIED = claims["is_verified"]
        if team_username is not None and team_username.strip():
            self.TEAM_USERNAME = team_username.strip()
        if demo_mode is not None:
            self.DEMO_MODE = demo_mode
        if submit_live_orders is not None:
            self.SUBMIT_LIVE_ORDERS = submit_live_orders


config = Config()

