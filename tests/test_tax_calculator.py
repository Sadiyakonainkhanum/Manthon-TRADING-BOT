import pytest
from engine.tax_calculator import IndianTaxCalculator


def test_stcg_calculation_positive():
    calc = IndianTaxCalculator()
    # Buy on 2025-01-01, sell on 2025-02-01 (31 days <= 365 days -> STCG)
    trade = calc.record_trade(
        ticker="ALPHACORP",
        action="SELL",
        quantity=100,
        entry_price=100.0,
        exit_price=150.0,
        entry_date="2025-01-01",
        exit_date="2025-02-01",
    )
    assert trade["gain_type"] == "STCG"
    assert trade["pnl"] == 5000.0
    report = calc.compute_tax_report()
    assert report["gross_stcg_gain"] == 5000.0
    assert report["taxable_stcg"] == 5000.0
    # 15% on ₹5,000 = ₹750
    assert report["stcg_tax"] == 750.0
    assert report["total_tax_liability"] == 750.0


def test_ltcg_exemption_under_section_112a():
    calc = IndianTaxCalculator()
    # Holding period 400 days (> 365 days -> LTCG)
    # Gain = ₹80,000 (below ₹1,00,000 exemption limit)
    calc.record_trade(
        ticker="BETATECH",
        action="SELL",
        quantity=100,
        entry_price=1000.0,
        exit_price=1800.0,
        entry_date="2024-01-01",
        exit_date="2025-02-04",
    )
    report = calc.compute_tax_report()
    assert report["gross_ltcg_gain"] == 80000.0
    assert report["ltcg_exemption_used"] == 80000.0
    assert report["taxable_ltcg_after_exemption"] == 0.0
    assert report["ltcg_tax"] == 0.0
    assert report["total_tax_liability"] == 0.0

    # Additional gain exceeding ₹1,00,000 total exemption limit
    calc.record_trade(
        ticker="GAMMAPHARMA",
        action="SELL",
        quantity=100,
        entry_price=1000.0,
        exit_price=1500.0,
        entry_date="2024-01-01",
        exit_date="2025-02-04",
    )
    report2 = calc.compute_tax_report()
    # Total LTCG = ₹80,000 + ₹50,000 = ₹1,30,000
    assert report2["gross_ltcg_gain"] == 130000.0
    assert report2["ltcg_exemption_used"] == 100000.0
    assert report2["taxable_ltcg_after_exemption"] == 30000.0
    # 10% on ₹30,000 = ₹3,000
    assert report2["ltcg_tax"] == 3000.0
    assert report2["total_tax_liability"] == 3000.0


def test_section_70_and_71_loss_offsets_and_credits():
    calc = IndianTaxCalculator()
    # Short term loss: ₹20,000
    calc.record_trade(
        ticker="LOSER",
        action="SELL",
        quantity=100,
        entry_price=500.0,
        exit_price=300.0,
        entry_date="2025-01-01",
        exit_date="2025-01-15",
    )
    # Short term gain: ₹15,000
    calc.record_trade(
        ticker="WINNER",
        action="SELL",
        quantity=100,
        entry_price=200.0,
        exit_price=350.0,
        entry_date="2025-01-01",
        exit_date="2025-01-20",
    )
    # Net STCG = -₹5,000 (Loss)
    report = calc.compute_tax_report()
    assert report["taxable_stcg"] == 0.0
    assert report["stcg_tax"] == 0.0
    assert report["carried_loss_shield"] == 5000.0

    # Now add LTCG of ₹120,000 (held > 365 days)
    calc.record_trade(
        ticker="LONGWINNER",
        action="SELL",
        quantity=100,
        entry_price=1000.0,
        exit_price=2200.0,
        entry_date="2023-01-01",
        exit_date="2025-01-25",
    )
    report2 = calc.compute_tax_report()
    # Excess STCL (₹5,000) offsets LTCG before Section 112A exemption:
    # LTCG = ₹120,000 - ₹5,000 = ₹115,000
    # Exemption used = ₹100,000 -> Taxable LTCG = ₹15,000
    # LTCG tax = 10% of ₹15,000 = ₹1,500
    assert report2["taxable_ltcg_after_exemption"] == 15000.0
    assert report2["ltcg_tax"] == 1500.0
    assert report2["total_tax_liability"] == 1500.0

