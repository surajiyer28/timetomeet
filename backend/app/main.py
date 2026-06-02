from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import auth, users, availability, sessions, bookings, feed
from app.websocket.router import router as ws_router
from app.websocket.manager import manager
from app.schemas.models import BroadcastPayload
from sqlalchemy import text
from app.database import AsyncSessionLocal

app = FastAPI(title="TimeToMeet API")

_allowed_origins = list({settings.frontend_url, "http://localhost:3000", "http://localhost:3001"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(availability.router)
app.include_router(sessions.router)
app.include_router(bookings.router)
app.include_router(feed.router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/internal/broadcast")
async def internal_broadcast(payload: BroadcastPayload):
    """Called by the MCP server to push WebSocket events to connected clients."""
    session_id = payload.session_id
    data = payload.model_dump()

    if session_id:
        # Look up participants and broadcast to all of them
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("SELECT user_id FROM session_participants WHERE session_id = :sid"),
                {"sid": session_id},
            )
            participant_ids = [str(r["user_id"]) for r in result.mappings()]
        await manager.broadcast_to_users(participant_ids, data)
    else:
        # Broadcast to all connected users (e.g. AGENT_VOICE targeted to one user)
        target_user = data.get("user_id")
        if target_user:
            await manager.broadcast_to_user(target_user, data)

    return {"status": "broadcast"}
