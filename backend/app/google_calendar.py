"""Per-user Google Calendar access (OAuth offline) over the Calendar REST API.

The backend owns all OAuth + token refresh; the MCP server asks the backend for free/busy via
an internal endpoint. Everything here degrades gracefully: if Google isn't configured, or a
user hasn't connected, callers fall back to the database-only behaviour.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import httpx
from sqlalchemy import text
from app.config import settings
from app.database import AsyncSessionLocal

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid", "email",
]


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",      # we need a refresh token
        "prompt": "consent",           # force refresh-token issuance every time
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange an auth code for tokens; returns {access_token, refresh_token, expiry, email, scopes}."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        tok = (await client.post(TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        })).json()
        if "access_token" not in tok:
            raise RuntimeError(f"Google token exchange failed: {tok}")
        email = ""
        try:
            info = (await client.get(USERINFO_URL, headers={"Authorization": f"Bearer {tok['access_token']}"})).json()
            email = info.get("email", "")
        except Exception:
            pass
    return {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expiry": datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600)),
        "scopes": tok.get("scope", ""),
        "email": email,
    }


async def store_tokens(user_id: str, t: dict) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                INSERT INTO google_tokens (user_id, google_email, access_token, refresh_token, expiry, scopes, updated_at)
                VALUES (:uid, :email, :at, :rt, :exp, :scopes, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    google_email = EXCLUDED.google_email,
                    access_token = EXCLUDED.access_token,
                    refresh_token = COALESCE(NULLIF(EXCLUDED.refresh_token, ''), google_tokens.refresh_token),
                    expiry = EXCLUDED.expiry, scopes = EXCLUDED.scopes, updated_at = now()
            """),
            {"uid": user_id, "email": t["email"], "at": t["access_token"],
             "rt": t["refresh_token"], "exp": t["expiry"], "scopes": t["scopes"]},
        )
        await db.commit()


async def connection_status(user_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT google_email FROM google_tokens WHERE user_id = :uid"), {"uid": user_id}
        )).mappings().first()
    return {"connected": bool(row), "email": row["google_email"] if row else None,
            "configured": settings.google_enabled}


async def disconnect(user_id: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM google_tokens WHERE user_id = :uid"), {"uid": user_id})
        await db.commit()


async def _valid_access_token(user_id: str) -> str | None:
    """Return a non-expired access token for the user, refreshing if needed; None if unconnected."""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT access_token, refresh_token, expiry FROM google_tokens WHERE user_id = :uid"),
            {"uid": user_id},
        )).mappings().first()
    if not row:
        return None
    if row["expiry"] > datetime.now(timezone.utc) + timedelta(seconds=60):
        return row["access_token"]
    # Refresh
    async with httpx.AsyncClient(timeout=15.0) as client:
        tok = (await client.post(TOKEN_URL, data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": row["refresh_token"],
            "grant_type": "refresh_token",
        })).json()
    if "access_token" not in tok:
        return None
    new_expiry = datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600))
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE google_tokens SET access_token = :at, expiry = :exp, updated_at = now() WHERE user_id = :uid"),
            {"at": tok["access_token"], "exp": new_expiry, "uid": user_id},
        )
        await db.commit()
    return tok["access_token"]


async def busy_intervals(user_id: str, time_min: datetime, time_max: datetime) -> list[tuple[datetime, datetime]] | None:
    """Real busy blocks from Google in [time_min, time_max]. None if unconnected/unavailable."""
    token = await _valid_access_token(user_id)
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = (await client.post(FREEBUSY_URL, headers={"Authorization": f"Bearer {token}"}, json={
                "timeMin": time_min.astimezone(timezone.utc).isoformat(),
                "timeMax": time_max.astimezone(timezone.utc).isoformat(),
                "items": [{"id": "primary"}],
            })).json()
        blocks = resp.get("calendars", {}).get("primary", {}).get("busy", [])
        out = []
        for b in blocks:
            out.append((datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                        datetime.fromisoformat(b["end"].replace("Z", "+00:00"))))
        return out
    except Exception:
        return None


async def create_event(user_id: str, summary: str, start: datetime, end: datetime,
                       attendee_emails: list[str]) -> str | None:
    """Create an event on the user's primary calendar; returns the event id, or None."""
    token = await _valid_access_token(user_id)
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = (await client.post(EVENTS_URL, headers={"Authorization": f"Bearer {token}"}, json={
                "summary": summary,
                "start": {"dateTime": start.astimezone(timezone.utc).isoformat()},
                "end": {"dateTime": end.astimezone(timezone.utc).isoformat()},
                "attendees": [{"email": e} for e in attendee_emails if e],
            })).json()
        return resp.get("id")
    except Exception:
        return None
