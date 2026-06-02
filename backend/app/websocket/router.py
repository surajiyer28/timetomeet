import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt
from sqlalchemy import text
from app.config import settings
from app.database import AsyncSessionLocal
from app.websocket.manager import manager

router = APIRouter(tags=["websocket"])


async def _get_ws_user(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        if not user_id:
            return None
    except JWTError:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT id, name, username, timezone FROM users WHERE id = :id"),
            {"id": user_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


@router.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(...),
):
    user = await _get_ws_user(token)
    if not user or str(user["id"]) != user_id:
        await websocket.close(code=4001)
        return

    await manager.connect(user_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = msg.get("type")
            session_id = msg.get("session_id")

            if event_type == "APPROVE" and session_id:
                await _handle_approve(user_id, session_id)

            elif event_type == "REJECT" and session_id:
                reason = msg.get("reason", "No reason given")
                await _handle_reject(user_id, session_id, reason)

            elif event_type in ("USER_MESSAGE", "VOICE_INPUT"):
                content = (msg.get("content") or msg.get("transcript") or "").strip()
                if content:
                    # The home agent invokes an LLM — run it off the receive loop.
                    asyncio.create_task(_handle_user_message(user_id, content))

    except WebSocketDisconnect:
        manager.disconnect(user_id)


async def _require_participant(user_id: str, session_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("SELECT 1 FROM session_participants WHERE session_id = :sid AND user_id = :uid"),
            {"sid": session_id, "uid": user_id},
        )
        return row.first() is not None


async def _handle_approve(user_id: str, session_id: str):
    if not await _require_participant(user_id, session_id):
        return
    from app.services.session_lifecycle import record_approval
    await record_approval(user_id, session_id)


async def _handle_reject(user_id: str, session_id: str, reason: str):
    if not await _require_participant(user_id, session_id):
        return
    from app.services.session_lifecycle import record_rejection
    name = await _user_name(user_id)
    await record_rejection(user_id, session_id, reason, name)


async def _user_name(user_id: str) -> str:
    async with AsyncSessionLocal() as db:
        row = await db.execute(text("SELECT name FROM users WHERE id = :id"), {"id": user_id})
        m = row.mappings().first()
        return m["name"] if m else "Someone"


async def _handle_user_message(user_id: str, content: str):
    """Route a message from the user to their personal (home) agent.

    The home agent handles scheduling, calendar questions, guidance and cancellations.
    Both the user's message and the agent's reply are persisted to the home channel and
    streamed back as CHAT_MESSAGE events (the reply also drives text-to-speech)."""
    from app.services.chat import post_chat
    await post_chat(user_id, "user", content)

    from app.agents.scheduling_agent import run_home_agent_turn
    try:
        reply = await run_home_agent_turn(user_id, content)
    except Exception as e:
        print(f"[home-agent] error for user {user_id}: {e}")
        reply = "Sorry, I ran into a problem with that — mind trying again?"

    await post_chat(user_id, "agent", reply)
