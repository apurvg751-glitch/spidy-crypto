from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from server import app, trade_manager


def test_war_room_endpoints():
    client = TestClient(app)

    # 1. Status endpoint returns 200
    res_status = client.get("/api/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert "global_status" in data
    assert "active_trade" in data

    # 2. Breakeven returns 400 when no trade is active
    trade_manager.active_trade = None
    res_be = client.post("/api/breakeven")
    assert res_be.status_code == 400

    # 3. Partial returns 400 when no trade is active
    res_part = client.post("/api/partial")
    assert res_part.status_code == 400

    # 4. Close active trade returns 200 and clears slot
    res_close = client.post("/api/close_active_trade")
    assert res_close.status_code == 200
    assert res_close.json()["status"] in ("all_cleared", "trade_closed")
    assert trade_manager.active_trade is None

    # 5. Trigger scan returns 200 without throwing errors
    res_scan = client.post("/api/trigger_scan")
    assert res_scan.status_code == 200
