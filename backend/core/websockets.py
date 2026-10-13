"""
WebSocket ConnectionManager for real-time progress broadcasting.

Manages active WebSocket connections keyed by session ID.
Background threads push progress via asyncio.run_coroutine_threadsafe().
"""

import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections grouped by video session ID.

    When Celery is integrated in the future, this class stays unchanged.
    Only the source of broadcast calls changes (Redis Pub/Sub listener
    instead of direct asyncio.run_coroutine_threadsafe from threads).
    """

    def __init__(self) -> None:
        # session_id -> list of active WebSocket connections
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept a WebSocket and register it under the session ID."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
        logger.info(f"WebSocket connected for session {session_id} "
                     f"(total: {len(self.active_connections[session_id])})")

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket from the session's connection list."""
        if session_id in self.active_connections:
            try:
                self.active_connections[session_id].remove(websocket)
            except ValueError:
                pass
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
            logger.info(f"WebSocket disconnected for session {session_id}")

    async def broadcast(self, session_id: str, data: dict) -> None:
        """Send a JSON message to all WebSocket connections for a session."""
        if session_id not in self.active_connections:
            return

        stale: list[WebSocket] = []
        for ws in self.active_connections[session_id]:
            try:
                await ws.send_json(data)
            except Exception:
                stale.append(ws)

        # Clean up any broken connections
        for ws in stale:
            self.disconnect(session_id, ws)


# Singleton instance — imported by views.py and pipeline.py
manager = ConnectionManager()
