from sqlalchemy import text
from database import AsyncSessionLocal
from context import caller_id


async def get_my_meeting_history(limit: int = 10) -> dict:
    """Returns YOUR recent confirmed bookings for context (most recent first)."""
    user_id = caller_id()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("""
                SELECT b.id, b.title, b.start_time, b.end_time, b.status,
                       array_agg(u.username) AS participants
                FROM bookings b
                JOIN booking_participants bp ON bp.booking_id = b.id
                JOIN booking_participants bp2 ON bp2.booking_id = b.id
                JOIN users u ON u.id = bp2.user_id
                WHERE bp.user_id = :user_id AND b.status = 'CONFIRMED'
                GROUP BY b.id, b.title, b.start_time, b.end_time, b.status
                ORDER BY b.start_time DESC
                LIMIT :limit
            """),
            {"user_id": user_id, "limit": limit},
        )
        meetings = [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "start_time": r["start_time"].isoformat(),
                "end_time": r["end_time"].isoformat(),
                "status": r["status"],
                "participants": r["participants"],
            }
            for r in result.mappings()
        ]
    return {"meetings": meetings}
