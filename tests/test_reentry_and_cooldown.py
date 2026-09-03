import time
import pytest
from pathlib import Path
from storage.database import Database
from config.settings import settings
from strategy.reentry_manager import ReentryManager
from strategy.models.base_model import StrategyCandidate
from market_data.models import Candle, ConfirmationsResult
from strategy.scoring import SetupScoreBreakdown


def make_candle(t: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> Candle:
    return Candle(time=t, open=o, high=h, low=l, close=c, volume=v, resolution="5m")


def make_candidate(
    coin: str = "BTCUSD",
    model_id: str = "MODEL_1",
    direction: str = "LONG",
    entry: float = 70000.0,
    stop_loss: float = 69500.0,
    target_1: float = 71000.0,
    target_2: float = 71500.0,
    detection_ts: int = 10000,
    sweep_ts: int = 9800,
    bos_ts: int = 9900,
    retest_ts: int = 9950,
    score: int = 85
) -> StrategyCandidate:
    risk = abs(entry - stop_loss)
    reward = abs(target_2 - entry)
    rr = reward / max(risk, 1e-4)

    score_breakdown = SetupScoreBreakdown(
        trend_score=20,
        liquidity_score=25,
        structure_score=20,
        volume_score=15,
        risk_reward_score=10,
        total_score=score,
        atr_value=200.0
    )

    conf = ConfirmationsResult(
        trend_aligned=True,
        macro_aligned=True,
        sweep_ok=True,
        bos_ok=True,
        volume_ok=True,
        vwap_ok=True,
        zone_ok=True,
        passed_count=7,
        rating="HIGH_PROBABILITY"
    )

    gen_id = ReentryManager.generate_setup_id(
        coin=coin,
        model_id=model_id,
        direction=direction,
        sweep_ts=sweep_ts,
        bos_ts=bos_ts,
        retest_ts=retest_ts
    )

    return StrategyCandidate(
        id=f"{coin}_{model_id}_{direction}_{detection_ts}",
        coin=coin,
        model_id=model_id,
        model_name="Liquidity Sweep Reversal",
        direction=direction,
        detection_timestamp=detection_ts,
        entry=entry,
        stop_loss=stop_loss,
        target_1=target_1,
        target_2=target_2,
        rr=rr,
        setup_score=score,
        score_breakdown=score_breakdown,
        confirmations=conf,
        generation_id=gen_id,
        sweep_timestamp=sweep_ts,
        bos_timestamp=bos_ts,
        retest_timestamp=retest_ts
    )


@pytest.fixture
def clean_db(tmp_path):
    db_path = tmp_path / "test_reentry.db"
    return Database(db_path=db_path)


def test_completed_btc_setup_cannot_be_reused(clean_db):
    """Test 1: A completed BTC setup generation cannot be reused."""
    reentry = ReentryManager(db=clean_db)
    cand = make_candidate(coin="BTCUSD", detection_ts=10000, sweep_ts=9800, bos_ts=9900)

    # Register trade close with this candidate
    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand.id,
        result="COMPLETED",
        close_price=71500.0,
        candidate_or_trade=cand.model_dump()
    )

    candles = [make_candle(10000 + i*300, 70000, 70100, 69900, 70050) for i in range(10)]
    ok, reason, _ = reentry.evaluate_candidate(cand, candles, atr=200.0)
    assert ok is False
    assert reason == "OLD_SETUP_ALREADY_CONSUMED"


def test_same_bos_cannot_create_two_trades(clean_db):
    """Test 2: Same BOS timestamp cannot create two trades."""
    reentry = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", bos_ts=9900, sweep_ts=9800, detection_ts=10000)

    # Close trade 1 using BOS 9900
    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    # Candidate 2 has a DIFFERENT sweep (10200) but REUSES old BOS 9900
    cand2 = make_candidate(coin="BTCUSD", bos_ts=9900, sweep_ts=10200, detection_ts=10500)
    candles = [make_candle(10000 + i*300, 70000, 70100, 69900, 70050) for i in range(10)]
    ok, reason, _ = reentry.evaluate_candidate(cand2, candles, atr=200.0)
    assert ok is False
    assert reason == "OLD_SETUP_ALREADY_CONSUMED"


def test_same_sweep_cannot_create_two_trades(clean_db):
    """Test 3: Same sweep timestamp cannot create two trades."""
    reentry = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", sweep_ts=9800, bos_ts=9900, detection_ts=10000)

    # Close trade 1 using Sweep 9800
    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="STOPPED",
        close_price=69500.0,
        candidate_or_trade=cand1.model_dump()
    )

    # Candidate 2 has a NEW BOS (10300) but REUSES old Sweep 9800
    cand2 = make_candidate(coin="BTCUSD", sweep_ts=9800, bos_ts=10300, detection_ts=10500)
    candles = [make_candle(10000 + i*300, 70000, 70100, 69900, 70050) for i in range(10)]
    ok, reason, _ = reentry.evaluate_candidate(cand2, candles, atr=200.0)
    assert ok is False
    assert reason == "OLD_SETUP_ALREADY_CONSUMED"


