from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_user

router = APIRouter(prefix="/feed", tags=["feed"])

# Statuses worth showing as a card in the stream (actionable or terminal).
_CARD_STATUSES = ("PROPOSED", "PENDING_APPROVAL", "CONFIRMED", "ESCALATED")


@router.get("")
async def get_feed(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The user's stream. Privacy model: a user only ever sees their OWN agent. We return
    the user's home conversation (general chat + per-meeting agent traces) plus a card per
    meeting that needs a look. The inter-agent negotiation thread is never exposed."""
    uid = str(current_user["id"])

    # Meetings the user participates in, with their own approval status + participant handles.
    sess_rows = (await db.execute(
        text("""
            SELECT ss.id, ss.status, ss.purpose, ss.proposed_start, ss.proposed_end, ss.updated_at,
                   me.approval_status AS my_approval_status
            FROM scheduling_sessions ss
            JOIN session_participants me ON me.session_id = ss.id AND me.user_id = :uid
        """),
        {"uid": uid},
    )).mappings().all()

    sessions: dict[str, dict] = {}
    for s in sess_rows:
        sid = str(s["id"])
        parts = (await db.execute(
            text("""
                SELECT u.username FROM session_participants sp
                JOIN users u ON u.id = sp.user_id
                WHERE sp.session_id = :sid AND sp.user_id != :uid
                ORDER BY u.username
            """),
            {"sid": sid, "uid": uid},
        )).mappings().all()
        sessions[sid] = {
            "status": s["status"],
            "purpose": s["purpose"],
            "proposed_start": s["proposed_start"].isoformat() if s["proposed_start"] else None,
            "proposed_end": s["proposed_end"].isoformat() if s["proposed_end"] else None,
            "participants": [p["username"] for p in parts],  # the OTHER people (for the tag)
            "my_approval_status": s["my_approval_status"],
            "updated_at": s["updated_at"].isoformat(),
        }

    items: list[dict] = []
    latest_trace_at: dict[str, str] = {}  # session_id -> last trace timestamp (for card placement)

    # Home conversation: you <-> your agent, including per-meeting traces.
    chat_rows = (await db.execute(
        text("""
            SELECT id, role, content, session_id, created_at
            FROM agent_chat_messages WHERE user_id = :uid ORDER BY created_at ASC
        """),
        {"uid": uid},
    )).mappings().all()
    for r in chat_rows:
        sid = str(r["session_id"]) if r["session_id"] else None
        ts = r["created_at"].isoformat()
        if sid:
            latest_trace_at[sid] = ts
        items.append({
            "kind": "chat", "id": str(r["id"]), "role": r["role"], "content": r["content"],
            "session_id": sid,
            "participants": sessions.get(sid, {}).get("participants", []) if sid else [],
            "created_at": ts,
        })

    # One card per meeting that's proposed/confirmed/escalated. Anchor it to the meeting's
    # most recent trace so the card sits right BELOW the agent's announcement of it.
    for sid, meta in sessions.items():
        if meta["status"] in _CARD_STATUSES:
            items.append({
                "kind": "proposal", "id": f"card-{sid}", "session_id": sid,
                "created_at": latest_trace_at.get(sid, meta["updated_at"]), "session": meta,
            })

    # Sort by time; when a card shares a timestamp with its announcing trace, the card comes after.
    items.sort(key=lambda i: (i["created_at"], 1 if i["kind"] == "proposal" else 0))
    return {"items": items, "sessions": sessions}
