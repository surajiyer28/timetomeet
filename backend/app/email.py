from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib
from sqlalchemy import text
from app.config import settings
from app.database import AsyncSessionLocal


async def _send(to_addrs: list[str], subject: str, body_html: str) -> None:
    if not to_addrs:
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = "TimeToMeet <noreply@timetomeet.local>"
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(body_html, "html"))
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=False,
        )
    except Exception as e:
        print(f"[email] send failed: {e}")


async def _get_session_info(session_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        sess = await db.execute(
            text("SELECT purpose, proposed_start, proposed_end FROM scheduling_sessions WHERE id = :id"),
            {"id": session_id},
        )
        row = sess.mappings().first()
        parts = await db.execute(
            text("""
                SELECT u.email, u.name, sp.role
                FROM session_participants sp
                JOIN users u ON u.id = sp.user_id
                WHERE sp.session_id = :id
            """),
            {"id": session_id},
        )
        return {
            "session": dict(row) if row else {},
            "participants": [dict(p) for p in parts.mappings()],
        }


async def _get_booking_info(booking_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        booking = await db.execute(
            text("SELECT title, start_time, end_time FROM bookings WHERE id = :id"),
            {"id": booking_id},
        )
        row = booking.mappings().first()
        parts = await db.execute(
            text("""
                SELECT u.email, u.name
                FROM booking_participants bp
                JOIN users u ON u.id = bp.user_id
                WHERE bp.booking_id = :id
            """),
            {"id": booking_id},
        )
        return {
            "booking": dict(row) if row else {},
            "participants": [dict(p) for p in parts.mappings()],
        }


async def send_approval_needed(session_id: str) -> None:
    info = await _get_session_info(session_id)
    sess = info["session"]
    participants = info["participants"]
    emails = [p["email"] for p in participants]

    purpose = sess.get("purpose") or "Meeting"
    start = sess.get("proposed_start")
    time_str = start.strftime("%A, %B %-d at %-I:%M %p UTC") if start else "TBD"

    body = f"""
    <p>Your scheduling agents have agreed on a time for <strong>{purpose}</strong>.</p>
    <p><strong>Proposed time:</strong> {time_str}</p>
    <p>Open the app to approve or reject this time.</p>
    <p style="color:#666;font-size:12px">TimeToMeet</p>
    """
    await _send(emails, f"TimeToMeet: Approval needed — {purpose}", body)


async def send_booking_confirmed(booking_id: str) -> None:
    info = await _get_booking_info(booking_id)
    booking = info["booking"]
    participants = info["participants"]
    emails = [p["email"] for p in participants]
    names = ", ".join(p["name"] for p in participants)

    title = booking.get("title") or "Meeting"
    start = booking.get("start_time")
    time_str = start.strftime("%A, %B %-d at %-I:%M %p UTC") if start else "TBD"

    body = f"""
    <p>Your meeting has been confirmed!</p>
    <p><strong>{title}</strong><br>
    {time_str}<br>
    With: {names}</p>
    <p style="color:#666;font-size:12px">TimeToMeet</p>
    """
    await _send(emails, f"TimeToMeet: Meeting confirmed — {title}", body)


async def send_escalation_notice(session_id: str) -> None:
    info = await _get_session_info(session_id)
    sess = info["session"]
    # Only notify the initiator
    initiator = next((p for p in info["participants"] if p["role"] == "INITIATOR"), None)
    if not initiator:
        return

    purpose = sess.get("purpose") or "Meeting"
    body = f"""
    <p>Your scheduling agent needs your help.</p>
    <p>The agents couldn't agree on a time for <strong>{purpose}</strong> after several rounds.</p>
    <p>Open the app to select a time manually or adjust your availability.</p>
    <p style="color:#666;font-size:12px">TimeToMeet</p>
    """
    await _send([initiator["email"]], f"TimeToMeet: Agent needs help — {purpose}", body)


async def send_rejection_notice(session_id: str, rejected_by_name: str) -> None:
    info = await _get_session_info(session_id)
    sess = info["session"]
    participants = info["participants"]
    emails = [p["email"] for p in participants]

    purpose = sess.get("purpose") or "Meeting"
    body = f"""
    <p><strong>{rejected_by_name}</strong> rejected the proposed time for <strong>{purpose}</strong>.</p>
    <p>Your agents are re-negotiating. You'll be notified when a new time is proposed.</p>
    <p style="color:#666;font-size:12px">TimeToMeet</p>
    """
    await _send(emails, f"TimeToMeet: Re-negotiating — {purpose}", body)