def test_same_retest_cannot_create_two_trades(clean_db):
    """Test 4: Same retest event timestamp cannot create two trades."""
    reentry = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", sweep_ts=9800, bos_ts=9900, retest_ts=9950, detection_ts=10000)

    # Close trade 1 using Retest 9950
    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    # Candidate 2 has new sweep & new BOS but reuses retest 9950
    cand2 = make_candidate(coin="BTCUSD", sweep_ts=10200, bos_ts=10300, retest_ts=9950, detection_ts=10500)
    candles = [make_candle(10000 + i*300, 70000, 70100, 69900, 70050) for i in range(10)]
    ok, reason, _ = reentry.evaluate_candidate(cand2, candles, atr=200.0)
    assert ok is False
    assert reason == "OLD_SETUP_ALREADY_CONSUMED"


def test_cooldown_blocks_immediate_btc_reentry(clean_db):
    """Test 5: Cooldown blocks immediate BTC re-entry right after trade closes."""
    reentry = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", detection_ts=10000)

    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    # Fresh setup arrives only 1 bar later (cooldown is 4 bars)
    cand2 = make_candidate(coin="BTCUSD", sweep_ts=10100, bos_ts=10200, retest_ts=10250, detection_ts=10300)
    # Only 1 bar passed since close
    closed_bar = (int(time.time()) // 300) * 300
    candles = [make_candle(closed_bar + 300, 70000, 70100, 69900, 70050)]

    ok, reason, _ = reentry.evaluate_candidate(cand2, candles, atr=200.0)
    assert ok is False
    assert "COOLDOWN_ACTIVE" in reason


def test_btc_monitoring_continues_during_cooldown(clean_db):
    """Test 6: BTC monitoring and status reporting continue uninterrupted during cooldown."""
    reentry = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", detection_ts=10000)

    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    status = reentry.get_market_status("BTCUSD")
    assert status["coin"] == "BTCUSD"
    assert status["state"] == "POST_TRADE_COOLDOWN"
    assert status["cooldown_remaining_bars"] == settings.SAME_MARKET_COOLDOWN_BARS
    assert status["trade_eligibility"] == "BLOCKED"
    assert status["previous_setup_status"] == "CONSUMED"


def test_eth_can_qualify_while_btc_in_cooldown(clean_db):
    """Test 7: ETH can still qualify while BTC is cooling down (per-market cooldown)."""
    reentry = ReentryManager(db=clean_db)
    btc_cand = make_candidate(coin="BTCUSD", detection_ts=10000)

    # Put BTC in cooldown
    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=btc_cand.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=btc_cand.model_dump()
    )

    # BTC should be in cooldown
    btc_status = reentry.get_market_status("BTCUSD")
    assert btc_status["state"] == "POST_TRADE_COOLDOWN"
    assert btc_status["trade_eligibility"] == "BLOCKED"

    # ETH has NO cooldown -> completely eligible!
    eth_status = reentry.get_market_status("ETHUSD")
    assert eth_status["state"] == "READY"
    assert eth_status["trade_eligibility"] == "READY"

    eth_cand = make_candidate(coin="ETHUSD", entry=2400.0, stop_loss=2380.0, target_1=2450.0, target_2=2480.0, detection_ts=10200)
    candles_eth = [make_candle(10200, 2400.0, 2410.0, 2390.0, 2405.0) for _ in range(5)]
    ok, reason, _ = reentry.evaluate_candidate(eth_cand, candles_eth, atr=10.0)
    assert ok is True
    assert reason == "QUALIFIED_FRESH_SETUP"


