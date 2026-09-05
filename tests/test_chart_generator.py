import pytest
from telegram.chart_generator import generate_trade_chart


def test_generate_trade_chart_synthetic():
    png_bytes = generate_trade_chart(
        symbol="BTCUSD",
        direction="LONG",
        entry=65000.0,
        stop_loss=64500.0,
        target_1=66000.0,
        target_2=67000.0
    )
    assert len(png_bytes) > 1000
    # Check PNG magic header: \x89PNG\r\n\x1a\n
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_trade_chart_with_candles():
    mock_candles = [
        {"open": 64800, "high": 65100, "low": 64750, "close": 65050},
        {"open": 65050, "high": 65200, "low": 64950, "close": 65150},
        {"open": 65150, "high": 65300, "low": 65000, "close": 65020},
        {"open": 65020, "high": 65100, "low": 64800, "close": 64850},
        {"open": 64850, "high": 65000, "low": 64800, "close": 64980},
    ]
    png_bytes = generate_trade_chart(
        symbol="ETHUSD",
        direction="SHORT",
        entry=3500.0,
        stop_loss=3540.0,
        target_1=3420.0,
        target_2=3360.0,
        candles=mock_candles
    )
    assert len(png_bytes) > 1000
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
