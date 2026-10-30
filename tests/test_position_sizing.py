import pytest
from engine.config import config
from engine.state import state
from engine.strategy import strategy
from engine.risk_manager import risk_manager


@pytest.fixture(autouse=True)
def setup_teardown_state():
    """Reset state to clean baseline before each test."""
    with state.lock:
        state.reset_capital()
        state.market_prices.clear()
        state.holdings.clear()
        state.daily_executed_orders.clear()
        state.price_history.clear()
        config.reload()
    yield
    with state.lock:
        state.reset_capital()
        state.market_prices.clear()
        state.holdings.clear()
        state.daily_executed_orders.clear()


def test_low_and_high_priced_stock_sizing():
    """Verify high- and low-priced stocks receive ~3% target capital allocation with integer shares."""
    with state.lock:
        state.available_cash = 1_000_000.0
        state.peak_wealth = 1_000_000.0

    # 1. High-priced stock: HMDP at ₹2,350.00
    hmdp_price = 2350.00
    qty_hmdp = strategy.calculate_buy_quantity("HMDP", hmdp_price)
    assert isinstance(qty_hmdp, int)
    # Target 3% of 10L = 30,000. 30,000 // 2350 = 12 shares (value = ₹28,200)
    assert qty_hmdp == 12
    trade_val_hmdp = qty_hmdp * hmdp_price
    assert 25000 <= trade_val_hmdp <= 30000

    # 2. Low-priced stock: DSNY at ₹110.27
    dsny_price = 110.27
    qty_dsny = strategy.calculate_buy_quantity("DSNY", dsny_price)
    assert isinstance(qty_dsny, int)
    # Target 3% of 10L = 30,000. 30,000 // 110.27 = 272 shares (value = ₹29,993.44)
    assert qty_dsny == 272
    trade_val_dsny = qty_dsny * dsny_price
    assert 29000 <= trade_val_dsny <= 30000


def test_integer_rounding():
    """Ensure fractional share sizes are strictly floored to integers."""
    with state.lock:
        state.available_cash = 1_000_000.0
        state.peak_wealth = 1_000_000.0

    price = 333.33  # 30,000 / 333.33 = 90.0009
    qty = strategy.calculate_buy_quantity("TEST", price)
    assert isinstance(qty, int)
    assert qty == 90
    assert (qty * price) <= (1_000_000.0 * config.TARGET_ALLOCATION_PCT)


def test_invalid_and_stale_prices():
    """Invalid, negative, zero, non-numeric, boolean, and non-finite prices must return 0 without error."""
    assert strategy.calculate_buy_quantity("TEST", 0.0) == 0
    assert strategy.calculate_buy_quantity("TEST", -150.0) == 0
    assert strategy.calculate_buy_quantity("TEST", None) == 0
    assert strategy.calculate_buy_quantity("TEST", "invalid") == 0
    assert strategy.calculate_buy_quantity("TEST", float("nan")) == 0
    # Explicit regression tests for booleans and infinities
    assert strategy.calculate_buy_quantity("TEST", True) == 0
    assert strategy.calculate_buy_quantity("TEST", False) == 0
    assert strategy.calculate_buy_quantity("TEST", float("inf")) == 0
    assert strategy.calculate_buy_quantity("TEST", float("-inf")) == 0


def test_insufficient_cash_preserves_reserve():
    """When cash is near the 20% minimum buffer, sizing scales down to protect the cash reserve."""
    with state.lock:
        # Total wealth = 1,000,000. Reserve = 200,000.
        # Set available cash = 210,000 (headroom = 10,000 - 20 = 9,980)
        state.starting_capital = 1_000_000.0
        state.available_cash = 210_000.0
        state.holdings = {
            "CORE": {"quantity": 790, "avg_price": 1000.0, "position_type": "LONG"}
        }
        state.market_prices["CORE"] = {"close": 1000.0}

    price = 1000.0
    # Headroom = 210,000 - 200,000 - 20 = 9,980.
    # 9,980 // 1000 = 9 shares
    qty = strategy.calculate_buy_quantity("INCR", price)
    assert qty == 9
    total_cost = (qty * price) + config.BROKERAGE_PER_ORDER
    remaining_cash = 210_000.0 - total_cost
    assert remaining_cash >= (1_000_000.0 * 0.20)  # Preserves at least 200,000 cash


