import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import hash_password, verify_password, create_access_token
from app.schemas.models import SignupRequest, SigninRequest, TokenResponse

_TZ_ALIASES = {
    "America/Indianapolis":  "America/Indiana/Indianapolis",
    "America/Louisville":    "America/Kentucky/Louisville",
    "America/Knox_IN":       "America/Indiana/Knox",
    "America/Fort_Wayne":    "America/Indiana/Indianapolis",
}

def _normalize_tz(tz: str) -> str:
    return _TZ_ALIASES.get(tz, tz)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        text("SELECT id FROM users WHERE email = :email OR username = :username"),
        {"email": body.email, "username": body.username},
    )
    if existing.first():
        raise HTTPException(status_code=400, detail="Email or username already taken")

    user_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO users (id, email, password_hash, name, username, timezone)
            VALUES (:id, :email, :password_hash, :name, :username, :timezone)
        """),
        {
            "id": user_id,
            "email": body.email,
            "password_hash": hash_password(body.password),
            "name": body.name,
            "username": body.username,
            "timezone": _normalize_tz(body.timezone),
        },
    )
    await db.commit()
    token = create_access_token(user_id, body.username)
    return TokenResponse(access_token=token, user_id=user_id, username=body.username, timezone=_normalize_tz(body.timezone))


@router.post("/signin", response_model=TokenResponse)
async def signin(body: SigninRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        text("SELECT id, username, timezone, password_hash FROM users WHERE email = :email"),
        {"email": body.email},
    )
    user = result.mappings().first()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(str(user["id"]), user["username"])
    return TokenResponse(access_token=token, user_id=str(user["id"]), username=user["username"], timezone=user["timezone"])
