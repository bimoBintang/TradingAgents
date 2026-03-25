"""WebSocket connection manager — tracks per-user active connections.

Supports multiple connections per user (e.g. multiple browser tabs).
Thread-safe via asyncio lock.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Any

from fastapi import WebSocket

logger = logging.getLogger("api.ws_manager")


class ConnectionManager:
    """Manages WebSocket connections grouped by user_id."""

    def __init__(self):
        # user_id → list of active WebSocket connections
        self._connections: Dict[int, List[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections[user_id].append(websocket)
        logger.info("WS connected: user_id=%d (total=%d)", user_id, len(self._connections[user_id]))

    async def disconnect(self, websocket: WebSocket, user_id: int):
        """Remove a closed WebSocket connection."""
        async with self._lock:
            conns = self._connections[user_id]
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                del self._connections[user_id]
        logger.info("WS disconnected: user_id=%d", user_id)

    async def send_json(self, user_id: int, data: Dict[str, Any]):
        """Send JSON data to all connections of a specific user."""
        async with self._lock:
            conns = list(self._connections.get(user_id, []))

        stale = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                stale.append(ws)

        # Clean up broken connections
        if stale:
            async with self._lock:
                for ws in stale:
                    if ws in self._connections.get(user_id, []):
                        self._connections[user_id].remove(ws)

    async def broadcast(self, data: Dict[str, Any]):
        """Send JSON data to ALL connected users."""
        async with self._lock:
            all_conns = [
                (uid, list(conns))
                for uid, conns in self._connections.items()
            ]

        for uid, conns in all_conns:
            for ws in conns:
                try:
                    await ws.send_json(data)
                except Exception:
                    pass

    @property
    def active_count(self) -> int:
        """Total number of active WebSocket connections."""
        return sum(len(conns) for conns in self._connections.values())


# Global singleton
manager = ConnectionManager()
