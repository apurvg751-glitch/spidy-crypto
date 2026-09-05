import pytest
import time
from market_data.news_filter import EconomicNewsFilter
from market_data.funding_screener import FundingRateScreener
from indicators.order_flow import OrderFlowEngine


def test_economic_news_filter_blocks_during_event_window():
    filter_engine = EconomicNewsFilter(buffer_minutes=30)
    now = int(time.time())

    # Register US CPI in 15 minutes
    filter_engine.register_event("US CPI Inflation Data", now + (15 * 60), impact="HIGH")

    # Current time should be blocked!
    blocked, reason = filter_engine.is_in_high_impact_window(now)
    assert blocked is True
    assert "US CPI" in reason

    # 45 minutes before event should be safe
    blocked_safe, reason_safe = filter_engine.is_in_high_impact_window(now - (30 * 60))
    assert blocked_safe is False


def test_funding_rate_screener_classifies_conditions():
    # Extreme positive (+0.10% per 8h)
    ext_pos = FundingRateScreener.analyze_funding("BTCUSD", raw_8h_rate=0.0010)
    assert ext_pos["status"] == "EXTREME_POSITIVE"
    assert ext_pos["recommendation"] == "FAVOR_SHORTS"

    # Extreme negative (-0.08% per 8h)
    ext_neg = FundingRateScreener.analyze_funding("ETHUSD", raw_8h_rate=-0.0008)
    assert ext_neg["status"] == "EXTREME_NEGATIVE"
    assert ext_neg["recommendation"] == "FAVOR_LONGS"

    # Balanced normal funding (+0.01% per 8h)
    norm = FundingRateScreener.analyze_funding("SOLUSD", raw_8h_rate=0.0001)
    assert norm["status"] == "BALANCED"


def test_order_flow_cvd_divergence():
    # Price dropping: [100.0, 99.0, 98.0, 97.0]
    prices = [100.0, 99.0, 98.0, 97.0]
    # CVD rising (buyers absorbing selling): [50.0, 80.0, 110.0, 150.0]
    cvd = [50.0, 80.0, 110.0, 150.0]

    div_found, div_type = OrderFlowEngine.detect_cvd_divergence(prices, cvd)
    assert div_found is True
    assert div_type == "BULLISH_CVD_ABSORPTION"

    # Synchronized move (no divergence)
    prices_sync = [100.0, 101.0, 102.0, 103.0]
    cvd_sync = [50.0, 70.0, 90.0, 110.0]
    div_found_sync, _ = OrderFlowEngine.detect_cvd_divergence(prices_sync, cvd_sync)
    assert div_found_sync is False
