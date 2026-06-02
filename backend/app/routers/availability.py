from datetime import time
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_user
from app.schemas.models import AvailabilityEntry, AvailabilityResponse

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("", response_model=AvailabilityResponse)
async def get_availability(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT day_of_week, start_time, end_time, is_available FROM availability WHERE user_id = :uid ORDER BY day_of_week"),
        {"uid": str(current_user["id"])},
    )
    rows = result.mappings().all()
    return AvailabilityResponse(
        availability=[
            AvailabilityEntry(
                day_of_week=r["day_of_week"],
                start_time=str(r["start_time"]),
                end_time=str(r["end_time"]),
                is_available=r["is_available"],
            )
            for r in rows
        ]
    )


@router.put("", response_model=AvailabilityResponse)
async def set_availability(
    body: AvailabilityResponse,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = str(current_user["id"])
    for entry in body.availability:
        start = time.fromisoformat(entry.start_time)
        end = time.fromisoformat(entry.end_time)
        await db.execute(
            text("""
                INSERT INTO availability (id, user_id, day_of_week, start_time, end_time, is_available)
                VALUES (gen_random_uuid(), :uid, :dow, :start, :end, :avail)
                ON CONFLICT (user_id, day_of_week)
                DO UPDATE SET start_time = :start, end_time = :end, is_available = :avail
            """),
            {"uid": uid, "dow": entry.day_of_week, "start": start, "end": end, "avail": entry.is_available},
        )
    await db.commit()
    return await get_availability(current_user=current_user, db=db)
