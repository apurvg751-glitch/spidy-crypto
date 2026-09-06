import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from market_data.delta_execution import DeltaExecutionClient
from storage.database import Database


@pytest.fixture
def execution_client():
    return DeltaExecutionClient(
        api_key="test_api_key",
        api_secret="test_api_secret",
        base_url="https://api.india.delta.exchange"
    )


def test_client_initialization(execution_client):
    assert execution_client.api_key == "test_api_key"
    assert execution_client.api_secret == "test_api_secret"
    assert execution_client.get_product_id("BTCUSD") == 27
    assert execution_client.get_product_id("ETHUSD") == 3136
    assert execution_client.get_product_id("XRPUSD") == 14969
    assert execution_client.get_product_id("AVAXUSD") == 14830


def test_signature_generation(execution_client):
    ts, sig = execution_client._generate_signature("GET", "/v2/wallet/balances")
    assert len(ts) >= 10
    assert len(sig) == 64  # SHA256 hex length


@pytest.mark.asyncio
async def test_place_order_mock(execution_client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "result": {
            "id": 99999,
            "product_id": 3136,
            "size": 1,
            "side": "buy",
            "order_type": "limit_order",
            "limit_price": "2400.0"
        }
    }

    with patch.object(execution_client.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await execution_client.place_order(
            symbol="ETHUSD",
            side="buy",
            order_type="limit_order",
            size=1,
            limit_price=2400.0
        )
        assert res["success"] is True
        assert res["order"]["id"] == 99999
        await execution_client.close()


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_delta_exec.db"
    return Database(db_path=str(db_file))


@pytest.mark.asyncio
async def test_hybrid_market_entry_execution(temp_db):
    from trade_manager.manager import TradeManager
    import asyncio

    tm = TradeManager(db=temp_db)
    tm.delta_execution = AsyncMock()
    tm.delta_execution.place_order.return_value = {
        "success": True,
        "order": {"id": 12345, "average_fill_price": "105.50"}
    }
    tm.delta_execution.place_bracket_order.return_value = {"success": True}

    setup_mock = MagicMock()
    setup_mock.coin = "SOLUSD"
    setup_mock.direction = "LONG"
    setup_mock.entry = 105.50
    setup_mock.stop_loss = 105.20
    setup_mock.target_1 = 106.50

    pv_mock = MagicMock()
    pv_mock.delta_contracts = 2.0

    await tm._submit_live_order(setup_mock, pv_mock)

    # Verify market order placed immediately (hybrid execution)
    tm.delta_execution.place_order.assert_called_once_with(
        symbol="SOLUSD",
        side="buy",
        order_type="market_order",
        size=2
    )

    # Verify initial bracket protection placed
    tm.delta_execution.place_bracket_order.assert_called_once_with(
        symbol="SOLUSD",
        stop_loss_price=105.20,
        take_profit_price=106.50
    )


@pytest.mark.asyncio
async def test_live_partial_execution_on_delta(temp_db):
    from trade_manager.manager import TradeManager
    import asyncio

    tm = TradeManager(db=temp_db)
    tm.delta_execution = AsyncMock()
    tm.delta_execution.place_order.return_value = {"success": True}
    tm.delta_execution.place_bracket_order.return_value = {"success": True}
    tm.telegram.send_partial_profit_secured = AsyncMock(return_value=True)

    tm.active_trade = {
        "setup_id": "TEST_LIVE_PARTIAL",
        "coin": "SOLUSD",
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 95.0,
        "original_stop": 95.0,
        "target_1": 105.0,
        "target_2": 115.0,
        "trade_status": "ACTIVE",
        "margin_used": 4200.0,
        "leverage": 6,
        "delta_contracts": 3,
        "partial_closed": False
    }

    # Execute 40% partial
    ok, msg = await tm._execute_partial(pct=0.40, current_price=105.0, achieved_r=1.0)
    assert ok is True
    assert tm.active_trade["partial_closed"] is True
    assert tm.active_trade["delta_contracts"] == 2  # 3 - 1 = 2 contracts remaining runner!

    # Wait a tick for background task
    await asyncio.sleep(0.01)

    # Verify market reduce-only order was placed to bank 40% contracts
    tm.delta_execution.place_order.assert_called_once_with(
        symbol="SOLUSD",
        side="sell",
        order_type="market_order",
        size=1,
        reduce_only=True
    )

    # Verify bracket order was advanced to Breakeven SL and Runner Target 2
    tm.delta_execution.place_bracket_order.assert_called_once_with(
        symbol="SOLUSD",
        stop_loss_price=tm.active_trade["stop_loss"],
        take_profit_price=115.0
    )


@pytest.mark.asyncio
async def test_trailing_stop_updates_delta_bracket(temp_db):
    from trade_manager.manager import TradeManager
    import asyncio

    tm = TradeManager(db=temp_db)
    tm.delta_execution = AsyncMock()
    tm.delta_execution.place_bracket_order.return_value = {"success": True}
    tm.telegram.send_trade_lifecycle_update = AsyncMock(return_value=True)

    tm.active_trade = {
        "setup_id": "TEST_LIVE_TRAIL",
        "coin": "SOLUSD",
        "direction": "LONG",
        "entry": 100.0,
        "stop_loss": 100.25,
        "original_stop": 95.0,
        "target_1": 105.0,
        "target_2": 115.0,
        "trade_status": "ACTIVE",
        "margin_used": 2520.0,
        "leverage": 6,
        "delta_contracts": 2,
        "partial_closed": True
    }

    # Price moves to +2.2R (111.0) -> Trailing stop should ratchet to lock +1.0R (105.0)
    await tm.update_price("SOLUSD", 111.0)
    assert tm.active_trade["stop_loss"] >= 105.0

    # Wait a tick for background task
    await asyncio.sleep(0.01)

    # Verify bracket order was ratcheted on Delta Exchange with the new stop loss and runner TP2
    tm.delta_execution.place_bracket_order.assert_called_with(
        symbol="SOLUSD",
        stop_loss_price=tm.active_trade["stop_loss"],
        take_profit_price=115.0
    )

