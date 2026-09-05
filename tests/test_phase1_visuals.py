import pytest
from telegram.chart_generator import generate_trade_chart
from journal.social_cards import generate_pnl_social_card


def test_generate_trade_chart_returns_valid_png():
    chart_bytes = generate_trade_chart(
        symbol="AVAXUSD",
        direction="LONG",
        entry=7.508,
        stop_loss=7.450,
        target_1=7.612,
        target_2=7.653
    )
    assert chart_bytes is not None
    assert len(chart_bytes) > 1000
    # Check PNG magic header
    assert chart_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_generate_social_card_returns_valid_png():
    card_bytes = generate_pnl_social_card(
        coin="AVAXUSD",
        direction="LONG",
        pnl_inr=425.0,
        achieved_r=0.83,
        win_rate=100.0,
        execution_grade="A+",
        exit_reason="Trailing Stop Hit (Profit Secured 🔒)"
    )
    assert card_bytes is not None
    assert len(card_bytes) > 1000
    assert card_bytes.startswith(b"\x89PNG\r\n\x1a\n")
