from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_user
from app.schemas.models import UserResponse, UserPublic

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    return UserResponse(**{k: str(v) for k, v in current_user.items()})


@router.get("/@{username}", response_model=UserPublic)
async def get_user_by_username(username: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, name, username, timezone FROM users WHERE username = :username"),
        {"username": username},
    )
    user = result.mappings().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserPublic(**{k: str(v) for k, v in user.items()})
