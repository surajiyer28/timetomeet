"""Single source of truth for the human-gated parts of a session's lifecycle:
recording approvals/rejections and creating the confirmed booking.

Both the REST routes and the WebSocket handlers delegate here so the behaviour is
identical regardless of how the action arrives.
"""
import uuid
import asyncio
from datetime import datetime, timezone
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.websocket.manager import manager


async def _participant_ids(db, session_id: str) -> list[str]:
    rows = await db.execute(
        text("SELECT user_id FROM session_participants WHERE session_id = :sid"),
        {"sid": session_id},
    )
    return [str(r["user_id"]) for r in rows.mappings()]


async def _create_calendar_events(booking_id, title, start, end, email_rows) -> None:
    """Best-effort: create a Google Calendar event on each connected participant's calendar,
    inviting the others. Stores the first created event id on the booking. No-op if Google is
    unconfigured or nobody connected — the DB booking is still the source of truth."""
    from app.config import settings
    if not settings.google_enabled:
        return
    from app import google_calendar as gcal

    invite_emails = [r["google_email"] or r["email"] for r in email_rows]
    first_event_id = None
    for r in email_rows:
        if not r["google_email"]:
            continue  # this participant hasn't connected Google
        others = [e for e in invite_emails if e and e != (r["google_email"] or r["email"])]
        event_id = await gcal.create_event(str(r["id"]), title, start, end, others)
        first_event_id = first_event_id or event_id

    if first_event_id:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE bookings SET calendar_event_id = :eid WHERE id = :bid"),
                {"eid": first_event_id, "bid": booking_id},
            )
            await db.commit()


async def create_meeting(
    initiator_id: str,
    participant_usernames: list[str],
    purpose: str | None,
    duration_minutes: int = 30,
    timing_note: str | None = None,
) -> dict:
    """Create a scheduling session initiated by `initiator_id`, then kick off the agent
    negotiation. Returns {session_id, participants, unknown}. Used by the home agent and REST."""
    now = datetime.now(timezone.utc)
    resolved: list[dict] = []
    unknown: list[str] = []

    async with AsyncSessionLocal() as db:
        for raw in participant_usernames:
            uname = raw.lstrip("@").strip()
            if not uname:
                continue
            row = (await db.execute(
                text("SELECT id, username, name FROM users WHERE username = :u"),
                {"u": uname},
            )).mappings().first()
            if row and str(row["id"]) != initiator_id:
                resolved.append(dict(row))
            elif not row:
                unknown.append(uname)

        if not resolved:
            return {"error": "No valid participants found", "unknown": unknown}

        session_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO scheduling_sessions (id, initiated_by, purpose, duration_minutes, timing_note, status, created_at, updated_at)
                VALUES (:id, :by, :purpose, :dur, :timing, 'NEGOTIATING', :now, :now)
            """),
            {"id": session_id, "by": initiator_id, "purpose": purpose, "dur": duration_minutes,
             "timing": timing_note, "now": now},
        )
        await db.execute(
            text("""
                INSERT INTO session_participants (id, session_id, user_id, role, approval_status)
                VALUES (gen_random_uuid(), :sid, :uid, 'INITIATOR', 'PENDING')
            """),
            {"sid": session_id, "uid": initiator_id},
        )
        for p in resolved:
            await db.execute(
                text("""
                    INSERT INTO session_participants (id, session_id, user_id, role, approval_status)
                    VALUES (gen_random_uuid(), :sid, :uid, 'PARTICIPANT', 'PENDING')
                    ON CONFLICT (session_id, user_id) DO NOTHING
                """),
                {"sid": session_id, "uid": str(p["id"])},
            )
        await db.commit()
        participant_ids = await _participant_ids(db, session_id)

    await manager.broadcast_to_users(participant_ids, {
        "type": "SESSION_CREATED",
        "session_id": session_id,
        "purpose": purpose,
        "participants": [{"username": p["username"], "name": p["name"]} for p in resolved],
    })

    from app.agents.orchestrator import run_negotiation
    asyncio.create_task(run_negotiation(session_id))

    return {
        "session_id": session_id,
        "participants": [p["username"] for p in resolved],
        "unknown": unknown,
    }


async def cancel_meeting(user_id: str, session_id: str) -> dict:
    """Cancel a session (and its booking, if any). Caller must be a participant."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        is_part = (await db.execute(
            text("SELECT 1 FROM session_participants WHERE session_id = :sid AND user_id = :uid"),
            {"sid": session_id, "uid": user_id},
        )).first()
        if not is_part:
            return {"error": "You are not a participant in that meeting."}
        await db.execute(
            text("UPDATE scheduling_sessions SET status = 'CANCELLED', updated_at = :now WHERE id = :sid"),
            {"now": now, "sid": session_id},
        )
        await db.execute(
            text("UPDATE bookings SET status = 'CANCELLED' WHERE session_id = :sid"),
            {"sid": session_id},
        )
        participant_ids = await _participant_ids(db, session_id)
        await db.commit()

    await manager.broadcast_to_users(participant_ids, {
        "type": "CANCELLED", "session_id": session_id,
    })
    return {"status": "cancelled", "session_id": session_id}


