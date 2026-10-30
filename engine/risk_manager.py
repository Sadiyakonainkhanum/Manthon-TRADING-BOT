import time
from typing import Dict, Any, Tuple, Optional, List
from engine.config import config
from engine.state import state

List_orders = List[Dict[str, Any]]


class RiskManager:
    """Enforces strict portfolio guardrails, capital preservation, and Indian exchange rules."""

    def __init__(self):
        self.stop_loss_pct = config.STOP_LOSS_PCT          # 3.5%
        self.take_profit_pct = config.TAKE_PROFIT_PCT      # 5.0%
        self.min_cash_buffer_pct = config.MIN_CASH_BUFFER_PCT  # 20.0%
        self.max_stock_allocation_pct = config.MAX_STOCK_CONCENTRATION_PCT  # 25.0%

    def validate_order(self, ticker: str, action: str, quantity: int, current_price: float) -> Tuple[bool, Optional[str]]:
        """
        Performs rigorous pre-trade risk checks before order submission.
        Returns: (is_valid, rejection_reason)
        """
        if state.emergency_stop:
            return False, "EMERGENCY_STOP_ACTIVE: Trading halted by user"

        if quantity <= 0:
            return False, "INVALID_QUANTITY: Must be positive integer"

        trade_value = quantity * current_price
        brokerage = config.BROKERAGE_PER_ORDER
        total_required = trade_value + brokerage

        metrics = state.compute_wealth_metrics()
        available_cash = metrics["available_cash"]
        total_wealth = metrics["total_wealth"]

        # Minimum cash reserve requirement
        min_reserve = total_wealth * self.min_cash_buffer_pct

        if action == "BUY":
            # Cash balance check
            if available_cash < total_required:
                return False, f"INSUFFICIENT_CAPITAL: Need ₹{total_required:,.2f}, have ₹{available_cash:,.2f}"

            # Cash cushion protection
            if (available_cash - total_required) < (min_reserve * 0.75):
                return False, f"RISK_VIOLATION: Order violates min cash cushion (reserve threshold ₹{min_reserve:,.2f})"

            # Concentration limit
            existing_pos = state.holdings.get(ticker, {})
            existing_val = existing_pos.get("quantity", 0) * current_price if existing_pos.get("position_type") == "LONG" else 0.0
            new_val = existing_val + trade_value
            if (new_val / total_wealth) > self.max_stock_allocation_pct:
                return False, f"CONCENTRATION_LIMIT: Exceeds max allocation of {self.max_stock_allocation_pct*100}% per stock"

        elif action == "SHORT":
            # Short sell requires 100% margin collateral + brokerage
            if available_cash < total_required:
                return False, f"INSUFFICIENT_MARGIN: Shorting requires 100% margin (₹{total_required:,.2f})"

            # Margin reserve check
            if (available_cash - total_required) < (min_reserve * 0.5):
                return False, "RISK_VIOLATION: Margin lock would breach safety cash floor"

        elif action == "SELL":
            existing_pos = state.holdings.get(ticker, {})
            if existing_pos.get("position_type") != "LONG" or existing_pos.get("quantity", 0) < quantity:
                return False, f"INSUFFICIENT_HOLDINGS: Own {existing_pos.get('quantity', 0)} shares, attempted to sell {quantity}"

        elif action == "COVER":
            existing_pos = state.holdings.get(ticker, {})
            if existing_pos.get("position_type") != "SHORT" or existing_pos.get("quantity", 0) < quantity:
                return False, "NO_SHORT_POSITION: Cannot cover without active short position"

        return True, None

    def check_stop_losses(self) -> List_orders:
        """
        Scans all open positions and triggers immediate stop-loss exits
        if an asset falls >= stop_loss_pct below entry price.
        """
        orders_to_trigger = []
        with state.lock:
            for ticker, pos in list(state.holdings.items()):
                qty = pos.get("quantity", 0)
                if qty <= 0:
                    continue

                avg_price = pos.get("avg_price", 0.0)
                if not isinstance(avg_price, (int, float)) or avg_price <= 0:
                    continue

                price_entry = state.market_prices.get(ticker) or {}
                raw_curr = price_entry.get("close")
                if raw_curr is not None and isinstance(raw_curr, (int, float)) and raw_curr > 0:
                    curr_price = float(raw_curr)
                else:
                    curr_price = float(avg_price)

                pos_type = pos.get("position_type", "LONG")

                if pos_type == "LONG":
                    loss_pct = (avg_price - curr_price) / avg_price
                    if loss_pct >= self.stop_loss_pct:
                        orders_to_trigger.append({
                            "ticker": ticker,
                            "action": "SELL",
                            "quantity": qty,
                            "reason": f"STOP_LOSS: Down {loss_pct*100:.2f}% (Limit: {self.stop_loss_pct*100}%)"
                        })
                elif pos_type == "SHORT":
                    loss_pct = (curr_price - avg_price) / avg_price
                    if loss_pct >= self.stop_loss_pct:
                        orders_to_trigger.append({
                            "ticker": ticker,
                            "action": "COVER",
                            "quantity": qty,
                            "reason": f"STOP_LOSS_SHORT: Adverse move {loss_pct*100:.2f}% (Limit: {self.stop_loss_pct*100}%)"
                        })

        return orders_to_trigger

    def check_take_profits(self) -> List_orders:
        """
        Scans all open positions and triggers immediate profit-taking exits
        if an asset rises >= take_profit_pct above entry price.
        """
        orders_to_trigger = []
        with state.lock:
            for ticker, pos in list(state.holdings.items()):
                qty = pos.get("quantity", 0)
                if qty <= 0:
                    continue

                avg_price = pos.get("avg_price", 0.0)
                if not isinstance(avg_price, (int, float)) or avg_price <= 0:
                    continue

                price_entry = state.market_prices.get(ticker) or {}
                raw_curr = price_entry.get("close")
                if raw_curr is not None and isinstance(raw_curr, (int, float)) and raw_curr > 0:
                    curr_price = float(raw_curr)
                else:
                    curr_price = float(avg_price)

                pos_type = pos.get("position_type", "LONG")
                target_tp = self.take_profit_pct
                if not state.is_demo_mode:
                    # In live competition, allow strong trends to ride up to 7.5%
                    # unless RSI indicates overbought exhaustion (>= 70)
                    sig = state.strategy_signals.get(ticker, {})
                    rsi_val = sig.get("rsi")
                    if rsi_val is not None and rsi_val < 70.0:
                        target_tp = max(target_tp, 0.075)

                if pos_type == "LONG":
                    gain_pct = (curr_price - avg_price) / avg_price
                    if gain_pct >= target_tp:
                        orders_to_trigger.append({
                            "ticker": ticker,
                            "action": "SELL",
                            "quantity": qty,
                            "reason": f"TAKE_PROFIT: Up {gain_pct*100:.2f}% (Target: {target_tp*100:.1f}%)"
                        })
                elif pos_type == "SHORT":
                    gain_pct = (avg_price - curr_price) / avg_price
                    if gain_pct >= target_tp:
                        orders_to_trigger.append({
                            "ticker": ticker,
                            "action": "COVER",
                            "quantity": qty,
                            "reason": f"TAKE_PROFIT_SHORT: Profit {gain_pct*100:.2f}% (Target: {target_tp*100:.1f}%)"
                        })

        return orders_to_trigger


List_orders = list[dict[str, Any]]
risk_manager = RiskManager()
