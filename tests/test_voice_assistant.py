import pytest
from engine.state import state
from engine.voice_assistant import voice_assistant


def test_voice_assistant_profit_inquiry():
    state.realized_pnl = 45000.0
    state.available_cash = 950000.0
    res = voice_assistant.process_query("what is our current profit?")
    assert "profit" in res["voice_text"].lower() or "wealth" in res["voice_text"].lower()
    assert res["persona"] == "Jeff"
    assert res["action"] is None


def test_voice_assistant_emergency_halt_action():
    state.emergency_stop = False
    res = voice_assistant.process_query("emergency stop trading immediately")
    assert state.emergency_stop is True
    assert res["action"] == "HALT_TRADING"
    assert "halted" in res["voice_text"].lower() or "stop" in res["voice_text"].lower()


def test_voice_assistant_resume_trading_action():
    state.emergency_stop = True
    res = voice_assistant.process_query("resume trading now")
    assert state.emergency_stop is False
    assert res["action"] == "RESUME_TRADING"


def test_voice_assistant_switch_ticker_chart():
    res = voice_assistant.process_query("switch chart to ROUT")
    assert res["action"] == "SWITCH_TICKER"
    assert res["action_param"] == "ROUT"
    assert "ROUT" in res["voice_text"]


def test_voice_assistant_phonetic_ticker_recognition():
    res = voice_assistant.process_query("why is aerox moving?")
    assert res["action"] == "SWITCH_TICKER"
    assert res["action_param"] == "AERX"


def test_voice_assistant_cash_reserve_query():
    state.available_cash = 800000.0
    res = voice_assistant.process_query("how much cash reserve do we have?")
    assert "cash" in res["voice_text"].lower()
    assert res["persona"] == "Agnes"


def test_voice_assistant_navigation_commands():
    res_orders = voice_assistant.process_query("show order history")
    assert res_orders["action"] == "SWITCH_TAB"
    assert res_orders["action_param"] == "orders"

    res_diag = voice_assistant.process_query("show tax and diagnostics")
    assert res_diag["action"] == "SWITCH_TAB"
    assert res_diag["action_param"] == "diagnostics"