async def list_my_activity(user_id: str) -> dict:
    """Active sessions and upcoming confirmed bookings for a user (for 'what's on my calendar')."""
    async with AsyncSessionLocal() as db:
        sessions = (await db.execute(
            text("""
                SELECT ss.id, ss.purpose, ss.status, ss.proposed_start,
                       array_agg(u.username) AS usernames
                FROM scheduling_sessions ss
                JOIN session_participants sp  ON sp.session_id = ss.id
                JOIN session_participants spa ON spa.session_id = ss.id
                JOIN users u ON u.id = spa.user_id
                WHERE sp.user_id = :uid AND ss.status NOT IN ('CANCELLED','CONFIRMED','EXPIRED')
                GROUP BY ss.id, ss.purpose, ss.status, ss.proposed_start
                ORDER BY ss.created_at DESC
            """),
            {"uid": user_id},
        )).mappings().all()
        bookings = (await db.execute(
            text("""
                SELECT b.title, b.start_time, b.end_time,
                       array_agg(u.username) AS usernames
                FROM bookings b
                JOIN booking_participants bp  ON bp.booking_id = b.id
                JOIN booking_participants bpa ON bpa.booking_id = b.id
                JOIN users u ON u.id = bpa.user_id
                WHERE bp.user_id = :uid AND b.status = 'CONFIRMED'
                GROUP BY b.id, b.title, b.start_time, b.end_time
                ORDER BY b.start_time ASC
            """),
            {"uid": user_id},
        )).mappings().all()

    return {
        "active_negotiations": [
            {"session_id": str(s["id"]), "purpose": s["purpose"], "status": s["status"],
             "with": [u for u in s["usernames"]],
             "proposed_start": s["proposed_start"].isoformat() if s["proposed_start"] else None}
            for s in sessions
        ],
        "upcoming_meetings": [
            {"title": b["title"], "start": b["start_time"].isoformat(),
             "end": b["end_time"].isoformat(), "with": [u for u in b["usernames"]]}
            for b in bookings
        ],
    }


