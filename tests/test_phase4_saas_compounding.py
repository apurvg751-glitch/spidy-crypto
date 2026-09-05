import pytest
from trade_manager.copy_trader import CopyTraderEngine


@pytest.mark.asyncio
async def test_copy_trader_engine_replicates_to_clients():
    engine = CopyTraderEngine()
    engine.register_client("VIP_001", "Client A", allocated_margin=1500.0)
    engine.register_client("VIP_002", "Client B", allocated_margin=6000.0)

    master_trade = {
        "coin": "AVAXUSD",
        "direction": "LONG",
        "entry": 7.508,
        "margin_used": 3000.0
    }

    results = await engine.broadcast_trade(master_trade)
    assert len(results) == 2
    assert results[0]["client_id"] == "VIP_001"
    assert results[0]["scale_ratio"] == 0.5  # 1500 / 3000 = 0.5x
    assert results[1]["client_id"] == "VIP_002"
    assert results[1]["scale_ratio"] == 2.0  # 6000 / 3000 = 2.0x
    assert results[0]["status"] == "COPIED_SUCCESSFULLY"
