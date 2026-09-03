import pytest
from journal.trade_journal import TradeJournalEngine


def test_trade_journal_summary():
    data = TradeJournalEngine.get_daily_trades()
    assert "total_trades" in data
    assert "win_rate" in data
    assert "total_r" in data
    assert "trades" in data
    assert isinstance(data["trades"], list)


def test_trade_journal_telegram_markdown():
    md = TradeJournalEngine.generate_telegram_markdown()
    assert "DAILY TRADE JOURNAL" in md
    assert "NET PERFORMANCE SUMMARY" in md
    assert "FORWARD TRADES AUDIT" in md


def test_trade_journal_html_generation():
    html = TradeJournalEngine.generate_html_page()
    assert "<!DOCTYPE html>" in html
    assert "DAILY INSTITUTIONAL JOURNAL" in html
    assert "<table>" in html