async def confirm_and_book(session_id: str) -> str | None:
    """Create the confirmed booking for a fully-approved session (idempotent)."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            text("SELECT id FROM bookings WHERE session_id = :sid AND status = 'CONFIRMED'"),
            {"sid": session_id},
        )
        if existing.first():
            return None  # already booked

        sess = (await db.execute(
            text("SELECT purpose, proposed_start, proposed_end FROM scheduling_sessions WHERE id = :id"),
            {"id": session_id},
        )).mappings().first()
        if not sess or not sess["proposed_start"]:
            return None

        booking_id = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO bookings (id, session_id, title, start_time, end_time, status, created_at)
                VALUES (:id, :sid, :title, :start, :end, 'CONFIRMED', :now)
            """),
            {"id": booking_id, "sid": session_id, "title": sess["purpose"] or "Meeting",
             "start": sess["proposed_start"], "end": sess["proposed_end"], "now": now},
        )
        participant_ids = await _participant_ids(db, session_id)
        for uid in participant_ids:
            await db.execute(
                text("INSERT INTO booking_participants (id, booking_id, user_id) VALUES (gen_random_uuid(), :bid, :uid)"),
                {"bid": booking_id, "uid": uid},
            )
        await db.execute(
            text("UPDATE scheduling_sessions SET status = 'CONFIRMED', updated_at = :now WHERE id = :id"),
            {"now": now, "id": session_id},
        )
        # Emails for calendar invites: prefer the connected Google address, else the account email.
        email_rows = (await db.execute(
            text("""
                SELECT u.id, u.email, g.google_email
                FROM users u LEFT JOIN google_tokens g ON g.user_id = u.id
                WHERE u.id = ANY(:ids)
            """),
            {"ids": participant_ids},
        )).mappings().all()
        await db.commit()

    # Write a real Google Calendar event on each connected participant's calendar (best effort).
    await _create_calendar_events(
        booking_id, sess["purpose"] or "Meeting",
        sess["proposed_start"], sess["proposed_end"], email_rows,
    )

    await manager.broadcast_to_users(participant_ids, {
        "type": "CONFIRMED", "session_id": session_id, "booking_id": booking_id,
    })
    from app.services.chat import post_trace_to_participants
    await post_trace_to_participants(session_id, "All set — the meeting is on the calendar.")
    from app.email import send_booking_confirmed
    await send_booking_confirmed(booking_id)
    return booking_id


async def record_approval(user_id: str, session_id: str) -> dict:
    """Mark a participant approved; if all have approved, confirm and book."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE session_participants SET approval_status = 'APPROVED' WHERE session_id = :sid AND user_id = :uid"),
            {"sid": session_id, "uid": user_id},
        )
        counts = (await db.execute(
            text("""
                SELECT COUNT(*) FILTER (WHERE approval_status = 'APPROVED') AS approved, COUNT(*) AS total
                FROM session_participants WHERE session_id = :sid
            """),
            {"sid": session_id},
        )).mappings().first()
        all_approved = counts["approved"] == counts["total"]
        participant_ids = await _participant_ids(db, session_id)
        await db.commit()

    await manager.broadcast_to_users(participant_ids, {
        "type": "APPROVAL_UPDATE", "session_id": session_id, "user_id": user_id, "status": "APPROVED",
    })

    booking_id = None
    if all_approved:
        booking_id = await confirm_and_book(session_id)
    return {"all_approved": all_approved, "booking_id": booking_id}


async def record_rejection(user_id: str, session_id: str, reason: str, rejected_by_name: str) -> dict:
    """Mark a participant's rejection, reopen negotiation, notify, and restart the agents."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE session_participants SET approval_status = 'REJECTED', rejection_reason = :reason WHERE session_id = :sid AND user_id = :uid"),
            {"sid": session_id, "uid": user_id, "reason": reason},
        )
        await db.execute(
            text("UPDATE session_participants SET approval_status = 'PENDING', rejection_reason = NULL WHERE session_id = :sid AND user_id != :uid"),
            {"sid": session_id, "uid": user_id},
        )
        await db.execute(
            text("UPDATE scheduling_sessions SET status = 'RE_NEGOTIATING', proposed_start = NULL, proposed_end = NULL, updated_at = :now WHERE id = :sid"),
            {"now": now, "sid": session_id},
        )
        await db.execute(
            text("""
                INSERT INTO session_messages (id, session_id, sender_user_id, sender_type, content, message_type, created_at)
                VALUES (gen_random_uuid(), :sid, :uid, 'USER', :content, 'REJECT', :now)
            """),
            {"sid": session_id, "uid": user_id, "content": f"Rejected: {reason}", "now": now},
        )
        participant_ids = await _participant_ids(db, session_id)
        await db.commit()

    await manager.broadcast_to_users(participant_ids, {
        "type": "RE_NEGOTIATING", "session_id": session_id, "rejected_by": user_id, "reason": reason,
    })
    from app.services.chat import post_trace_to_participants
    await post_trace_to_participants(session_id, "That time didn't work out — I'm looking for another option.")
    from app.email import send_rejection_notice
    await send_rejection_notice(session_id, rejected_by_name)

    from app.agents.orchestrator import run_negotiation
    asyncio.create_task(run_negotiation(session_id))
    return {"status": "rejected"}
