import asyncio
import contextlib
import uuid

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.db import SessionLocal
from app.core.realtime import hub
from app.core.security import decode_access_token
from app.models import AuthSession

router = APIRouter(tags=["realtime"])


async def _authenticate(token: str) -> uuid.UUID | None:
    try:
        payload = decode_access_token(token)
        async with SessionLocal() as db:
            sess = await db.get(AuthSession, uuid.UUID(payload["sid"]))
            if sess is None or sess.revoked:
                return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


@router.websocket("/ws")
async def ws(websocket: WebSocket, token: str = "") -> None:
    """Real-time events for the signed-in user: message.new, conversation.updated, notification.new …

    Auth: `?token=<access token>` (browsers can't set headers on WebSocket). Clients should reconnect with a
    refreshed token when the socket closes with code 4401.
    """
    user_id = await _authenticate(token)
    if user_id is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    q = hub.subscribe(user_id)
    await websocket.send_json({"event": "ready", "data": {}})

    async def pump() -> None:
        while True:
            await websocket.send_json(await q.get())

    async def listen() -> None:
        while True:
            if (await websocket.receive_text()) == "ping":
                await websocket.send_json({"event": "pong", "data": {}})

    tasks = [asyncio.create_task(pump()), asyncio.create_task(listen())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await t
        hub.unsubscribe(user_id, q)
