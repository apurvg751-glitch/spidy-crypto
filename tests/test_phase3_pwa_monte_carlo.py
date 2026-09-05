import pytest
from fastapi.testclient import TestClient
from server import app
from backtesting.monte_carlo import MonteCarloEngine


def test_monte_carlo_simulation_runs():
    res = MonteCarloEngine.run_simulation(
        initial_capital=3000.0,
        win_rate=0.65,
        avg_win_r=1.8,
        avg_loss_r=1.0,
        risk_per_trade_pct=1.5,
        num_trades=50,
        num_simulations=100
    )
    assert res["num_simulations"] == 100
    assert res["num_trades"] == 50
    assert res["median_equity"] > 0
    assert res["ruin_probability_pct"] <= 5.0
    assert res["status"] in ("APPROVED_ROBUST", "HIGH_RISK")


def test_monte_carlo_api_endpoint():
    client = TestClient(app)
    res = client.get("/api/monte-carlo?simulations=50&trades=20")
    assert res.status_code == 200
    data = res.json()
    assert "median_equity" in data
    assert "ruin_probability_pct" in data


def test_pwa_manifest_exists():
    from pathlib import Path
    manifest_path = Path("ui/static/manifest.json")
    sw_path = Path("ui/static/sw.js")
    assert manifest_path.exists()
    assert sw_path.exists()
