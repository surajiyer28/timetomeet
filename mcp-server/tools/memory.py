from datetime import datetime, timezone
from sqlalchemy import text
from database import AsyncSessionLocal
from context import caller_id


async def get_my_preferences() -> dict:
    """Returns all stored agent-memory entries for YOUR user (preferred times, style, etc.)."""
    user_id = caller_id()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT key, value, updated_at FROM agent_memory WHERE user_id = :user_id ORDER BY updated_at DESC"),
            {"user_id": user_id},
        )
        rows = result.mappings().all()
        return {"preferences": [{"key": r["key"], "value": r["value"], "updated_at": r["updated_at"].isoformat()} for r in rows]}


async def save_to_my_memory(key: str, value: str) -> dict:
    """Saves or updates a preference or learned fact in YOUR user's agent memory."""
    user_id = caller_id()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO agent_memory (id, user_id, key, value, updated_at)
                VALUES (gen_random_uuid(), :user_id, :key, :value, :now)
                ON CONFLICT (user_id, key) DO UPDATE SET value = :value, updated_at = :now
            """),
            {"user_id": user_id, "key": key, "value": value, "now": now},
        )
        await db.commit()
    return {"status": "saved", "key": key}
