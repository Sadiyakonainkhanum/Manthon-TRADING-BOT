import time
from typing import Dict, Any, Optional
from engine.config import config
from engine.state import state
from engine.risk_manager import risk_manager
from engine.api_client import api_client
from engine.tax_calculator import tax_calculator


class ExecutionEngine:
    """Manages order validation, dispatch, friction accounting, and portfolio bookkeeping."""

    def execute_order(self, ticker: str, action: str, quantity: int, 
                      current_price: Optional[float] = None, 
                      simulated_date: Optional[str] = None,
                      strategy_reason: str = "") -> Dict[str, Any]:
        """Submits an order either to the live gateway, paper engine, or internal demo engine."""
        with state.lock:
            if current_price is None or current_price <= 0:
                current_price = state.market_prices.get(ticker, {}).get("close", 1000.0)

            # 1. Duplicate Order Prevention per Ticker & Simulated Day
            if simulated_date:
                day_key = f"{ticker}:{simulated_date}"
                if day_key in state.daily_executed_orders:
                    log_entry = {
                        "id": f"ord_dup_{int(time.time()*1000)}",
                        "timestamp": time.strftime("%H:%M:%S"),
                        "ticker": ticker,
                        "action": action,
                        "quantity": quantity,
                        "price": round(current_price, 2),
                        "status": "REJECTED",
                        "rejection_reason": f"DUPLICATE_ORDER_PREVENTED: Already executed an order for {ticker} on {simulated_date}",
                        "strategy_reason": strategy_reason,
                        "fee": 0.0,
                        "is_demo": state.is_demo_mode
                    }
                    state.order_log.append(log_entry)
                    return log_entry

            # 2. Pre-trade Risk Validation
            is_valid, reject_reason = risk_manager.validate_order(ticker, action, quantity, current_price)
            if not is_valid:
                log_entry = {
                    "id": f"ord_rej_{int(time.time()*1000)}",
                    "timestamp": time.strftime("%H:%M:%S"),
                    "ticker": ticker,
                    "action": action,
                    "quantity": quantity,
                    "price": round(current_price, 2),
                    "status": "REJECTED",
                    "rejection_reason": reject_reason,
                    "strategy_reason": strategy_reason,
                    "fee": 0.0,
                    "is_demo": state.is_demo_mode
                }
                state.order_log.append(log_entry)
                self._record_decision(ticker, action, quantity, current_price, simulated_date, strategy_reason, log_entry)
                return log_entry

            # 3. If in LIVE mode and server configured
            if not state.is_demo_mode and config.rest_base_url:
                if not config.SUBMIT_LIVE_ORDERS:
                    # SAFE DEFAULT: Paper Mode when SUBMIT_LIVE_ORDERS is false
                    fee = config.BROKERAGE_PER_ORDER
                    if action == "SELL":
                        fee += config.DP_CHARGE_PER_SELL
                    exec_price = current_price
                    order_id = f"paper_ord_{int(time.time()*1000)}"

                    log_entry = {
                        "id": order_id,
                        "timestamp": time.strftime("%H:%M:%S"),
                        "ticker": ticker,
                        "action": action,
                        "quantity": quantity,
                        "price": round(exec_price, 2),
                        "status": "FILLED",
                        "rejection_reason": None,
                        "strategy_reason": f"[PAPER MODE] {strategy_reason}",
                        "fee": fee,
                        "is_demo": False
                    }
                    state.order_log.append(log_entry)
                    if simulated_date:
                        state.daily_executed_orders.add(f"{ticker}:{simulated_date}")
                    self._update_local_portfolio(ticker, action, quantity, exec_price, fee, is_demo=False, simulated_date=simulated_date)
                    self._record_decision(ticker, action, quantity, exec_price, simulated_date, strategy_reason, log_entry)
                    return log_entry

                # STAGE SAFETY GUARD: Block live gateway submission if simulation is paused, idle, or completed
                if str(state.sim_stage).lower() not in ("simulation", "development") or str(state.sim_status).upper() in ("PAUSED", "COMPLETED", "IDLE"):
                    log_entry = {
                        "id": f"ord_stage_{int(time.time()*1000)}",
                        "timestamp": time.strftime("%H:%M:%S"),
                        "ticker": ticker,
                        "action": action,
                        "quantity": quantity,
                        "price": round(current_price, 2),
                        "status": "REJECTED",
                        "rejection_reason": f"STAGE_SAFETY_LOCK: Cannot submit live orders when stage is '{state.sim_stage}' and status is '{state.sim_status}'",
                        "strategy_reason": strategy_reason,
                        "fee": 0.0,
                        "is_demo": False
                    }
                    state.order_log.append(log_entry)
                    return log_entry

                # EXPLICIT LIVE ORDER: Submits to competition gateway
                res = api_client.submit_order(ticker, action, quantity, simulated_date)
                order_id = res.get("order_id", f"ord_{int(time.time()*1000)}")
                status = res.get("status", "REJECTED")
                
                fill_price_raw = res.get("fill_price")
                if fill_price_raw is not None and isinstance(fill_price_raw, (int, float)) and fill_price_raw > 0:
                    exec_price = float(fill_price_raw)
                elif current_price is not None and isinstance(current_price, (int, float)) and current_price > 0:
                    exec_price = float(current_price)
                else:
                    exec_price = 0.0

                fee = config.BROKERAGE_PER_ORDER if status == "FILLED" else 0.0
                if action == "SELL" and status == "FILLED":
                    fee += config.DP_CHARGE_PER_SELL

                log_entry = {
                    "id": order_id,
                    "timestamp": time.strftime("%H:%M:%S"),
                    "ticker": ticker,
                    "action": action,
                    "quantity": quantity,
                    "price": round(exec_price, 2),
                    "status": status,
                    "rejection_reason": res.get("rejection_reason"),
                    "strategy_reason": strategy_reason,
                    "fee": fee,
                    "is_demo": False
                }
                state.order_log.append(log_entry)

                if status == "FILLED":
                    if simulated_date:
                        state.daily_executed_orders.add(f"{ticker}:{simulated_date}")
                    self._update_local_portfolio(ticker, action, quantity, exec_price, fee, is_demo=False, simulated_date=simulated_date)
                
                self._record_decision(ticker, action, quantity, exec_price, simulated_date, strategy_reason, log_entry)
                return log_entry

            # 4. DEMO Execution (Accurately mirrors platform exchange mechanics)
            fee = config.BROKERAGE_PER_ORDER
            if action == "SELL":
                fee += config.DP_CHARGE_PER_SELL

            exec_price = current_price
            order_id = f"demo_ord_{int(time.time()*1000)}"

            log_entry = {
                "id": order_id,
                "timestamp": time.strftime("%H:%M:%S"),
                "ticker": ticker,
                "action": action,
                "quantity": quantity,
                "price": round(exec_price, 2),
                "status": "FILLED",
                "rejection_reason": None,
                "strategy_reason": strategy_reason,
                "fee": fee,
                "is_demo": True
            }
            state.order_log.append(log_entry)
            if simulated_date:
                state.daily_executed_orders.add(f"{ticker}:{simulated_date}")
            self._update_local_portfolio(ticker, action, quantity, exec_price, fee, is_demo=True, simulated_date=simulated_date)
            self._record_decision(ticker, action, quantity, exec_price, simulated_date, strategy_reason, log_entry)
            return log_entry

    def _record_decision(self, ticker: str, action: str, quantity: int, price: float,
                         simulated_date: Optional[str], strategy_reason: str, log_entry: Dict[str, Any]):
        """Maintains an auditable log of trading decisions and rationales."""
        decision = {
            "timestamp": time.strftime("%H:%M:%S"),
            "simulated_date": simulated_date or state.sim_current_date,
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "price": round(price, 2),
            "status": log_entry.get("status"),
            "strategy_reason": strategy_reason,
            "rejection_reason": log_entry.get("rejection_reason")
        }
        state.decision_audit_trail.append(decision)
        if len(state.decision_audit_trail) > 200:
            state.decision_audit_trail = state.decision_audit_trail[-200:]

    def _update_local_portfolio(self, ticker: str, action: str, quantity: int, 
                                price: float, fee: float, is_demo: bool,
                                simulated_date: Optional[str] = None):
        """Updates internal cash, holdings, locked margin, realized P&L, and Indian Capital Gains Tax ledger."""
        trade_val = quantity * price
        state.total_brokerage_paid += config.BROKERAGE_PER_ORDER
        if action == "SELL":
            state.total_dp_charges_paid += config.DP_CHARGE_PER_SELL

        pos = state.holdings.get(ticker, {
            "quantity": 0, "avg_price": 0.0, "position_type": "LONG", "margin_locked": 0.0, "is_demo": is_demo
        })

        current_date_str = simulated_date or state.sim_current_date or time.strftime("%Y-%m-%d")

        if action == "BUY":
            # If we had a short, BUY covers it first
            if pos["position_type"] == "SHORT" and pos["quantity"] > 0:
                short_qty = pos["quantity"]
                cover_qty = min(short_qty, quantity)
                # Profit on short = (short_entry_price - cover_price) * quantity
                pnl = (pos["avg_price"] - price) * cover_qty
                state.realized_pnl += pnl
                # Release locked margin
                margin_release = cover_qty * pos["avg_price"]
                state.margin_locked = max(0.0, state.margin_locked - margin_release)
                state.available_cash += (margin_release + pnl - fee)

                # Record capital gains tax for covered short
                entry_date_str = pos.get("entry_date", current_date_str)
                tax_calculator.record_trade(
                    ticker=ticker,
                    action="COVER",
                    quantity=cover_qty,
                    entry_price=price,
                    exit_price=pos["avg_price"],
                    entry_date=entry_date_str,
                    exit_date=current_date_str
                )

                remaining_short = short_qty - cover_qty
                remaining_buy = quantity - cover_qty

                if remaining_short > 0:
                    pos["quantity"] = remaining_short
                    state.holdings[ticker] = pos
                elif remaining_buy > 0:
                    # Excess becomes new long position
                    pos["position_type"] = "LONG"
                    pos["quantity"] = remaining_buy
                    pos["avg_price"] = price
                    pos["entry_date"] = current_date_str
                    state.available_cash -= (remaining_buy * price)
                    state.holdings[ticker] = pos
                else:
                    del state.holdings[ticker]
            else:
                # Standard Long Buy
                old_qty = pos.get("quantity", 0)
                old_avg = pos.get("avg_price", 0.0)
                new_qty = old_qty + quantity
                new_avg = ((old_qty * old_avg) + trade_val) / new_qty if new_qty > 0 else price
                pos["position_type"] = "LONG"
                pos["quantity"] = new_qty
                pos["avg_price"] = new_avg
                if "entry_date" not in pos or not pos["entry_date"]:
                    pos["entry_date"] = current_date_str
                state.available_cash -= (trade_val + fee)
                state.holdings[ticker] = pos

        elif action == "SELL":
            # Deliver shares
            old_qty = pos.get("quantity", 0)
            avg_p = pos.get("avg_price", price)
            sell_qty = min(old_qty, quantity)
            # Realized P&L = (Selling Price - Buying Price) * Quantity
            pnl = (price - avg_p) * sell_qty
            state.realized_pnl += pnl
            state.available_cash += (sell_qty * price - fee)

            # Record capital gains tax under IT Act, 1961
            entry_date_str = pos.get("entry_date", current_date_str)
            tax_calculator.record_trade(
                ticker=ticker,
                action="SELL",
                quantity=sell_qty,
                entry_price=avg_p,
                exit_price=price,
                entry_date=entry_date_str,
                exit_date=current_date_str
            )
            
            remaining = old_qty - sell_qty
            if remaining > 0:
                pos["quantity"] = remaining
                state.holdings[ticker] = pos
            else:
                if ticker in state.holdings:
                    del state.holdings[ticker]

        elif action == "SHORT":
            # Initiate short sell: 100% margin locked from cash
            state.available_cash -= (trade_val + fee)
            state.margin_locked += trade_val
            pos["position_type"] = "SHORT"
            pos["quantity"] = pos.get("quantity", 0) + quantity
            pos["avg_price"] = price
            pos["margin_locked"] = state.margin_locked
            pos["entry_date"] = current_date_str
            state.holdings[ticker] = pos

        elif action == "COVER":
            # Buy back borrowed shares
            short_qty = pos.get("quantity", 0)
            avg_p = pos.get("avg_price", price)
            cover_qty = min(short_qty, quantity)
            pnl = (avg_p - price) * cover_qty
            state.realized_pnl += pnl
            margin_release = cover_qty * avg_p
            state.margin_locked = max(0.0, state.margin_locked - margin_release)
            state.available_cash += (margin_release + pnl - fee)

            # Record capital gains tax for covered short
            entry_date_str = pos.get("entry_date", current_date_str)
            tax_calculator.record_trade(
                ticker=ticker,
                action="COVER",
                quantity=cover_qty,
                entry_price=price,
                exit_price=avg_p,
                entry_date=entry_date_str,
                exit_date=current_date_str
            )

            remaining = short_qty - cover_qty
            if remaining > 0:
                pos["quantity"] = remaining
                state.holdings[ticker] = pos
            else:
                if ticker in state.holdings:
                    del state.holdings[ticker]


execution_engine = ExecutionEngine()

