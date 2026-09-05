import pytest
from fastapi.testclient import TestClient
from server import app
from config.settings import settings


@pytest.fixture
def client():
    # settings.ADMIN_PIN is "1408" by default
    return TestClient(app, raise_server_exceptions=False)


def test_public_read_endpoints_remain_accessible(client):
    """Verifies that monitoring and telemetry endpoints remain open for HUD viewing without PIN."""
    endpoints = [
        "/api/status",
        "/api/performance",
        "/api/model_stats",
        "/api/history",
        "/api/monte-carlo?simulations=10&trades=10",
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200, f"Expected 200 for public endpoint {ep}, got {res.status_code}"


def test_verify_pin_endpoint(client):
    """Tests the /api/verify_pin endpoint with correct and incorrect PIN."""
    # Correct PIN
    res_correct = client.post("/api/verify_pin", json={"pin": "1408"})
    assert res_correct.status_code == 200
    assert res_correct.json().get("authenticated") is True

    # Incorrect PIN
    res_wrong = client.post("/api/verify_pin", json={"pin": "9999"})
    assert res_wrong.status_code == 401


def test_sensitive_endpoints_block_unauthorized_access(client):
    """Verifies that all 7 sensitive control endpoints reject requests without a PIN."""
    sensitive_endpoints = [
        "/api/close_active_trade",
        "/api/pause",
        "/api/resume",
        "/api/breakeven",
        "/api/partial",
        "/api/reset",
        "/api/simulate_setup?symbol=ETHUSD&direction=LONG&model_id=MODEL_1&force=false",
    ]
    for ep in sensitive_endpoints:
        # Without any PIN
        res_no_pin = client.post(ep)
        assert res_no_pin.status_code == 401, f"Expected 401 for unauthenticated {ep}, got {res_no_pin.status_code}"

        # With incorrect PIN in header
        res_wrong_header = client.post(ep, headers={"X-Admin-PIN": "0000"})
        assert res_wrong_header.status_code == 401, f"Expected 401 for wrong PIN {ep}, got {res_wrong_header.status_code}"

        # With incorrect PIN in query param
        separator = "&" if "?" in ep else "?"
        res_wrong_query = client.post(f"{ep}{separator}pin=9999")
        assert res_wrong_query.status_code == 401, f"Expected 401 for wrong query PIN {ep}, got {res_wrong_query.status_code}"


def test_sensitive_endpoints_succeed_with_valid_pin_header(client):
    """Verifies that requests carrying header 'X-Admin-PIN: 1408' pass authentication."""
    headers = {"X-Admin-PIN": "1408"}

    # Test resume (safe state toggle)
    res_resume = client.post("/api/resume", headers=headers)
    assert res_resume.status_code == 200
    assert res_resume.json().get("status") == "resumed"

    # Test pause
    res_pause = client.post("/api/pause", headers=headers)
    assert res_pause.status_code == 200
    assert res_pause.json().get("status") == "stopped"

    # Resume back
    res_resume2 = client.post("/api/resume", headers=headers)
    assert res_resume2.status_code == 200


def test_sensitive_endpoints_succeed_with_valid_pin_query(client):
    """Verifies that requests carrying query param '?pin=1408' also pass authentication."""
    res = client.post("/api/resume?pin=1408")
    assert res.status_code == 200
    assert res.json().get("status") == "resumed"
