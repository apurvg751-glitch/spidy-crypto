import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from market_data.delta_execution import DeltaExecutionClient


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
