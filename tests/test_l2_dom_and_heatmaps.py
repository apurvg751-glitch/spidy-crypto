import pytest
from market_data.models import Candle, ConfirmationsResult
from market_data.l2_book import OrderBookEngine, OrderBookAnalysis
from market_data.derivatives_intel import DerivativesIntelEngine, DerivativesIntel
from strategy.setup_grading import SetupGradingEngine, SetupGradeResult
from structure.equilibrium import EquilibriumEngine, DealingRange




def test_order_book_parsing_and_imbalance():
    """Verifies that OrderBookEngine calculates depth, imbalance ratio, and liquidity walls accurately."""
    # Synthetic Order Book: heavy bids (buy pressure) and a major bid wall at 79000
    raw_buys = [
        {"price": "79400.0", "size": "500", "depth": "500"},
        {"price": "79350.0", "size": "600", "depth": "1100"},
        {"price": "79300.0", "size": "450", "depth": "1550"},
        {"price": "79000.0", "size": "4500", "depth": "6050"},  # Major Institutional Bid Wall!
    ]
    raw_sells = [
        {"price": "79401.0", "size": "200", "depth": "200"},
        {"price": "79450.0", "size": "250", "depth": "450"},
        {"price": "79500.0", "size": "300", "depth": "750"},
        {"price": "79800.0", "size": "350", "depth": "1100"},
    ]

    analysis = OrderBookEngine.parse_orderbook("BTCUSD", raw_buys, raw_sells, depth_levels=4)

    assert analysis.symbol == "BTCUSD"
    assert analysis.best_bid == 79400.0
    assert analysis.best_ask == 79401.0
    assert analysis.spread == 1.0
    assert analysis.total_bid_depth_top20 == 6050.0
    assert analysis.total_ask_depth_top20 == 1100.0
    assert analysis.imbalance_ratio_top20 == 5.5  # 6050 / 1100
    assert analysis.imbalance_bias == "BULLISH_IMBALANCE"

    # Wall check
    assert analysis.nearest_bid_wall is not None
    assert analysis.nearest_bid_wall.price == 79000.0
    assert analysis.nearest_bid_wall.side == "BID"
    assert analysis.nearest_bid_wall.is_major is True


def test_liquidation_clusters_calculation():
    """Verifies calculation of 25x/50x/100x retail liquidation clusters."""
    current_p = 80000.0
    swing_h = 80500.0
    swing_l = 79500.0

    clusters = DerivativesIntelEngine.calculate_liquidation_clusters(current_p, swing_h, swing_l)

    assert len(clusters) == 6  # 3 short liquidations above, 3 long liquidations below

    short_liqs = [c for c in clusters if c.side == "SHORT_LIQUIDATION"]
    long_liqs = [c for c in clusters if c.side == "LONG_LIQUIDATION"]

    assert len(short_liqs) == 3
    assert len(long_liqs) == 3

    # 100x short liq should be closest above swing high
    liq_100x = [c for c in short_liqs if c.leverage == 100][0]
    assert liq_100x.estimated_price > swing_h
    assert liq_100x.distance_pct > 0.0

    # 100x long liq should be closest below swing low
    liq_long_100x = [c for c in long_liqs if c.leverage == 100][0]
    assert liq_long_100x.estimated_price < swing_l
    assert liq_long_100x.distance_pct < 0.0


def test_grading_with_dom_and_derivatives_boost():
    """Verifies that DOM imbalance and squeeze sentiment boost the institutional setup grade."""
    # Create synthetic orderbook with bullish imbalance
    dom = OrderBookAnalysis(
        symbol="BTCUSD",
        timestamp=1700000000,
        best_bid=79400.0,
        best_ask=79401.0,
        spread=1.0,
        spread_bps=0.12,
        total_bid_depth_top20=5000.0,
        total_ask_depth_top20=2500.0,
        imbalance_ratio_top20=2.0,
        imbalance_bias="BULLISH_IMBALANCE"
    )

    # Create synthetic derivatives intel with short squeeze priming (negative funding)
    derivatives = DerivativesIntel(
        symbol="BTCUSD",
        timestamp=1700000000,
        funding_rate=-0.015,
        predicted_funding_rate=-0.018,
        annualized_funding_pct=-16.42,
        sentiment="EXTREME_SHORT_CROWDED",
        squeeze_potential="SHORT_SQUEEZE_PRIME"
    )

    candles_1h = [
        Candle(time=1700000000 + i*3600, open=78000.0, high=81000.0, low=78000.0, close=79000.0, volume=1000.0)
        for i in range(20)
    ]
    dealing_range = EquilibriumEngine.calculate_range(candles_1h)

    # Base score of 78 (normally B+). With +5 DOM and +5 Squeeze boost -> 88 (promoted to A+!)
    confirms = ConfirmationsResult(passed_count=5, is_qualified=True)
    res = SetupGradingEngine.grade_setup(
        direction="LONG",
        current_price=79000.0,  # in Discount zone
        setup_score=78,
        confirmations=confirms,
        mtf_context=None,
        dealing_range=dealing_range,
        displacement=None,
        orderbook=dom,
        derivatives=derivatives
    )

    assert res.score == 88
    assert res.dom_confluence is True
    assert res.liquidation_confluence is True
    assert res.grade == "A+"
    assert res.is_tradeable is True


