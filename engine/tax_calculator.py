"""
Indian Capital Gains Tax Calculator (Income-tax Act, 1961)
Implements statutory compliance and tax-loss harvesting for MANTHAN 2026:
- Section 111A: Short-Term Capital Gains (STCG) at 15% (holding period <= 365 days)
- Section 112A: Long-Term Capital Gains (LTCG) at 10% on gains exceeding ₹1,00,000 exemption
- Sections 70 & 71: Inter-head and intra-head capital loss set-offs:
    * Short-term capital losses (STCL) offset STCG first, then remaining offsets LTCG.
    * Long-term capital losses (LTCL) offset LTCG only.
    * Realized net losses generate tax credits against current or future liabilities.
"""

import math
from datetime import datetime
from typing import Dict, Any, Optional, List


class IndianTaxCalculator:
    """
    Computes cumulative capital gains tax, exemptions, and loss offset credits.
    """

    def __init__(self):
        self.stcg_rate = 0.15  # 15% under Section 111A
        self.ltcg_rate = 0.10  # 10% under Section 112A
        self.ltcg_exemption_limit = 100000.0  # ₹1,00,000 under Section 112A

        # Cumulative realized gains and losses
        self.gross_stcg_gain: float = 0.0
        self.gross_stcg_loss: float = 0.0
        self.gross_ltcg_gain: float = 0.0
        self.gross_ltcg_loss: float = 0.0

        # Trade closed history log for tax audit
        self.closed_trades: List[Dict[str, Any]] = []

    def reset(self):
        """Resets all tax accumulators."""
        self.gross_stcg_gain = 0.0
        self.gross_stcg_loss = 0.0
        self.gross_ltcg_gain = 0.0
        self.gross_ltcg_loss = 0.0
        self.closed_trades.clear()

    @staticmethod
    def calculate_holding_days(entry_date_str: str, exit_date_str: str) -> int:
        """Calculates elapsed calendar days between entry and exit."""
        if not entry_date_str or not exit_date_str:
            return 1  # Default to short term if dates missing
        try:
            d1 = datetime.strptime(str(entry_date_str)[:10], "%Y-%m-%d")
            d2 = datetime.strptime(str(exit_date_str)[:10], "%Y-%m-%d")
            return max(0, (d2 - d1).days)
        except Exception:
            return 1

    def record_trade(
        self,
        ticker: str,
        action: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        entry_date: str,
        exit_date: str,
    ) -> Dict[str, Any]:
        """
        Records a closed trade, classifies it as STCG or LTCG, and updates tax ledgers.
        """
        holding_days = self.calculate_holding_days(entry_date, exit_date)
        is_long_term = holding_days > 365

        # P&L calculation: (exit - entry) * qty for long sales
        pnl = (exit_price - entry_price) * quantity

        if is_long_term:
            if pnl >= 0:
                self.gross_ltcg_gain += pnl
            else:
                self.gross_ltcg_loss += abs(pnl)
            gain_type = "LTCG"
        else:
            if pnl >= 0:
                self.gross_stcg_gain += pnl
            else:
                self.gross_stcg_loss += abs(pnl)
            gain_type = "STCG"

        trade_record = {
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "holding_days": holding_days,
            "gain_type": gain_type,
            "entry_date": entry_date,
            "exit_date": exit_date,
        }
        self.closed_trades.append(trade_record)
        return trade_record

    def compute_tax_report(self) -> Dict[str, Any]:
        """
        Applies Sections 70, 71, 111A, and 112A rules to produce comprehensive tax liability.
        """
        # Step 1: Intra-head set off for STCG (Section 70)
        net_stcg = self.gross_stcg_gain - self.gross_stcg_loss

        # Step 2: Intra-head set off for LTCG (Section 70)
        net_ltcg = self.gross_ltcg_gain - self.gross_ltcg_loss

        stcl_carried = 0.0
        ltcl_carried = 0.0
        stcl_offset_against_ltcg = 0.0

        # Step 3: Inter-head set off (Section 71)
        # If STCL exists (net_stcg < 0), it can offset positive LTCG
        if net_stcg < 0:
            excess_stcl = abs(net_stcg)
            if net_ltcg > 0:
                stcl_offset_against_ltcg = min(excess_stcl, net_ltcg)
                net_ltcg -= stcl_offset_against_ltcg
                excess_stcl -= stcl_offset_against_ltcg
            stcl_carried = excess_stcl
            taxable_stcg = 0.0
        else:
            taxable_stcg = net_stcg

        # LTCL cannot offset STCG under Section 70/71 (only LTCG)
        if net_ltcg < 0:
            ltcl_carried = abs(net_ltcg)
            taxable_ltcg = 0.0
        else:
            taxable_ltcg = net_ltcg

        # Step 4: Apply Section 112A ₹1,00,000 exemption for LTCG
        ltcg_exemption_used = min(taxable_ltcg, self.ltcg_exemption_limit)
        taxable_ltcg_after_exemption = max(0.0, taxable_ltcg - ltcg_exemption_used)

        # Step 5: Compute final tax liabilities
        stcg_tax = taxable_stcg * self.stcg_rate
        ltcg_tax = taxable_ltcg_after_exemption * self.ltcg_rate
        total_tax_liability = stcg_tax + ltcg_tax

        # Total tax loss credits (accumulated losses available to shield gains)
        total_tax_loss_credits = (stcl_carried * self.stcg_rate) + (ltcl_carried * self.ltcg_rate)

        return {
            "gross_stcg_gain": round(self.gross_stcg_gain, 2),
            "gross_stcg_loss": round(self.gross_stcg_loss, 2),
            "gross_ltcg_gain": round(self.gross_ltcg_gain, 2),
            "gross_ltcg_loss": round(self.gross_ltcg_loss, 2),
            "taxable_stcg": round(taxable_stcg, 2),
            "stcg_tax": round(stcg_tax, 2),
            "taxable_ltcg_before_exemption": round(taxable_ltcg, 2),
            "ltcg_exemption_used": round(ltcg_exemption_used, 2),
            "taxable_ltcg_after_exemption": round(taxable_ltcg_after_exemption, 2),
            "ltcg_tax": round(ltcg_tax, 2),
            "total_tax_liability": round(total_tax_liability, 2),
            "tax_loss_credit_harvested": round(stcl_offset_against_ltcg * self.ltcg_rate, 2),
            "carried_loss_shield": round(stcl_carried + ltcl_carried, 2),
            "total_trades_processed": len(self.closed_trades),
        }


# Global singleton tax calculator
tax_calculator = IndianTaxCalculator()

