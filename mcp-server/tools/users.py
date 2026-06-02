from sqlalchemy import text
from database import AsyncSessionLocal


async def get_user_by_username(username: str) -> dict:
    """Looks up a user by their @handle. Returns id, name, username."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("SELECT id, name, username, timezone FROM users WHERE username = :username"),
            {"username": username.lstrip("@")},
        )
        row = result.mappings().first()
        if not row:
            return {"error": f"User @{username} not found"}
        return {"id": str(row["id"]), "name": row["name"], "username": row["username"], "timezone": row["timezone"]}
