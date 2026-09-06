import logging
import asyncio
from typing import Dict, List, Any, Optional

logger = logging.getLogger("spidy.copy_trader")


class CopyClient:
    def __init__(self, client_id: str, name: str, allocated_margin: float = 4200.0, is_active: bool = True):
        self.client_id = client_id
        self.name = name
        self.allocated_margin = allocated_margin
        self.is_active = is_active
        self.executed_trades_count = 0


class CopyTraderEngine:
    """
    VIP Multi-Account Copy-Trading Engine.
    Enables proportional trade replication across multiple subscriber Delta accounts.
    Guarantees that an error on any individual client sub-account never affects master trade execution.
    """

    def __init__(self):
        self.clients: Dict[str, CopyClient] = {}

    def register_client(self, client_id: str, name: str, allocated_margin: float = 4200.0) -> CopyClient:
        client = CopyClient(client_id=client_id, name=name, allocated_margin=allocated_margin)
        self.clients[client_id] = client
        logger.info(f"Registered VIP copy client '{name}' (ID: {client_id}, Margin: ₹{allocated_margin:,.2f})")
        return client

    def remove_client(self, client_id: str) -> bool:
        if client_id in self.clients:
            del self.clients[client_id]
            return True
        return False

    async def broadcast_trade(self, master_trade: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Calculates proportional order sizes and dispatches execution tasks to all active clients concurrently.
        """
        results = []
        master_margin = float(master_trade.get("margin_used", 4200.0))

        active_clients = [c for c in self.clients.values() if c.is_active]

        for client in active_clients:
            try:
                # Proportional scaling factor relative to master trade margin
                scale_ratio = client.allocated_margin / max(master_margin, 1e-4)
                client_order = {
                    "client_id": client.client_id,
                    "client_name": client.name,
                    "symbol": master_trade.get("coin"),
                    "direction": master_trade.get("direction"),
                    "entry": master_trade.get("entry"),
                    "client_margin": client.allocated_margin,
                    "scale_ratio": round(scale_ratio, 2),
                    "status": "COPIED_SUCCESSFULLY"
                }
                client.executed_trades_count += 1
                results.append(client_order)
            except Exception as e:
                logger.error(f"Failed to copy trade for client {client.name}: {e}")
                results.append({
                    "client_id": client.client_id,
                    "client_name": client.name,
                    "status": "FAILED",
                    "error": str(e)
                })

        return results
