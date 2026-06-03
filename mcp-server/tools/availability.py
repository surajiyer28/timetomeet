from datetime import datetime, timedelta, date as date_type
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from sqlalchemy import text
from database import AsyncSessionLocal
from config import settings
from context import caller_id


async def _google_busy(user_id: str, day_start: datetime, day_end: datetime) -> list[tuple]:
    """Ask the backend for the user's real Google busy blocks for the day. Returns [] when the
    user hasn't connected Google or anything goes wrong — availability then stays DB-only."""
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(f"{settings.backend_url}/internal/freebusy", json={
                "user_id": user_id,
                "time_min": day_start.isoformat(),
                "time_max": day_end.isoformat(),
            })
        data = resp.json()
        if not data.get("connected"):
            return []
        return [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in data.get("busy", [])]
    except Exception:
        return []

# macOS / browser aliases not recognised by zoneinfo
_TZ_ALIASES = {
    "America/Indianapolis":     "America/Indiana/Indianapolis",
    "America/Louisville":       "America/Kentucky/Louisville",
    "America/Knox_IN":          "America/Indiana/Knox",
    "America/Fort_Wayne":       "America/Indiana/Indianapolis",
    "America/Shipshewana":      "America/Indiana/Indianapolis",
}

def _get_tz(name: str) -> ZoneInfo:
    name = _TZ_ALIASES.get(name, name)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


async def check_my_availability(date: str, duration_minutes: int) -> dict:
    """
    Returns YOUR free time slots on the given date (YYYY-MM-DD), filtered to your
    availability grid and excluding existing bookings. Slots are ISO 8601 strings in
    your local timezone. You can only ever see your own availability.
    """
    user_id = caller_id()
    async with AsyncSessionLocal() as db:
        # Get user timezone
        tz_result = await db.execute(
            text("SELECT timezone FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )
        tz_row = tz_result.mappings().first()
        if not tz_row:
            return {"error": "User not found"}

        user_tz = _get_tz(tz_row["timezone"])
        try:
            target_date = date_type.fromisoformat(date)
        except ValueError:
            return {"error": f"Invalid date '{date}'. Use YYYY-MM-DD format."}

        today = datetime.now(user_tz).date()
        if target_date < today:
            return {"date": date, "free_slots": [], "message": "That date is in the past."}

        day_of_week = target_date.weekday()  # 0=Monday, 6=Sunday

        # Get availability grid for this day
        avail_result = await db.execute(
            text("""
                SELECT start_time, end_time, is_available
                FROM availability
                WHERE user_id = :user_id AND day_of_week = :dow
            """),
            {"user_id": user_id, "dow": day_of_week},
        )
        avail = avail_result.mappings().first()
        if not avail or not avail["is_available"]:
            return {"date": date, "free_slots": [], "message": "Not available on this day"}

        # Get existing bookings for this date
        day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=user_tz)
        day_end = day_start + timedelta(days=1)

        bookings_result = await db.execute(
            text("""
                SELECT b.start_time, b.end_time
                FROM bookings b
                JOIN booking_participants bp ON bp.booking_id = b.id
                WHERE bp.user_id = :user_id
                  AND b.status = 'CONFIRMED'
                  AND b.start_time >= :day_start
                  AND b.start_time < :day_end
            """),
            {"user_id": user_id, "day_start": day_start, "day_end": day_end},
        )
        busy_blocks = [(r["start_time"], r["end_time"]) for r in bookings_result.mappings()]

        # Also subtract real Google Calendar busy blocks (best effort; degrades to DB-only).
        busy_blocks += await _google_busy(user_id, day_start, day_end)

        # Generate 30-minute slots within availability window
        slot_start = datetime.combine(target_date, avail["start_time"]).replace(tzinfo=user_tz)
        avail_end = datetime.combine(target_date, avail["end_time"]).replace(tzinfo=user_tz)
        slot_duration = timedelta(minutes=duration_minutes)
        step = timedelta(minutes=30)
        now = datetime.now(user_tz)  # don't offer slots that have already started today

        free_slots = []
        current = slot_start
        while current + slot_duration <= avail_end:
            slot_end = current + slot_duration
            overlaps = any(
                not (slot_end <= busy_start or current >= busy_end)
                for busy_start, busy_end in busy_blocks
            )
            if not overlaps and current >= now:
                free_slots.append(current.isoformat())
            current += step

        return {"date": date, "timezone": tz_row["timezone"], "free_slots": free_slots}
