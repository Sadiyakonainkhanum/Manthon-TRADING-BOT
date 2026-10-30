import time
import asyncio
import logging
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engine.config import config
from engine.state import state
from engine.bot_service import bot_master
from engine.execution_engine import execution_engine

logger = logging.getLogger("TelemetryServer")

app = FastAPI(
    title="MANTHAN 2026 Autonomous Trading Hub",
    description="Decoupled Quantitative Telemetry & Strategy Control Dashboard",
    version="1.0.0"
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ConfigUpdateRequest(BaseModel):
    server_ip: Optional[str] = None
    bot_access_token: Optional[str] = None
    team_username: Optional[str] = None
    demo_mode: Optional[bool] = None
    submit_live_orders: Optional[bool] = None


class ManualOrderRequest(BaseModel):
    ticker: str
    action: str  # BUY | SELL | SHORT | COVER
    quantity: int


class EmergencyStopRequest(BaseModel):
    active: bool


class VoiceQueryRequest(BaseModel):
    query: str
    persona: Optional[str] = "agnes"


@app.on_event("startup")
async def on_startup():
    """Starts the trading bot master service in the background."""
    bot_master.start()


@app.on_event("shutdown")
async def on_shutdown():
    """Stops the trading bot master service gracefully."""
    bot_master.stop()


@app.get("/api/telemetry")
async def get_telemetry():
    """Returns complete real-time snapshot of the trading bot state."""
    return state.get_snapshot()


@app.get("/api/agents")
async def get_agents():
    """Returns real-time decisions, briefs, and confidence from Agnes and Jeff."""
    with state.lock:
        return {
            "agents": {
                "agnes": {
                    "name": "Agnes",
                    "role": "Market & Sentiment Intelligence Analyst"
                },
                "jeff": {
                    "name": "Jeff",
                    "role": "Strategic Decision Agent"
                }
            },
            "decisions": state.agent_decisions,
            "timestamp": time.strftime("%H:%M:%S")
        }


@app.get("/api/stocks/{ticker}/history")
async def get_stock_history(ticker: str):
    """Returns rolling price history for a given ticker."""
    with state.lock:
        history = state.price_history.get(ticker, [])
        return {
            "ticker": ticker,
            "prices": history[-60:],
            "count": len(history[-60:])
        }


@app.get("/api/config")
async def get_config():
    """Returns current environment coordinates and status without exposing raw secrets."""
    return {
        "server_ip": config.SERVER_IP,
        "kafka_port": config.KAFKA_PORT,
        "order_gateway_port": config.ORDER_GATEWAY_PORT,
        "portal_port": config.PARTICIPANT_PORTAL_PORT,
        "team_username": config.TEAM_USERNAME,
        "team_name": config.TEAM_NAME,
        "team_id": config.TEAM_ID,
        "is_verified": config.IS_VERIFIED,
        "consumer_group_id": config.consumer_group_id,
        "token_configured": bool(config.BOT_ACCESS_TOKEN),
        "masked_token": config.masked_token,
        "demo_mode": state.is_demo_mode,
        "submit_live_orders": config.SUBMIT_LIVE_ORDERS,
        "emergency_stop": state.emergency_stop,
        "kafka_broker": config.kafka_broker,
        "rest_base_url": config.rest_base_url,
        "portal_url": config.portal_url
    }


@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    """Updates connection coordinates dynamically and applies them to engine."""
    config.update(
        server_ip=req.server_ip,
        token=req.bot_access_token,
        team_username=req.team_username,
        demo_mode=req.demo_mode,
        submit_live_orders=req.submit_live_orders
    )
    if req.demo_mode is not None and req.demo_mode != state.is_demo_mode:
        bot_master.switch_mode(req.demo_mode)
    return {"status": "ok", "message": "Configuration updated successfully"}


@app.post("/api/emergency-stop")
async def set_emergency_stop(req: EmergencyStopRequest):
    """Activates or deactivates emergency stop kill-switch."""
    bot_master.set_emergency_stop(req.active)
    return {"status": "ok", "emergency_stop": state.emergency_stop}


@app.post("/api/reset-capital")
async def reset_capital():
    """Resets virtual demo capital back to ₹10,00,000."""
    state.reset_capital()
    return {"status": "ok", "message": "Testing capital reset to ₹10,00,000.00"}


@app.post("/api/orders/manual")
async def manual_order(req: ManualOrderRequest):
    """Manually dispatches an order for testing purposes."""
    if req.action not in ("BUY", "SELL", "SHORT", "COVER"):
        raise HTTPException(status_code=400, detail="Invalid action")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive integer")

    res = execution_engine.execute_order(
        ticker=req.ticker,
        action=req.action,
        quantity=req.quantity,
        strategy_reason="Manual Operator Trade"
    )
    return res


@app.websocket("/ws")
async def websocket_telemetry(websocket: WebSocket):
    """High-speed WebSocket feed streaming real-time metrics every 1 second."""
    await websocket.accept()
    try:
        while True:
            snapshot = state.get_snapshot()
            await websocket.send_json(snapshot)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


@app.post("/api/ai/voice-query")
async def voice_query(req: VoiceQueryRequest):
    """Processes natural language voice query for Agnes and Jeff AI assistant."""
    from engine.voice_assistant import voice_assistant
    res = voice_assistant.process_query(req.query, req.persona or "agnes")
    return res


# Mount Static UI Files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(STATIC_DIR / "index.html")

