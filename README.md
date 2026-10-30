# MANTHAN 2026: Autonomous Trading Systems Hub

**Team Consumer Group:** `group-MN2645`  
**Host Institution:** Jawaharlal Nehru New College of Engineering (JNNCE), Shivamogga  
**Department:** Department of Computer Science & Engineering (Data Science)  
**Hackathon Domain:** Autonomous Trading Systems (*"Churn Data, Discover Truth"*)  

---

## 1. Architectural Overview

The MANTHAN Autonomous Trading Hub is designed strictly to the competition specifications outlined in the problem statement:

```text
+------------------------------------+          +------------------------------------+
|     Kafka Market Data Stream       |          |        MANTHAN Trading Bot         |
|     (Broker: <SERVER_IP>:9094)     |  Streams |      (Python / FastAPI Engine)     |
| Topics:                            |  Ticks & | - Ingests ticks & news in real time|
| - market.ticks (OHLCV candles)     |--------->| - 5D/20D MA & News Sentiment Engine|
| - market.news  (News flashes)      |  (group- | - Risk checks & position sizing    |
|                                    |  MN2645) | - Submits automated trades (<3-4s) |
+------------------------------------+          +------------------------------------+
                                                                  |
                                                                  | Submits Orders
                                                                  v (POST /api/v1/orders)
+------------------------------------+          +------------------------------------+
|         Participant Portal         |          |       Order Execution Gateway      |
|            (Port 3003)             |<---------|            (Port 3002)             |
| - Real-time Portfolio & P&L        |  Updates | - Validates JWT Bearer Token       |
| - Pre-Flight Bot Readiness Status  |          | - Checks Capital & Margin Limits   |
| - Interactive API Explorer & Docs  |          | - Deducts Brokerage (₹20), DP, Tax |
+------------------------------------+          +------------------------------------+
```

### Core Engine Subsystems
- **Kafka Consumer (`engine/kafka_consumer.py`):** Subscribes to `market.ticks` and `market.news` with consumer group `group-MN2645`, `auto_offset_reset='latest'`, and `enable_auto_commit=False` across 10 partitions.
- **Pre-Flight Sequence Heartbeat (`engine/heartbeat_worker.py`):** Listens for `preflight_tick` standby events and continuously acknowledges sequence numbers via `POST /api/v1/bot/heartbeat` within the required 15-second window.
- **Lifecycle Poller (`engine/heartbeat_worker.py`):** Continuously queries `GET /api/v1/stage`. Order submissions activate only when `stage=simulation` and `status=RUNNING`. Orders immediately pause when status is `PAUSED` or `COMPLETED`.
- **Dynamic Universe Discovery (`engine/universe_manager.py`):** Dynamically loads the tradable stock universe via `GET /api/v1/stocks` and warms up rolling price buffers via `GET /api/v1/stocks/:ticker/history?days=90` (anti-lookahead protected).
- **Dual Strategy Engine (`engine/strategy.py` & `engine/indicators.py`):**
  - **Strategy 1:** 5-Day Fast MA vs 20-Day Slow MA trend crossover.
  - **Strategy 2:** Mean reversion dip buying (>4% 3-day drop oversold trigger).
  - **Strategy 3:** Corporate news headline keyword matching (`PROFIT`, `SURGE`, `GROWTH`, `RECORD`, `BEAT`, etc. vs `LOSS`, `PLUNGE`, `DROP`, `FRAUD`, etc.).
- **Risk Management & Capital Preservation (`engine/risk_manager.py`):**
  - Enforces minimum 20% liquid cash reserve cushion.
  - Caps single-stock allocation at 25% of total wealth.
  - Implements a hard 3.5% stop-loss liquidation rule.
  - Tracks 100% short sell margin collateral and the 10-day bi-weekly short square-off cycle.
  - **Duplicate Order Prevention:** Prevents firing multiple orders for the same ticker on the same simulated day.
  - **Client-Side Rate Limiter:** Throttled to 110 requests/min (under the 120 req/min platform penalty limit).
- **Safety Mode:** Operates in **Paper Trading Mode** by default. Submitting actual orders to `/api/v1/orders` requires explicit configuration (`SUBMIT_LIVE_ORDERS=true`).

---

## 2. Quick Setup & Run Commands

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Run Unit Tests
Verify that all 21 strategy, risk, indicator, and lifecycle tests pass:
```bash
pytest -v
```

### Step 3: Launch the Trading Hub
```bash
python run.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## 3. Connecting to the Venue Network

### Missing Venue Configuration Checklist
To trade live on the competition exchange, the following details must be obtained at the venue:

1. **Venue Wi-Fi Connection:** Connect laptop to the official venue Wi-Fi network (private competition subnet).
2. **Competition Server IP (`SERVER_IP`):** The server IP announced at the registration desk (e.g., `192.168.1.xxx` or `172.x.x.x`).
3. **Persistent Bearer Token (`BOT_ACCESS_TOKEN`):** Copied from Step 1 of the Participant Guide UI at `http://<SERVER_IP>:3003`.
4. **Physical Desk Verification:** Complete team verification at the registration desk (unverified accounts cannot place orders).

### Configuring Credentials
Configure credentials in `.env` or click the **Settings** button in the dashboard:

```bash
# .env file
SERVER_IP=192.168.1.100       # Replace with actual venue server IP
ORDER_GATEWAY_PORT=3002
KAFKA_PORT=9094
BOT_ACCESS_TOKEN=eyJhbGci...  # Paste your JWT token here
TEAM_USERNAME=MN2645          # Exact team group: group-MN2645
DEMO_MODE=false               # Connects to live venue Kafka and REST
SUBMIT_LIVE_ORDERS=true       # Enables live order submission (set true for live trades)
```

---

## 4. API Endpoints Reference

All authenticated endpoints require header: `Authorization: Bearer <BOT_ACCESS_TOKEN>`

| Method | Endpoint | Auth | Purpose |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/bot/heartbeat` | Bearer JWT | Send standby heartbeat sequence ACK: `{"seq": N}` |
| `GET` | `/api/v1/stage` | Public | Real-time platform lifecycle: stage & status |
| `GET` | `/api/v1/simulation/clock` | Public | Simulation clock: current day, remaining days |
| `GET` | `/api/v1/stocks` | Bearer JWT | Dynamic tradable stock discovery |
| `GET` | `/api/v1/stocks/:ticker/history` | Optional | Historical daily OHLCV bars for indicator warm-up |
| `POST` | `/api/v1/orders` | Bearer JWT | Submit market order: `{"ticker": "...", "action": "BUY\|SELL\|SHORT\|COVER", "quantity": N}` |
| `GET` | `/api/v1/orders` | Bearer JWT | Historical order audit log and rejection reasons |
| `GET` | `/api/v1/portfolio` | Bearer JWT | Cash, stock holdings, valuations, margin, net P&L |
| `GET` | `/api/v1/portfolio/cash` | Bearer JWT | Lightweight query for available cash |
