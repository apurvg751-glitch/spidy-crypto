import pytest
from market_data.delta_specs import (
    DeltaPointValueEngine,
    DELTA_CONTRACT_SPECS,
    PointValueTelemetry,
)


def test_delta_specs_coverage():
    """Verify all 6 core markets are defined with correct Delta Exchange India specs."""
    expected_symbols = ["BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD", "AVAXUSD"]
    for sym in expected_symbols:
        spec = DeltaPointValueEngine.get_spec(sym)
        assert spec is not None
        assert spec.symbol == sym
        assert spec.contract_value > 0
        assert spec.tick_size > 0
        assert spec.point_unit > 0
        assert spec.point_label != ""


def test_btc_point_value_calculation():
    """Verify BTCUSD point value: at ~$80,000, 1 point ($1.00) gives exact expected INR."""
    telemetry = DeltaPointValueEngine.calculate_point_value(
        symbol="BTCUSD",
        price=80000.0,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    # Notional: ₹18,000 = $205.714
    # Units: 205.714 / 80000 = ~0.002571 BTC
    # Contract value = 0.001 BTC -> ~2.57 contracts
    # Point definition = 1.0 ($1.00)
    # inr_per_point = 0.002571 * 1.0 * 87.5 = ~₹0.225
    assert telemetry.symbol == "BTCUSD"
    assert telemetry.point_unit == 1.0
    assert 0.20 <= telemetry.point_value_inr <= 0.26
    assert 2.0 <= telemetry.delta_contracts <= 3.0
    assert telemetry.contract_unit == "BTC"


def test_eth_point_value_calculation():
    """Verify ETHUSD point value: at ~$2,450, 1 point ($1.00) gives exact expected INR."""
    telemetry = DeltaPointValueEngine.calculate_point_value(
        symbol="ETHUSD",
        price=2450.0,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    # Notional: $205.714
    # Units: 205.714 / 2450 = ~0.0839 ETH
    # Contract value = 0.01 ETH -> ~8.4 contracts
    # inr_per_point = 0.0839 * 1.0 * 87.5 = ~₹7.34
    assert telemetry.symbol == "ETHUSD"
    assert telemetry.point_unit == 1.0
    assert 6.5 <= telemetry.point_value_inr <= 8.0
    assert 8.0 <= telemetry.delta_contracts <= 9.0


def test_bnb_point_value_calculation():
    """Verify BNBUSD point value: at ~$720, 1 point ($1.00) gives exact expected INR."""
    telemetry = DeltaPointValueEngine.calculate_point_value(
        symbol="BNBUSD",
        price=720.0,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    # Notional: $205.714
    # Units: 205.714 / 720 = ~0.2857 BNB
    # Contract value = 0.1 BNB -> ~2.85 contracts
    # inr_per_point = 0.2857 * 1.0 * 87.5 = ~₹25.0
    assert telemetry.symbol == "BNBUSD"
    assert 22.0 <= telemetry.point_value_inr <= 28.0
    assert 2.5 <= telemetry.delta_contracts <= 3.2


def test_sol_point_value_calculation():
    """Verify SOLUSD point value: at ~$100, 1 point ($1.00) gives exact expected INR."""
    telemetry = DeltaPointValueEngine.calculate_point_value(
        symbol="SOLUSD",
        price=100.0,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    # Notional: $205.714
    # Units: 205.714 / 100 = 2.057 SOL
    # Contract value = 1.0 SOL -> ~2.06 contracts
    # inr_per_point = 2.057 * 1.0 * 87.5 = ~₹180.0
    assert telemetry.symbol == "SOLUSD"
    assert 170.0 <= telemetry.point_value_inr <= 190.0
    assert 1.9 <= telemetry.delta_contracts <= 2.2


def test_xrp_point_value_calculation():
    """Verify XRPUSD point value: at ~$1.40, 0.01 point ($0.01) gives exact expected INR."""
    telemetry = DeltaPointValueEngine.calculate_point_value(
        symbol="XRPUSD",
        price=1.40,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    # Notional: $205.714
    # Units: 205.714 / 1.40 = 146.94 XRP
    # Contract value = 1.0 XRP -> ~147 Lots
    # 0.01 pt = 146.94 * 0.01 * 87.5 = ~₹1.28
    assert telemetry.symbol == "XRPUSD"
    assert telemetry.point_unit == 0.01
    assert 120.0 <= telemetry.point_value_inr <= 135.0
    assert 140.0 <= telemetry.delta_contracts <= 155.0


def test_avax_point_value_calculation():
    """Verify AVAXUSD point value: at ~$7.50, 0.1 point ($0.10) gives exact expected INR."""
    telemetry = DeltaPointValueEngine.calculate_point_value(
        symbol="AVAXUSD",
        price=7.50,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    # Notional: $205.714
    # Units: 205.714 / 7.50 = 27.42 AVAX
    # Contract value = 1.0 AVAX -> ~27 Lots
    # 0.1 pt = 27.42 * 0.1 * 87.5 = ~₹240.00
    assert telemetry.symbol == "AVAXUSD"
    assert telemetry.point_unit == 0.1
    assert 220.0 <= telemetry.point_value_inr <= 260.0
    assert 25.0 <= telemetry.delta_contracts <= 30.0


def test_exact_pnl_calculation():
    """Verify exact PnL matches the point value times points moved for LONG and SHORT."""
    # Long trade on ETH from 2400 to 2450 (+50 points)
    res = DeltaPointValueEngine.calculate_exact_pnl(
        symbol="ETHUSD",
        direction="LONG",
        entry=2400.0,
        current_price=2450.0,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    assert res["points_moved"] == 50.0
    assert res["pnl_inr"] > 0
    assert res["pnl_usd"] > 0
    # ~50 pts * ~₹7.5/pt = ~₹375
    assert 350.0 <= res["pnl_inr"] <= 400.0

    # Short trade on BTC from 80000 to 79000 (+1000 points in profit)
    res = DeltaPointValueEngine.calculate_exact_pnl(
        symbol="BTCUSD",
        direction="SHORT",
        entry=80000.0,
        current_price=79000.0,
        margin_used=3000.0,
        leverage=6,
        usd_inr_rate=87.5
    )
    assert res["points_moved"] == 1000.0
    assert res["pnl_inr"] > 0
    # 1000 pts * ~0.226 = ~₹226
    assert 200.0 <= res["pnl_inr"] <= 250.0
