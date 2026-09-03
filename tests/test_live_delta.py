import pytest
from market_data.delta_rest import DeltaRestClient


@pytest.mark.asyncio
async def test_live_delta_rest_candles():
    """Live test fetching 5m and 15m candles from Delta Exchange India for all 3 coins."""
    client = DeltaRestClient()
    try:
        # ETHUSD 5m
        eth_5m = await client.get_candles("ETHUSD", resolution="5m", limit=10)
        assert len(eth_5m) > 0, "Failed to fetch ETHUSD 5m candles"
        assert eth_5m[-1].close > 0
        assert eth_5m[-1].time > eth_5m[0].time

        # BTCUSD 5m
        btc_5m = await client.get_candles("BTCUSD", resolution="5m", limit=10)
        assert len(btc_5m) > 0, "Failed to fetch BTCUSD 5m candles"
        assert btc_5m[-1].close > 0

        # SOLUSD 5m
        sol_5m = await client.get_candles("SOLUSD", resolution="5m", limit=10)
        assert len(sol_5m) > 0, "Failed to fetch SOLUSD 5m candles"
        assert sol_5m[-1].close > 0

        # ETHUSD 15m
        eth_15m = await client.get_candles("ETHUSD", resolution="15m", limit=10)
        assert len(eth_15m) > 0, "Failed to fetch ETHUSD 15m candles"
        assert eth_15m[-1].close > 0

    finally:
        await client.close()