def test_cash_reserve_exhaustion_skips_trade():
    """When available cash is already at or below the 20% reserve + fee, sizing returns 0."""
    with state.lock:
        state.starting_capital = 1_000_000.0
        state.available_cash = 200_000.0  # Exactly at 20% floor
        state.holdings = {
            "CORE": {"quantity": 800, "avg_price": 1000.0, "position_type": "LONG"}
        }
        state.market_prices["CORE"] = {"close": 1000.0}

    qty = strategy.calculate_buy_quantity("NEW", 500.0)
    assert qty == 0


def test_concentration_cap_with_existing_holdings():
    """Concentration cap must include existing holdings and limit additional purchases to remaining headroom."""
    with state.lock:
        # Total wealth = 1,000,000. Max allocation 25% = 250,000.
        # Existing holding of TIKR is 230 shares @ 1,000 = 230,000 (23%).
        # Headroom = 250,000 - 230,000 = 20,000 (< 30,000 target).
        state.starting_capital = 1_000_000.0
        state.available_cash = 770_000.0
        state.holdings = {
            "TIKR": {"quantity": 230, "avg_price": 1000.0, "position_type": "LONG"}
        }
        state.market_prices["TIKR"] = {"close": 1000.0}

    price = 1000.0
    qty = strategy.calculate_buy_quantity("TIKR", price)
    # Headroom is 20,000, price is 1000 -> qty should be 20 shares (not 30)
    assert qty == 20
    new_total_val = (230 + qty) * price
    assert new_total_val <= (1_000_000.0 * config.MAX_STOCK_CONCENTRATION_PCT)


def test_concentration_cap_at_or_above_limit():
    """If stock is already at or above 25% concentration cap, sizing returns 0."""
    with state.lock:
        state.starting_capital = 1_000_000.0
        state.available_cash = 750_000.0
        state.holdings = {
            "TIKR": {"quantity": 250, "avg_price": 1000.0, "position_type": "LONG"}
        }
        state.market_prices["TIKR"] = {"close": 1000.0}

    qty = strategy.calculate_buy_quantity("TIKR", 1000.0)
    assert qty == 0


def test_fee_accounting_in_headroom():
    """Ensure flat ₹20 brokerage is deducted from cash headroom before sizing."""
    with state.lock:
        # Cash = 205,020. Reserve = 200,000.
        # Headroom = 5,020 - 20 (fee) = 5,000.
        state.starting_capital = 1_000_000.0
        state.available_cash = 205_020.0
        state.holdings = {
            "CORE": {"quantity": 794, "avg_price": 1000.0, "position_type": "LONG"},
        }
        state.market_prices["CORE"] = {"close": 1000.0}

    price = 1000.0
    # Headroom = 5,000 // 1000 = 5 shares (value = 5,000). Total required = 5,020.
    # Remaining cash = 205,020 - 5,020 = 200,000 (exactly at 20% reserve).
    qty = strategy.calculate_buy_quantity("EXTRA", price)
    assert qty == 5


def test_minimum_trade_value_threshold():
    """Trades resulting in total value below MIN_TRADE_VALUE (₹5,000) are skipped to avoid fee erosion."""
    with state.lock:
        # Cash = 203,000. Reserve = 200,000.
        # Headroom = 3,000 - 20 = 2,980.
        # 2,980 is below MIN_TRADE_VALUE of 5,000 -> must return 0.
        state.starting_capital = 1_000_000.0
        state.available_cash = 203_000.0
        state.holdings = {
            "CORE": {"quantity": 797, "avg_price": 1000.0, "position_type": "LONG"}
        }
        state.market_prices["CORE"] = {"close": 1000.0}

    qty = strategy.calculate_buy_quantity("TINY", 500.0)
    assert qty == 0


def test_risk_manager_accepts_sized_order():
    """Confirm orders produced by calculate_buy_quantity pass risk_manager.validate_order cleanly."""
    with state.lock:
        state.starting_capital = 1_000_000.0
        state.available_cash = 1_000_000.0

    ticker = "HAVN"
    price = 450.0
    qty = strategy.calculate_buy_quantity(ticker, price)
    assert qty > 0

    is_valid, reason = risk_manager.validate_order(ticker, "BUY", qty, price)
    assert is_valid is True
    assert reason is None