def test_new_btc_trade_possible_after_cooldown_and_fresh_setup(clean_db):
    """Test 8: New BTC trade becomes possible after cooldown expires AND fresh setup forms."""
    reentry = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", detection_ts=10000, sweep_ts=9800, bos_ts=9900)

    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    # Advance 5 bars into the future (past 4-bar cooldown)
    base_bar = (int(time.time()) // 300) * 300
    future_candles = [make_candle(base_bar + (i * 300), 70000, 70100, 69900, 70050) for i in range(1, 8)]

    # Brand new structure formed in the future!
    future_now = int(time.time()) + 2000
    cand2 = make_candidate(
        coin="BTCUSD",
        sweep_ts=future_now + 100,
        bos_ts=future_now + 200,
        retest_ts=future_now + 300,
        detection_ts=future_now + 400
    )

    ok, reason, _ = reentry.evaluate_candidate(cand2, future_candles, atr=200.0)
    assert ok is True
    assert reason == "QUALIFIED_FRESH_SETUP"


def test_cooldown_expiry_alone_not_sufficient(clean_db):
    """Test 9: Cooldown expiry alone is NOT sufficient (if no new structure formed, setup is rejected)."""
    reentry = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", detection_ts=10000, sweep_ts=9800, bos_ts=9900)

    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    # 10 bars pass in time
    base_bar = (int(time.time()) // 300) * 300
    future_candles = [make_candle(base_bar + (i * 300), 70000, 70100, 69900, 70050) for i in range(1, 12)]

    # Candidate uses OLD structure timestamps from before trade closed
    cand_old = make_candidate(
        coin="BTCUSD",
        sweep_ts=9800, # Old sweep
        bos_ts=9900,   # Old BOS
        detection_ts=10000
    )

    ok, reason, _ = reentry.evaluate_candidate(cand_old, future_candles, atr=200.0)
    assert ok is False
    assert reason in ("OLD_SETUP_ALREADY_CONSUMED", "NO_NEW_STRUCTURE")


def test_overextended_btc_move_rejected(clean_db):
    """Test 10: Overextended BTC move (> 2.5x ATR from structure) is rejected with OVEREXTENDED."""
    reentry = ReentryManager(db=clean_db)
    future_now = int(time.time()) + 5000

    # ATR is 100, but price expanded 500 points (5.0x ATR) away from previous swing low
    cand_overextended = make_candidate(
        coin="BTCUSD",
        entry=70600.0, # 600 points above low 70000 -> 6.0x ATR!
        stop_loss=70400.0,
        sweep_ts=future_now + 100,
        bos_ts=future_now + 200,
        retest_ts=future_now + 300,
        detection_ts=future_now + 400
    )

    candles = [
        make_candle(future_now + 100, 70000, 70050, 70000, 70020),
        make_candle(future_now + 200, 70020, 70200, 70010, 70180),
        make_candle(future_now + 300, 70180, 70400, 70150, 70390),
        make_candle(future_now + 400, 70390, 70620, 70380, 70600),
    ]

    ok, reason, ratio = reentry.evaluate_candidate(cand_overextended, candles, atr=100.0)
    assert ok is False
    assert "OVEREXTENDED" in reason
    assert ratio > 2.5


def test_fresh_continuation_setup_can_qualify(clean_db, monkeypatch):
    """Test 11: Fresh continuation setup can qualify during strong trend if enabled."""
    monkeypatch.setattr(settings, "ALLOW_TREND_CONTINUATION_REENTRY", True)
    reentry = ReentryManager(db=clean_db)

    cand1 = make_candidate(coin="BTCUSD", detection_ts=10000)
    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    # During cooldown (1 bar later), but has BRAND NEW BOS formed strictly after trade closed!
    now_ts = int(time.time())
    cand_continuation = make_candidate(
        coin="BTCUSD",
        sweep_ts=now_ts + 10,
        bos_ts=now_ts + 20, # BOS > trade close time!
        retest_ts=now_ts + 30,
        detection_ts=now_ts + 40,
        entry=70100.0
    )

    closed_bar = (now_ts // 300) * 300
    candles = [make_candle(closed_bar + 300, 70050, 70150, 70020, 70100)]

    ok, reason, _ = reentry.evaluate_candidate(cand_continuation, candles, atr=200.0)
    assert ok is True
    assert cand_continuation.is_continuation_setup is True
    assert reason == "QUALIFIED_FRESH_SETUP"


def test_restart_preserves_consumed_setups_and_cooldown(clean_db):
    """Test 12: Restarting the database / manager preserves consumed setup IDs and cooldown state."""
    reentry1 = ReentryManager(db=clean_db)
    cand1 = make_candidate(coin="BTCUSD", detection_ts=10000, sweep_ts=9800, bos_ts=9900)

    reentry1.register_trade_close(
        coin="BTCUSD",
        trade_id=cand1.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand1.model_dump()
    )

    # Simulate bot crash / reboot: Instantiate brand new ReentryManager with same DB
    reentry2 = ReentryManager(db=clean_db)

    # Verify state was reloaded from DB
    status = reentry2.get_market_status("BTCUSD")
    assert status["state"] == "POST_TRADE_COOLDOWN"
    assert status["last_trade_result"] == "COMPLETED"
    assert status["previous_setup_status"] == "CONSUMED"

    # Verify consumed setup check works on reloaded manager
    candles = [make_candle(10000, 70000, 70100, 69900, 70050)]
    ok, reason, _ = reentry2.evaluate_candidate(cand1, candles, atr=200.0)
    assert ok is False
    assert reason == "OLD_SETUP_ALREADY_CONSUMED"


def test_race_conditions_prevent_duplicate_reentry(clean_db):
    """Test 13: Rapid consecutive calls cannot create duplicate re-entry trades."""
    reentry = ReentryManager(db=clean_db)
    cand = make_candidate(coin="BTCUSD", detection_ts=10000)

    # First trade closes
    reentry.register_trade_close(
        coin="BTCUSD",
        trade_id=cand.id,
        result="COMPLETED",
        close_price=71000.0,
        candidate_or_trade=cand.model_dump()
    )

    candles = [make_candle(10000, 70000, 70100, 69900, 70050)]

    # Attempt rapid repeated evaluation of the same candidate
    results = [reentry.evaluate_candidate(cand, candles, atr=200.0)[0] for _ in range(10)]

    # Every single evaluation must deterministically return False!
    assert all(r is False for r in results)
