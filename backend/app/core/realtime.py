"""In-process pub/sub hub for WebSocket fan-out, keyed by user id.

Single-replica only. For multiple API replicas, bridge `publish` through Redis pub/sub
(each replica subscribes and forwards to its local sockets).
"""

import asyncio
import contextlib
import uuid
from collections import defaultdict
from typing import Any


class Hub:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, user_id: uuid.UUID) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._subs[user_id].add(q)
        return q

    def unsubscribe(self, user_id: uuid.UUID, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs[user_id].discard(q)
        if not self._subs[user_id]:
            self._subs.pop(user_id, None)

    def publish(self, user_id: uuid.UUID, event: str, data: dict[str, Any]) -> None:
        for q in list(self._subs.get(user_id, ())):
            with contextlib.suppress(
                asyncio.QueueFull
            ):  # slow consumer: drop rather than block writers
                q.put_nowait({"event": event, "data": data})


hub = Hub()
