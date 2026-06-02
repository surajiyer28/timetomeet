import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.websocket.manager import manager

# Per-session locks to prevent concurrent orchestrator runs
_locks: dict[str, asyncio.Lock] = {}


def _lock(session_id: str) -> asyncio.Lock:
    if session_id not in _locks:
        _locks[session_id] = asyncio.Lock()
    return _locks[session_id]


async def run_negotiation(session_id: str) -> None:
    lock = _lock(session_id)
    if lock.locked():
        return
    async with lock:
        await _negotiate(session_id)


async def _negotiate(session_id: str) -> None:
    from app.agents.scheduling_agent import run_agent_turn

    # Normalize RE_NEGOTIATING → NEGOTIATING before starting
    async with AsyncSessionLocal() as db:
        sess = await _get_session(session_id, db)
        if not sess:
            return
        if sess["status"] in ("CONFIRMED", "CANCELLED", "EXPIRED"):
            return
        if sess["status"] in ("RE_NEGOTIATING", "INITIATED"):
            await db.execute(
                text("UPDATE scheduling_sessions SET status = 'NEGOTIATING', updated_at = :now WHERE id = :id"),
                {"now": datetime.now(timezone.utc), "id": session_id},
            )
            await db.commit()

        participants = await _get_participants(session_id, db)

    if not participants:
        return

    # Initiator always goes first, then round-robin
    ordered = sorted(participants, key=lambda p: 0 if p["role"] == "INITIATOR" else 1)
    max_turns = 10

    for turn in range(max_turns):
        current = ordered[turn % len(ordered)]
        user_id = str(current["user_id"])

        print(f"[orchestrator] session={session_id} turn={turn} agent=@{current['username']}")

        try:
            trace = await run_agent_turn(user_id, session_id)
        except Exception as e:
            print(f"[orchestrator] agent error: {e}")
            await _escalate(session_id, f"Agent encountered an error: {str(e)[:300]}")
            return

        # The agent's note goes ONLY to its own user (private — never the other participants).
        if trace:
            from app.services.chat import post_chat
            await post_chat(user_id, "agent", trace, session_id)

        # Reload session state after the agent turn
        async with AsyncSessionLocal() as db:
            sess = await _get_session(session_id, db)

        if not sess:
            return

        status = sess["status"]
        print(f"[orchestrator] session={session_id} status after turn={turn}: {status}")

        if status == "PROPOSED":
            await _notify_approval(session_id, sess, proposer_id=user_id)
            return

        if status == "ESCALATED":
            await _broadcast_escalation(session_id, sess.get("escalation_reason", ""))
            return

        if status in ("CONFIRMED", "CANCELLED", "EXPIRED"):
            return

        if status == "RE_NEGOTIATING":
            # User rejected mid-negotiation — exit and let the new run handle it
            return

    # Max turns exhausted without consensus
    await _escalate(
        session_id,
        "Agents could not agree on a time after 10 rounds. Please select a time manually or adjust your availability.",
    )


async def _get_session(session_id: str, db) -> dict | None:
    result = await db.execute(
        text("SELECT id, status, purpose, duration_minutes, proposed_start, proposed_end, escalation_reason FROM scheduling_sessions WHERE id = :id"),
        {"id": session_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _get_participants(session_id: str, db) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT sp.user_id, sp.role, u.username
            FROM session_participants sp
            JOIN users u ON u.id = sp.user_id
            WHERE sp.session_id = :sid
        """),
        {"sid": session_id},
    )
    return [dict(r) for r in result.mappings()]


async def _notify_approval(session_id: str, sess: dict, proposer_id: str | None = None) -> None:
    """Broadcast PROPOSAL event so each participant's stream shows the approval card, and give
    the participants who didn't propose a short heads-up from their own agent."""
    from app.email import send_approval_needed
    from app.services.chat import post_trace_to_participants

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT user_id FROM session_participants WHERE session_id = :sid"),
            {"sid": session_id},
        )
        participant_ids = [str(r["user_id"]) for r in result.mappings()]

    await manager.broadcast_to_users(participant_ids, {
        "type": "PROPOSAL",
        "session_id": session_id,
        "proposed_start": sess["proposed_start"].isoformat() if sess["proposed_start"] else None,
        "proposed_end": sess["proposed_end"].isoformat() if sess["proposed_end"] else None,
    })
    # The proposer already heard from their own agent this turn; tell everyone else.
    await post_trace_to_participants(
        session_id,
        "We've lined up a time that works — take a look below and approve if it suits you.",
        exclude_user_id=proposer_id,
    )
    await send_approval_needed(session_id)


async def _escalate(session_id: str, reason: str) -> None:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE scheduling_sessions SET status = 'ESCALATED', escalation_reason = :reason, updated_at = :now WHERE id = :id"),
            {"reason": reason, "now": now, "id": session_id},
        )
        result = await db.execute(
            text("""
                SELECT sp.user_id FROM session_participants sp
                WHERE sp.session_id = :sid AND sp.role = 'INITIATOR'
            """),
            {"sid": session_id},
        )
        initiator_row = result.mappings().first()
        all_result = await db.execute(
            text("SELECT user_id FROM session_participants WHERE session_id = :sid"),
            {"sid": session_id},
        )
        participant_ids = [str(r["user_id"]) for r in all_result.mappings()]
        await db.commit()

    await manager.broadcast_to_users(participant_ids, {
        "type": "ESCALATED",
        "session_id": session_id,
        "reason": reason,
    })
    from app.services.chat import post_trace_to_participants
    await post_trace_to_participants(
        session_id,
        "I couldn't find a time that works for everyone. You may want to adjust your availability and try again.",
    )
    from app.email import send_escalation_notice
    await send_escalation_notice(session_id)


async def _broadcast_escalation(session_id: str, reason: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT user_id FROM session_participants WHERE session_id = :sid"),
            {"sid": session_id},
        )
        participant_ids = [str(r["user_id"]) for r in result.mappings()]

    await manager.broadcast_to_users(participant_ids, {
        "type": "ESCALATED",
        "session_id": session_id,
        "reason": reason,
    })
