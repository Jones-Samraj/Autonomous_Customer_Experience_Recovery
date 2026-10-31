"""WebSocket fan-out. Sync code (agents, background tasks) publishes via a thread-safe queue hand-off."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger("cx.events")


class ConnectionManager:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def _broadcast(self, message: dict):
        payload = json.dumps(message, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                self.clients.discard(ws)


manager = ConnectionManager()


def publish(message: dict) -> None:
    """Fire-and-forget; safe to call from worker threads, and a no-op when no server loop is running (tests)."""
    loop = manager.loop
    if loop is None or not manager.clients:
        return
    try:
        asyncio.run_coroutine_threadsafe(manager._broadcast(message), loop)
    except Exception:  # noqa: BLE001
        log.debug("publish failed", exc_info=True)
