import time
import hmac
import hashlib
import json
import logging
from typing import Optional, Any, Dict, List
import httpx

from config.settings import settings

logger = logging.getLogger("spidy.execution.delta")


class DeltaExecutionClient:
    """
    Production execution client for Delta Exchange India (/v2 API).
    Handles HMAC-SHA256 authentication, product ID mapping, order placement,
    bracket SL/TP orders, order cancellations, position queries, and account balance monitoring.
    """

    FALLBACK_PRODUCT_IDS: Dict[str, int] = {
        "BTCUSD": 27,
        "ETHUSD": 3136,
        "SOLUSD": 14823,
        "XRPUSD": 14969,
        "AVAXUSD": 14830,
        "BNBUSD": 3010,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        self.api_key = api_key or settings.DELTA_API_KEY
        self.api_secret = api_secret or settings.DELTA_API_SECRET
        self.base_url = (base_url or settings.DELTA_REST_URL).rstrip("/")
        self.client = httpx.AsyncClient(verify=False, timeout=12.0)
        self.product_ids: Dict[str, int] = dict(self.FALLBACK_PRODUCT_IDS)

    async def close(self):
        await self.client.aclose()

    def _generate_signature(self, method: str, path: str, query: str = "", body: str = "") -> tuple[str, str]:
        timestamp = str(int(time.time()))
        message = method.upper() + timestamp + path + query + body
        sig = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return timestamp, sig

    def _get_headers(self, method: str, path: str, query: str = "", body: str = "") -> Dict[str, str]:
        timestamp, signature = self._generate_signature(method, path, query, body)
        return {
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }

    async def init_product_ids(self) -> Dict[str, int]:
        """Fetches live product IDs from Delta Exchange India to ensure exact contract mapping."""
        try:
            path = "/v2/products"
            headers = self._get_headers("GET", path)
            res = await self.client.get(f"{self.base_url}{path}", headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    for item in data.get("result", []):
                        sym = item.get("symbol")
                        pid = item.get("id")
                        if sym and pid:
                            self.product_ids[sym] = int(pid)
                    logger.info(f"Initialized Delta product IDs: {self.product_ids}")
            return self.product_ids
        except Exception as e:
            logger.warning(f"Failed to fetch Delta product IDs dynamically, using fallback mapping: {e}")
            return self.product_ids

    def get_product_id(self, symbol: str) -> int:
        pid = self.product_ids.get(symbol) or self.FALLBACK_PRODUCT_IDS.get(symbol)
        if not pid:
            raise ValueError(f"Unknown Delta product symbol: {symbol}")
        return pid

    async def get_wallet_balances(self) -> Dict[str, Any]:
        """Fetches live wallet equity and available balances in USD and INR."""
        path = "/v2/wallet/balances"
        headers = self._get_headers("GET", path)
        try:
            res = await self.client.get(f"{self.base_url}{path}", headers=headers)
            if res.status_code != 200:
                logger.error(f"Delta get_wallet_balances HTTP {res.status_code}: {res.text}")
                return {"success": False, "error": res.text}
            return res.json()
        except Exception as e:
            logger.error(f"Delta get_wallet_balances exception: {e}")
            return {"success": False, "error": str(e)}

    async def check_spread(self, symbol: str, max_spread_bps: float = 12.0) -> tuple[bool, float, float]:
        """
        Pre-flight spread check.
        Queries /v2/tickers/{symbol}. Computes spread = (ask - bid) / bid.
        Returns (is_acceptable: bool, spread_bps: float, spread_pct: float).
        If spread > max_spread_bps (e.g. 12 bps = 0.12%), returns False.
        """
        try:
            path = f"/v2/tickers/{symbol}"
            res = await self.client.get(f"{self.base_url}{path}")
            if res.status_code == 200:
                data = res.json()
                result = data.get("result") or {}
                quotes = result.get("quotes") or {}
                best_bid = float(quotes.get("best_bid") or result.get("mark_price") or 0.0)
                best_ask = float(quotes.get("best_ask") or result.get("mark_price") or 0.0)
                if best_bid > 0 and best_ask > 0:
                    spread = best_ask - best_bid
                    spread_pct = (spread / best_bid) * 100.0
                    spread_bps = spread_pct * 100.0
                    is_acceptable = spread_bps <= max_spread_bps
                    return is_acceptable, round(spread_bps, 2), round(spread_pct, 4)
        except Exception as e:
            logger.warning(f"Delta check_spread exception for {symbol}: {e}")
        return True, 0.0, 0.0

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "limit_order",
        size: int = 1,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        post_only: bool = False,
        reduce_only: bool = False,
        bracket_stop_loss_price: Optional[float] = None,
        bracket_take_profit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Places an order on Delta Exchange India.
        side: 'buy' or 'sell'
        order_type: 'limit_order' or 'market_order'
        size: integer number of contracts
        """
        path = "/v2/orders"
        product_id = self.get_product_id(symbol)
        payload: Dict[str, Any] = {
            "product_id": product_id,
            "size": int(size),
            "side": side.lower(),
            "order_type": order_type,
            "reduce_only": reduce_only
        }
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
            if post_only:
                payload["post_only"] = "true"
        if stop_price is not None:
            payload["stop_price"] = str(stop_price)
            payload["stop_order_type"] = "stop_loss_order"

        if bracket_stop_loss_price is not None:
            payload["bracket_stop_loss_price"] = str(round(bracket_stop_loss_price, 4))
            payload["bracket_stop_trigger_method"] = "mark_price"
        if bracket_take_profit_price is not None:
            payload["bracket_take_profit_price"] = str(round(bracket_take_profit_price, 4))
            payload["bracket_stop_trigger_method"] = "mark_price"

        body = json.dumps(payload)
        headers = self._get_headers("POST", path, body=body)

        try:
            logger.info(f"Submitting order to Delta [{symbol} {side.upper()} size={size}]: {payload}")
            res = await self.client.post(f"{self.base_url}{path}", data=body, headers=headers)
            data = res.json()
            if res.status_code in (200, 201) and data.get("success"):
                logger.info(f"Delta order placed successfully: {data.get('result')}")
                return {"success": True, "order": data.get("result")}
            else:
                logger.error(f"Delta order failed HTTP {res.status_code}: {res.text}")
                return {"success": False, "error": data.get("error") or res.text}
        except Exception as e:
            logger.error(f"Delta order placement exception: {e}")
            return {"success": False, "error": str(e)}

    async def place_bracket_order(
        self,
        symbol: str,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
        is_limit_tp: bool = True
    ) -> Dict[str, Any]:
        """
        Places or updates a Bracket Order (Stop Loss & Take Profit) on an active position.
        Uses limit_order for Take Profit to qualify for 0.02% Maker Fee (saving 60% in fees).
        Automatically cancels old stop orders and issues standalone reduce_only Stop Loss
        when updating SL to Breakeven above entry.
        """
        path = "/v2/orders/bracket"
        product_id = self.get_product_id(symbol)
        payload: Dict[str, Any] = {
            "product_id": product_id,
            "bracket_stop_trigger_method": "mark_price"
        }
        if stop_loss_price is not None:
            payload["stop_loss_order"] = {
                "order_type": "market_order",
                "stop_price": str(round(stop_loss_price, 4))
            }
        if take_profit_price is not None:
            tp_type = "limit_order" if is_limit_tp else "market_order"
            tp_payload: Dict[str, Any] = {
                "order_type": tp_type,
                "stop_price": str(round(take_profit_price, 4))
            }
            if is_limit_tp:
                tp_payload["limit_price"] = str(round(take_profit_price, 4))
            payload["take_profit_order"] = tp_payload

        body = json.dumps(payload)
        headers = self._get_headers("POST", path, body=body)

        try:
            res = await self.client.post(f"{self.base_url}{path}", data=body, headers=headers)
            data = res.json()
            if res.status_code in (200, 201) and data.get("success"):
                logger.info(f"Delta bracket order placed for {symbol}: SL={stop_loss_price}, TP={take_profit_price} (Limit TP: {is_limit_tp})")
                return {"success": True, "result": data.get("result")}
            else:
                logger.warning(f"Delta bracket order response HTTP {res.status_code}: {res.text}. Attempting fallback standalone reduce_only SL...")
                # Fallback: If bracket API fails (e.g. SL above entry), place standalone reduce_only Stop Market order
                if stop_loss_price is not None:
                    fallback_res = await self.place_standalone_stop_loss(symbol, stop_loss_price)
                    if fallback_res.get("success"):
                        return {"success": True, "result": fallback_res.get("order"), "note": "Fallback standalone SL active"}
                return {"success": False, "error": data.get("error") or res.text}
        except Exception as e:
            logger.error(f"Delta bracket order exception: {e}")
            return {"success": False, "error": str(e)}

    async def place_standalone_stop_loss(self, symbol: str, stop_price: float, side: str = "sell") -> Dict[str, Any]:
        """Places a standalone reduce_only Stop-Market order (bypasses bracket limits for Breakeven trailing)."""
        await self.cancel_all_orders(symbol)
        return await self.place_order(
            symbol=symbol,
            side=side,
            order_type="stop_market_order",
            size=1, # reduce_only will close remaining position
            stop_price=stop_price,
            reduce_only=True
        )

    async def cancel_order(self, order_id: int, product_id: int) -> Dict[str, Any]:
        """Cancels an active order by ID."""
        path = "/v2/orders"
        payload = {"id": int(order_id), "product_id": int(product_id)}
        body = json.dumps(payload)
        headers = self._get_headers("DELETE", path, body=body)
        try:
            res = await self.client.request("DELETE", f"{self.base_url}{path}", data=body, headers=headers)
            return res.json()
        except Exception as e:
            logger.error(f"Delta cancel order error: {e}")
            return {"success": False, "error": str(e)}

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Cancels all open orders (optionally for a specific symbol) by querying open orders and cancelling each."""
        try:
            target_pid = self.get_product_id(symbol) if symbol else None
            path = "/v2/orders"
            headers = self._get_headers("GET", path, query="?state=open")
            res = await self.client.get(f"{self.base_url}{path}?state=open", headers=headers)
            if res.status_code != 200:
                return {"success": False, "error": res.text}
            
            data = res.json()
            orders = data.get("result", [])
            cancelled_count = 0
            for o in orders:
                pid = o.get("product_id")
                oid = o.get("id")
                if target_pid is None or pid == target_pid:
                    if oid and pid:
                        await self.cancel_order(order_id=oid, product_id=pid)
                        cancelled_count += 1
            logger.info(f"Cancelled {cancelled_count} open orders on Delta India (symbol={symbol})")
            return {"success": True, "cancelled_count": cancelled_count}
        except Exception as e:
            logger.error(f"Delta cancel all orders error: {e}")
            return {"success": False, "error": str(e)}

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetches all open positions on Delta Exchange India."""
        path = "/v2/positions/margined"
        headers = self._get_headers("GET", path)
        try:
            res = await self.client.get(f"{self.base_url}{path}", headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("success"):
                    return data.get("result", [])
            return []
        except Exception as e:
            logger.error(f"Delta get_positions error: {e}")
            return []
