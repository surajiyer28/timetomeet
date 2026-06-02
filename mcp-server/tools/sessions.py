import uuid
import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import httpx
from sqlalchemy import text
from database import AsyncSessionLocal
from config import settings
from context import caller_id


def _human_time(dt: datetime, tz_name: str | None = None) -> str:
    """Render a datetime like 'Tuesday, Jun 3 at 1:00 PM EDT' (no raw ISO in user-facing text).
    If tz_name (IANA) is given, convert to it so the zone abbreviation is meaningful."""
    if tz_name:
        try:
            dt = dt.astimezone(ZoneInfo(tz_name))
        except Exception:
            pass
    zone = dt.strftime("%Z")
    base = f"{dt.strftime('%A, %b')} {dt.day} at {dt.strftime('%-I:%M %p')}"
    return f"{base} {zone}".strip()


async def _broadcast(payload: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{settings.backend_url}/internal/broadcast", json=payload)
    except Exception:
        pass  # backend may not be up yet; best-effort broadcast


async def _is_participant(db, session_id: str, user_id: str) -> bool:
    row = await db.execute(
        text("SELECT 1 FROM session_participants WHERE session_id = :sid AND user_id = :uid"),
        {"sid": session_id, "uid": user_id},
    )
    return row.first() is not None


async def get_session_thread(session_id: str) -> dict:
    """Returns the full negotiation thread for a session (chronological) plus its current
    status, purpose, duration, and any proposed time. You must be a participant."""
    user_id = caller_id()
    async with AsyncSessionLocal() as db:
        if not await _is_participant(db, session_id, user_id):
            return {"error": "You are not a participant in this session."}

        result = await db.execute(
            text("""
                SELECT sm.id, sm.sender_user_id, u.username, u.name,
                       sm.sender_type, sm.content, sm.message_type, sm.metadata, sm.created_at
                FROM session_messages sm
                JOIN users u ON u.id = sm.sender_user_id
                WHERE sm.session_id = :session_id
                ORDER BY sm.created_at ASC
            """),
            {"session_id": session_id},
        )
        messages = [
            {
                "id": str(r["id"]),
                "sender_user_id": str(r["sender_user_id"]),
                "username": r["username"],
                "name": r["name"],
                "sender_type": r["sender_type"],
                "content": r["content"],
                "message_type": r["message_type"],
                "metadata": r["metadata"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in result.mappings()
        ]

        sess_result = await db.execute(
            text("SELECT status, purpose, duration_minutes, proposed_start, proposed_end FROM scheduling_sessions WHERE id = :id"),
            {"id": session_id},
        )
        sess = sess_result.mappings().first()
        if not sess:
            return {"error": "Session not found"}

        return {
            "session_id": session_id,
            "status": sess["status"],
            "purpose": sess["purpose"],
            "duration_minutes": sess["duration_minutes"],
            "proposed_start": sess["proposed_start"].isoformat() if sess["proposed_start"] else None,
            "proposed_end": sess["proposed_end"].isoformat() if sess["proposed_end"] else None,
            "messages": messages,
        }


async def send_message(
    session_id: str,
    content: str,
    message_type: str,
    metadata: dict | None = None,
) -> dict:
    """Posts a message to the shared negotiation thread as YOUR agent and broadcasts it
    to all participants. message_type is one of: INFO | COUNTER | CLARIFY | ESCALATE.
    Use propose_time / accept_proposal / reject_proposal for those specific actions."""
    user_id = caller_id()
    metadata = metadata or {}
    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        if not await _is_participant(db, session_id, user_id):
            return {"error": "You are not a participant in this session."}
        await db.execute(
            text("""
                INSERT INTO session_messages (id, session_id, sender_user_id, sender_type, content, message_type, metadata, created_at)
                VALUES (:id, :session_id, :sender_user_id, 'AGENT', :content, :message_type, CAST(:metadata AS jsonb), :now)
            """),
            {
                "id": msg_id,
                "session_id": session_id,
                "sender_user_id": user_id,
                "content": content,
                "message_type": message_type,
                "metadata": json.dumps(metadata) if metadata else None,
                "now": now,
            },
        )
        await db.commit()

    await _broadcast({"type": "MESSAGE", "session_id": session_id, "message": {
        "id": msg_id, "sender_user_id": user_id, "sender_type": "AGENT",
        "content": content, "message_type": message_type, "metadata": metadata,
        "created_at": now.isoformat(),
    }})
    return {"status": "sent", "message_id": msg_id}


async def propose_time(
    session_id: str,
    proposed_slots: list,
    reasoning: str,
) -> dict:
    """Proposes a meeting time and moves the session to PROPOSED so the humans can approve.
    proposed_slots must be a list of ISO 8601 datetime strings (use the exact strings from
    check_my_availability), e.g. ["2026-06-08T09:00:00-05:00"]. The first slot is the proposal."""
    user_id = caller_id()
    if not proposed_slots:
        return {"error": "proposed_slots must not be empty"}

    raw = proposed_slots[0]
    slot_str = (raw.get("start") or raw.get("time") or raw.get("datetime") or "") if isinstance(raw, dict) else str(raw)
    slot_str = slot_str.replace("Z", "+00:00")
    if not slot_str:
        return {"error": "Could not parse the proposed slot — pass ISO 8601 datetime strings."}
    try:
        proposed_start = datetime.fromisoformat(slot_str)
    except ValueError:
        return {"error": f"'{slot_str}' is not a valid ISO 8601 datetime."}

    msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    metadata = {"proposed_slots": proposed_slots, "reasoning": reasoning}

    async with AsyncSessionLocal() as db:
        if not await _is_participant(db, session_id, user_id):
            return {"error": "You are not a participant in this session."}

        dur_row = await db.execute(
            text("SELECT duration_minutes FROM scheduling_sessions WHERE id = :id"),
            {"id": session_id},
        )
        drow = dur_row.mappings().first()
        if not drow:
            return {"error": "Session not found"}
        duration = drow["duration_minutes"] or 30
        proposed_end = proposed_start + timedelta(minutes=duration)

        tz_row = await db.execute(text("SELECT timezone FROM users WHERE id = :id"), {"id": user_id})
        proposer_tz = (tz_row.scalar() or None)
        human = _human_time(proposed_start, proposer_tz)

        await db.execute(
            text("""
                INSERT INTO session_messages (id, session_id, sender_user_id, sender_type, content, message_type, metadata, created_at)
                VALUES (:id, :session_id, :sender_user_id, 'AGENT', :content, 'PROPOSE', CAST(:metadata AS jsonb), :now)
            """),
            {
                "id": msg_id, "session_id": session_id, "sender_user_id": user_id,
                "content": f"Proposing {human}. {reasoning}",
                "metadata": json.dumps(metadata), "now": now,
            },
        )
        await db.execute(
            text("""
                UPDATE scheduling_sessions
                SET status = 'PROPOSED', proposed_start = :start, proposed_end = :end, updated_at = :now
                WHERE id = :session_id
            """),
            {"start": proposed_start, "end": proposed_end, "now": now, "session_id": session_id},
        )
        await db.commit()

    await _broadcast({
        "type": "PROPOSAL", "session_id": session_id,
        "proposed_start": proposed_start.isoformat(), "proposed_end": proposed_end.isoformat(),
    })
    return {"status": "proposed", "proposed_start": proposed_start.isoformat(), "proposed_end": proposed_end.isoformat()}


async def accept_proposal(session_id: str) -> dict:
    """Signals (as YOUR agent) that the currently proposed time works for your user.
    This posts an ACCEPT message to the thread; the human still gives final approval in the app."""
    user_id = caller_id()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        if not await _is_participant(db, session_id, user_id):
            return {"error": "You are not a participant in this session."}
        await db.execute(
            text("""
                INSERT INTO session_messages (id, session_id, sender_user_id, sender_type, content, message_type, created_at)
                VALUES (gen_random_uuid(), :session_id, :user_id, 'AGENT', :content, 'ACCEPT', :now)
            """),
            {"session_id": session_id, "user_id": user_id, "content": "Accepts the proposed time.", "now": now},
        )
        await db.commit()

    await _broadcast({"type": "MESSAGE", "session_id": session_id, "message": {
        "sender_user_id": user_id, "sender_type": "AGENT",
        "content": "Accepts the proposed time.", "message_type": "ACCEPT",
        "created_at": now.isoformat(),
    }})
    return {"status": "accepted"}


async def reject_proposal(session_id: str, reason: str) -> dict:
    """Signals (as YOUR agent) that the proposed time does not work, with a reason.
    This reopens negotiation (status RE_NEGOTIATING) and posts a REJECT message to the thread."""
    user_id = caller_id()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        if not await _is_participant(db, session_id, user_id):
            return {"error": "You are not a participant in this session."}
        await db.execute(
            text("UPDATE scheduling_sessions SET status = 'RE_NEGOTIATING', proposed_start = NULL, proposed_end = NULL, updated_at = :now WHERE id = :session_id"),
            {"now": now, "session_id": session_id},
        )
        await db.execute(
            text("""
                INSERT INTO session_messages (id, session_id, sender_user_id, sender_type, content, message_type, created_at)
                VALUES (gen_random_uuid(), :session_id, :user_id, 'AGENT', :content, 'REJECT', :now)
            """),
            {"session_id": session_id, "user_id": user_id, "content": f"Rejects the proposed time: {reason}", "now": now},
        )
        await db.commit()

    await _broadcast({"type": "MESSAGE", "session_id": session_id, "message": {
        "sender_user_id": user_id, "sender_type": "AGENT",
        "content": f"Rejects the proposed time: {reason}", "message_type": "REJECT",
        "created_at": now.isoformat(),
    }})
    return {"status": "rejected", "reason": reason}
