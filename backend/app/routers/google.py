"""Google Calendar OAuth + connection management.

Browser-initiated endpoints carry the user's identity through Google's redirect via a short-
lived signed `state` token (the OAuth dance can't send our Authorization header back to us).
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from app.config import settings
from app.auth import get_current_user
from app import google_calendar as gcal

router = APIRouter(tags=["google"])


def _state_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "purpose": "google_oauth",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )


def _verify_state(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("purpose") != "google_oauth":
            raise ValueError
        return payload["sub"]
    except (JWTError, ValueError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")


@router.get("/auth/google/start")
async def google_start(token: str = Query(...)):
    """Begin the OAuth flow. `token` is the user's JWT (passed as a query param because this is
    a top-level browser navigation, not a fetch)."""
    if not settings.google_enabled:
        raise HTTPException(status_code=503, detail="Google Calendar is not configured on this server")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = payload["sub"]
    except (JWTError, KeyError):
        raise HTTPException(status_code=401, detail="Invalid token")
    return RedirectResponse(gcal.authorize_url(_state_token(user_id)))


@router.get("/auth/google/callback")
async def google_callback(code: str = Query(default=""), state: str = Query(default=""),
                          error: str = Query(default="")):
    dest = f"{settings.frontend_url}/dashboard"
    if error or not code or not state:
        return RedirectResponse(f"{dest}?google=error")
    user_id = _verify_state(state)
    try:
        tokens = await gcal.exchange_code(code)
        await gcal.store_tokens(user_id, tokens)
    except Exception:
        return RedirectResponse(f"{dest}?google=error")
    return RedirectResponse(f"{dest}?google=connected")


@router.get("/users/me/google")
async def google_status(current_user: dict = Depends(get_current_user)):
    return await gcal.connection_status(str(current_user["id"]))


@router.delete("/users/me/google")
async def google_disconnect(current_user: dict = Depends(get_current_user)):
    await gcal.disconnect(str(current_user["id"]))
    return {"status": "disconnected"}


class FreeBusyRequest(BaseModel):
    user_id: str
    time_min: str  # ISO 8601
    time_max: str


@router.post("/internal/freebusy")
async def internal_freebusy(body: FreeBusyRequest):
    """Used by the MCP server's check_my_availability to subtract real Google busy blocks.
    Returns {connected, busy:[[startISO,endISO],...]}; connected=false means fall back to DB-only."""
    blocks = await gcal.busy_intervals(
        body.user_id,
        datetime.fromisoformat(body.time_min.replace("Z", "+00:00")),
        datetime.fromisoformat(body.time_max.replace("Z", "+00:00")),
    )
    if blocks is None:
        return {"connected": False, "busy": []}
    return {"connected": True, "busy": [[s.isoformat(), e.isoformat()] for s, e in blocks]}
