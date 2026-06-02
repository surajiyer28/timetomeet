from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth import get_current_user
from app.schemas.models import (
    SessionCreateRequest, SessionResponse, SessionDetailResponse,
    ParticipantInfo, MessageResponse, RejectionRequest,
)
from app.websocket.manager import manager
from app.services.session_lifecycle import record_approval, record_rejection, create_meeting

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _get_session_participants(session_id: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT sp.user_id, sp.role, sp.approval_status, sp.rejection_reason,
                   u.username, u.name
            FROM session_participants sp
            JOIN users u ON u.id = sp.user_id
            WHERE sp.session_id = :sid
        """),
        {"sid": session_id},
    )
    return [dict(r) for r in result.mappings()]


async def _build_session_response(row: dict, db: AsyncSession) -> SessionResponse:
    participants = await _get_session_participants(str(row["id"]), db)
    return SessionResponse(
        id=str(row["id"]),
        initiated_by=str(row["initiated_by"]),
        purpose=row["purpose"],
        duration_minutes=row["duration_minutes"],
        status=row["status"],
        proposed_start=row["proposed_start"].isoformat() if row["proposed_start"] else None,
        proposed_end=row["proposed_end"].isoformat() if row["proposed_end"] else None,
        escalation_reason=row["escalation_reason"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
        participants=[
            ParticipantInfo(
                user_id=str(p["user_id"]),
                username=p["username"],
                name=p["name"],
                role=p["role"],
                approval_status=p["approval_status"],
                rejection_reason=p["rejection_reason"],
            )
            for p in participants
        ],
    )


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: SessionCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.participant_usernames:
        raise HTTPException(status_code=400, detail="At least one participant required")

    result = await create_meeting(
        initiator_id=str(current_user["id"]),
        participant_usernames=body.participant_usernames,
        purpose=body.purpose,
        duration_minutes=body.duration_minutes,
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    sess_row = dict((await db.execute(
        text("SELECT * FROM scheduling_sessions WHERE id = :id"),
        {"id": result["session_id"]},
    )).mappings().first())
    return await _build_session_response(sess_row, db)


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = str(current_user["id"])
    result = await db.execute(
        text("""
            SELECT ss.* FROM scheduling_sessions ss
            JOIN session_participants sp ON sp.session_id = ss.id
            WHERE sp.user_id = :uid
            ORDER BY ss.created_at DESC
        """),
        {"uid": uid},
    )
    sessions = []
    for row in result.mappings():
        sessions.append(await _build_session_response(dict(row), db))
    return sessions


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = str(current_user["id"])
    # Verify user is a participant
    check = await db.execute(
        text("SELECT 1 FROM session_participants WHERE session_id = :sid AND user_id = :uid"),
        {"sid": session_id, "uid": uid},
    )
    if not check.first():
        raise HTTPException(status_code=403, detail="Not a participant in this session")

    sess_result = await db.execute(
        text("SELECT * FROM scheduling_sessions WHERE id = :id"),
        {"id": session_id},
    )
    row = sess_result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    base = await _build_session_response(dict(row), db)

    # Load messages
    msgs_result = await db.execute(
        text("""
            SELECT sm.id, sm.sender_user_id, u.username, u.name,
                   sm.sender_type, sm.content, sm.message_type, sm.metadata, sm.created_at
            FROM session_messages sm
            JOIN users u ON u.id = sm.sender_user_id
            WHERE sm.session_id = :sid
            ORDER BY sm.created_at ASC
        """),
        {"sid": session_id},
    )
    messages = [
        MessageResponse(
            id=str(r["id"]),
            sender_user_id=str(r["sender_user_id"]),
            username=r["username"],
            name=r["name"],
            sender_type=r["sender_type"],
            content=r["content"],
            message_type=r["message_type"],
            metadata=r["metadata"],
            created_at=r["created_at"].isoformat(),
        )
        for r in msgs_result.mappings()
    ]

    return SessionDetailResponse(**base.model_dump(), messages=messages)


@router.post("/{session_id}/approve", response_model=dict)
async def approve_session(
    session_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = str(current_user["id"])
    await _require_participant(session_id, uid, db)
    await _require_status(session_id, ["PROPOSED", "PENDING_APPROVAL"], db)

    result = await record_approval(uid, session_id)
    return {"status": "approved", **result}


@router.post("/{session_id}/reject", response_model=dict)
async def reject_session(
    session_id: str,
    body: RejectionRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = str(current_user["id"])
    await _require_participant(session_id, uid, db)
    await _require_status(session_id, ["PROPOSED", "PENDING_APPROVAL"], db)

    return await record_rejection(uid, session_id, body.reason, current_user["name"])


# --- Helpers ---

async def _require_participant(session_id: str, user_id: str, db: AsyncSession):
    check = await db.execute(
        text("SELECT 1 FROM session_participants WHERE session_id = :sid AND user_id = :uid"),
        {"sid": session_id, "uid": user_id},
    )
    if not check.first():
        raise HTTPException(status_code=403, detail="Not a participant in this session")


async def _require_status(session_id: str, allowed: list[str], db: AsyncSession):
    result = await db.execute(
        text("SELECT status FROM scheduling_sessions WHERE id = :id"),
        {"id": session_id},
    )
    row = result.mappings().first()
    if not row or row["status"] not in allowed:
        raise HTTPException(status_code=409, detail=f"Session is not in an approvable state (current: {row['status'] if row else 'not found'})")
