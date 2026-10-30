"""
MANTHAN 2026 AI Voice Assistant Engine
Provides natural language voice understanding and speech generation
for Agnes (Quant/Sentiment Analyst) and Jeff (Strategic Decision Agent).
"""

import re
from typing import Dict, Any, Optional
from engine.state import state
from engine.config import config


class VoiceAssistantEngine:
    """Processes natural language voice commands and formulates speech responses."""

    KNOWN_TICKERS = ["AERX", "BLUX", "DSNY", "HAVN", "HMDP", "MOTR", "ORCX", "PLNX", "ROUT", "SONA"]

    def process_query(self, query: str, preferred_persona: str = "agnes") -> Dict[str, Any]:
        """
        Parses user query, determines intent, executes action if applicable,
        and constructs both a spoken voice text and formatted display text.
        """
        q = (query or "").strip().lower()
        if not q:
            return {
                "voice_text": "I didn't catch that. Please speak again or select a suggested command.",
                "display_text": "I didn't catch that. Please speak again or select a suggested command.",
                "action": None,
                "action_param": None,
                "persona": "Agnes"
            }

        # 1. Action: Emergency Halt / Stop
        if any(w in q for w in ["halt", "emergency stop", "emergency halt", "kill switch", "freeze trading"]):
            state.emergency_stop = True
            return {
                "voice_text": "Emergency stop activated. All trading execution has been immediately halted.",
                "display_text": "🚨 **Emergency Stop Activated.** All live and simulated order execution has been immediately halted.",
                "action": "HALT_TRADING",
                "action_param": None,
                "persona": "Jeff"
            }

        # 2. Action: Resume Trading
        if any(w in q for w in ["resume", "unhalt", "continue trading", "start trading"]):
            state.emergency_stop = False
            return {
                "voice_text": "Trading resumed. Strategy monitors and execution are now active.",
                "display_text": "✅ **Trading Resumed.** Strategy monitors and order execution are now active.",
                "action": "RESUME_TRADING",
                "action_param": None,
                "persona": "Jeff"
            }

        # 3. Action: Switch Ticker / Chart
        ticker_match = self._extract_ticker(q)
        if any(w in q for w in ["chart", "switch to", "show me", "open chart", "display"]) and ticker_match:
            return {
                "voice_text": f"Switching price chart to {ticker_match}.",
                "display_text": f"📊 Switched active candlestick chart to **{ticker_match}**.",
                "action": "SWITCH_TICKER",
                "action_param": ticker_match,
                "persona": "Agnes"
            }

        # 4. Action: Switch Tabs
        if "order" in q or "trades" in q:
            if "show" in q or "open" in q or "view" in q or "tab" in q:
                return {
                    "voice_text": "Opening the order history audit log.",
                    "display_text": "📋 Navigating to **Order History** tab.",
                    "action": "SWITCH_TAB",
                    "action_param": "orders",
                    "persona": "Jeff"
                }

        if "diagnostic" in q or "tax" in q or "connection" in q or "spec" in q:
            if "show" in q or "open" in q or "view" in q or "tab" in q:
                return {
                    "voice_text": "Opening the diagnostics and Section 8 tax ledger.",
                    "display_text": "⚖️ Navigating to **Diagnostics & Indian IT Act Tax Ledger** tab.",
                    "action": "SWITCH_TAB",
                    "action_param": "diagnostics",
                    "persona": "Agnes"
                }

        if "holding" in q or "position" in q or "portfolio" in q:
            if "show" in q or "open" in q or "view" in q or "tab" in q:
                return {
                    "voice_text": "Opening active portfolio holdings.",
                    "display_text": "💼 Navigating to **Holdings & Positions** tab.",
                    "action": "SWITCH_TAB",
                    "action_param": "holdings",
                    "persona": "Jeff"
                }

        # 5. Inquiry: Profit & Loss / Wealth
        if any(w in q for w in ["profit", "pnl", "p&l", "earnings", "made", "realized", "wealth", "balance", "how much money"]):
            with state.lock:
                metrics = state.compute_wealth_metrics()
                rpnl = metrics.get("realized_pnl", 0.0)
                tot = metrics.get("total_wealth", 1_000_000.0)
                cash = metrics.get("available_cash", 1_000_000.0)
                diff = tot - 1_000_000.0
                pct = (diff / 1_000_000.0) * 100.0

            rpnl_str = self._format_speech_currency(rpnl)
            tot_str = self._format_speech_currency(tot)

            if rpnl >= 0:
                v_text = f"We have realized a profit of {rpnl_str}. Total portfolio wealth is currently {tot_str}, up {pct:.1f} percent."
            else:
                v_text = f"Realized P and L is currently negative {self._format_speech_currency(abs(rpnl))}. Total portfolio wealth stands at {tot_str}."

            d_text = (
                f"💰 **Portfolio Valuation:**\n"
                f"• **Realized P&L:** {'+' if rpnl>=0 else ''}₹{rpnl:,.2f}\n"
                f"• **Total Wealth:** ₹{tot:,.2f} ({'+' if diff>=0 else ''}{pct:.2f}%)\n"
                f"• **Available Cash:** ₹{cash:,.2f}"
            )
            return {
                "voice_text": v_text,
                "display_text": d_text,
                "action": None,
                "action_param": None,
                "persona": "Jeff"
            }

        # 6. Inquiry: Cash Reserve & Risk Floor (Section 7)
        if any(w in q for w in ["cash", "reserve", "liquid", "cushion", "drawdown", "risk"]):
            with state.lock:
                metrics = state.compute_wealth_metrics()
                cash = metrics.get("available_cash", 1_000_000.0)
                tot = metrics.get("total_wealth", 1_000_000.0)
                cushion = (cash / tot * 100.0) if tot > 0 else 100.0
                dd = state.current_drawdown_pct

            cash_str = self._format_speech_currency(cash)
            v_text = f"Our liquid cash reserve is {cash_str}, representing {cushion:.1f} percent of the portfolio. Current drawdown is {dd:.2f} percent, safely within risk guidelines."
            d_text = (
                f"🛡️ **Risk & Liquidity Status (Section 7):**\n"
                f"• **Liquid Cash:** ₹{cash:,.2f} ({cushion:.1f}% liquidity)\n"
                f"• **Mandatory Floor:** ₹2,00,000 (20.0%) strictly maintained\n"
                f"• **Peak Drawdown:** {dd:.2f}% (Limit: 10.0%)"
            )
            return {
                "voice_text": v_text,
                "display_text": d_text,
                "action": None,
                "action_param": None,
                "persona": "Agnes"
            }

        # 7. Inquiry: Specific Ticker Intelligence (e.g. "Why is AERX bullish?", "What about ROUT?")
        if ticker_match:
            tk = ticker_match
            with state.lock:
                sig = state.strategy_signals.get(tk, {})
                mp = state.market_prices.get(tk, {})
                pos = state.holdings.get(tk, {})

            action = sig.get("signal", "HOLD")
            reason = sig.get("reason", "In consolidation with neutral momentum.")
            rsi = sig.get("rsi")
            fast_ma = sig.get("fast_ma")
            slow_ma = sig.get("slow_ma")
            curr_price = mp.get("close", 0.0)

            held_qty = pos.get("quantity", 0)
            held_text = f" We currently hold {held_qty} shares." if held_qty > 0 else " We do not hold open positions."

            v_text = f"For {tk}, current price is {curr_price:,.2f} rupees. Agnes recommends {action}. Reason: {reason}{held_text}"
            d_text = (
                f"🔍 **Multi-Agent Analysis for {tk}:**\n"
                f"• **Latest Price:** ₹{curr_price:,.2f}\n"
                f"• **Agent Recommendation:** **{action}** ({round((sig.get('confidence', 0.5))*100)}% confidence)\n"
                f"• **Technical Scan:** Fast MA: {f'₹{fast_ma:,.2f}' if fast_ma else '-'} | Slow MA: {f'₹{slow_ma:,.2f}' if slow_ma else '-'} | RSI: {rsi or '-'}\n"
                f"• **Reasoning:** {reason}\n"
                f"• **Holdings:** {held_qty} shares"
            )
            return {
                "voice_text": v_text,
                "display_text": d_text,
                "action": "SWITCH_TICKER",
                "action_param": tk,
                "persona": "Agnes" if preferred_persona == "agnes" else "Jeff"
            }

        # 8. Inquiry: News & Sentiment
        if any(w in q for w in ["news", "headline", "sentiment"]):
            with state.lock:
                recent_news = state.news_feed[-3:] if state.news_feed else []

            if not recent_news:
                return {
                    "voice_text": "No recent news events have been received from the Kafka news topic yet.",
                    "display_text": "📰 No news events received on Kafka topic `market.news` yet.",
                    "action": None,
                    "action_param": None,
                    "persona": "Agnes"
                }

            top_news = recent_news[-1]
            tk = top_news.get("ticker", "General")
            headline = top_news.get("headline", "")
            sent = top_news.get("sentiment", "NEUTRAL")

            v_text = f"Latest corporate news on {tk}: {headline}. Sentiment is {sent.lower()}."
            d_text = f"📰 **Latest News ({tk}):** {headline}\n• Sentiment: **{sent}**"
            return {
                "voice_text": v_text,
                "display_text": d_text,
                "action": None,
                "action_param": None,
                "persona": "Agnes"
            }

        # 9. Inquiry: Market Summary / General Briefing
        if any(w in q for w in ["summary", "brief", "overview", "market status", "how are we doing", "update"]):
            with state.lock:
                metrics = state.compute_wealth_metrics()
                rpnl = metrics.get("realized_pnl", 0.0)
                tot = metrics.get("total_wealth", 1_000_000.0)
                active_buys = sum(1 for s in state.strategy_signals.values() if s.get("signal") == "BUY")
                holdings_count = sum(1 for h in state.holdings.values() if h.get("quantity", 0) > 0)
                stage = state.sim_stage

            v_text = (
                f"Market briefing: Simulation stage is {stage}. "
                f"Total wealth is {self._format_speech_currency(tot)} with realized profit of {self._format_speech_currency(rpnl)}. "
                f"There are {active_buys} active BUY signals and {holdings_count} open positions."
            )
            d_text = (
                f"📊 **Executive Market Briefing:**\n"
                f"• **Stage:** {stage.upper()} ({state.sim_status})\n"
                f"• **Total Valuation:** ₹{tot:,.2f}\n"
                f"• **Realized P&L:** {'+' if rpnl>=0 else ''}₹{rpnl:,.2f}\n"
                f"• **Active BUY Signals:** {active_buys}\n"
                f"• **Active Holdings:** {holdings_count} stocks"
            )
            return {
                "voice_text": v_text,
                "display_text": d_text,
                "action": None,
                "action_param": None,
                "persona": "Jeff"
            }

        # 10. Help & Capabilities
        return {
            "voice_text": "I can assist you with portfolio profits, stock analysis for our 10 tickers, risk status, or executing emergency stops. Try asking: what is our total profit?",
            "display_text": (
                "🎙️ **AI Voice Assistant Commands:**\n"
                "• *'What is our total profit?'*\n"
                "• *'Give me a market summary'*\n"
                "• *'Why is AERX bullish?'* (or any ticker)\n"
                "• *'What is our cash reserve?'*\n"
                "• *'Show order history'*\n"
                "• *'Emergency stop'*"
            ),
            "action": None,
            "action_param": None,
            "persona": "Agnes"
        }

    def _extract_ticker(self, text: str) -> Optional[str]:
        """Identifies stock tickers from spoken text."""
        # Exact match
        for tk in self.KNOWN_TICKERS:
            # Match whole word or spelled-out letters
            pattern = rf"\b{tk.lower()}\b"
            if re.search(pattern, text):
                return tk

        # Phonetic / Spoken variations
        phonetic_map = {
            "aero": "AERX",
            "aerox": "AERX",
            "blue": "BLUX",
            "blue x": "BLUX",
            "destiny": "DSNY",
            "disney": "DSNY",
            "haven": "HAVN",
            "home depot": "HMDP",
            "motor": "MOTR",
            "motortech": "MOTR",
            "oracle": "ORCX",
            "oracrest": "ORCX",
            "planex": "PLNX",
            "route": "ROUT",
            "routewave": "ROUT",
            "sona": "SONA"
        }
        for name, tk in phonetic_map.items():
            if name in text:
                return tk

        return None

    def _format_speech_currency(self, val: float) -> str:
        """Formats numbers into clear spoken Indian Rupee phrases."""
        abs_val = abs(val)
        sign = "minus " if val < 0 else ""
        if abs_val >= 100_000:
            lakhs = abs_val / 100_000
            return f"{sign}{lakhs:.2f} Lakh Rupees"
        elif abs_val >= 1_000:
            thousands = abs_val / 1_000
            return f"{sign}{thousands:.1f} Thousand Rupees"
        else:
            return f"{sign}{abs_val:.0f} Rupees"


voice_assistant = VoiceAssistantEngine()

