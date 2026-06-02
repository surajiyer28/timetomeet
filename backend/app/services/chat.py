"""The home channel: a user's private conversation with their own agent.

This is the ONLY agent content a human ever sees. Inter-agent negotiation lives in
session_messages and is never surfaced to users. `post_chat` persists a line and streams
it to exactly one user, optionally tagged to a meeting (the agent's "what's happening" trace).
"""
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.websocket.manager import manager


async def post_chat(user_id: str, role: str, content: str, session_id: str | None = None) -> dict:
    content = (content or "").strip()
    if not content:
        return {}
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            text("""
                INSERT INTO agent_chat_messages (id, user_id, session_id, role, content, created_at)
                VALUES (gen_random_uuid(), :uid, :sid, :role, :content, :now)
                RETURNING id
            """),
            {"uid": user_id, "sid": session_id, "role": role, "content": content, "now": now},
        )
        msg_id = str(row.scalar())
        await db.commit()

    payload = {
        "id": msg_id, "role": role, "content": content,
        "session_id": session_id, "created_at": now.isoformat(),
    }
    await manager.broadcast_to_user(user_id, {"type": "CHAT_MESSAGE", "message": payload})
    return payload


async def post_trace_to_participants(session_id: str, content: str, exclude_user_id: str | None = None) -> None:
    """Post the same short trace line to every participant's own agent channel."""
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text("SELECT user_id FROM session_participants WHERE session_id = :sid"),
            {"sid": session_id},
        )
        uids = [str(r["user_id"]) for r in rows.mappings()]
    for uid in uids:
        if uid != exclude_user_id:
            await post_chat(uid, "agent", content, session_id)
