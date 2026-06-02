from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_user
from app.schemas.models import BookingResponse, BookingParticipantInfo

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("", response_model=list[BookingResponse])
async def get_bookings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = str(current_user["id"])
    result = await db.execute(
        text("""
            SELECT b.id, b.session_id, b.title, b.start_time, b.end_time, b.status, b.created_at
            FROM bookings b
            JOIN booking_participants bp ON bp.booking_id = b.id
            WHERE bp.user_id = :uid AND b.status = 'CONFIRMED'
            ORDER BY b.start_time ASC
        """),
        {"uid": uid},
    )
    bookings = []
    for row in result.mappings():
        parts_result = await db.execute(
            text("""
                SELECT u.id, u.username, u.name
                FROM booking_participants bp
                JOIN users u ON u.id = bp.user_id
                WHERE bp.booking_id = :bid
            """),
            {"bid": str(row["id"])},
        )
        participants = [
            BookingParticipantInfo(user_id=str(p["id"]), username=p["username"], name=p["name"])
            for p in parts_result.mappings()
        ]
        bookings.append(BookingResponse(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            title=row["title"],
            start_time=row["start_time"].isoformat(),
            end_time=row["end_time"].isoformat(),
            status=row["status"],
            created_at=row["created_at"].isoformat(),
            participants=participants,
        ))
    return bookings
