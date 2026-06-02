from datetime import datetime, time
from typing import Optional
from pydantic import BaseModel, EmailStr


# --- Auth ---

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    username: str
    timezone: str


class SigninRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    timezone: str


# --- Users ---

class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    username: str
    timezone: str


class UserPublic(BaseModel):
    id: str
    name: str
    username: str
    timezone: str


# --- Availability ---

class AvailabilityEntry(BaseModel):
    day_of_week: int  # 0=Monday, 6=Sunday
    start_time: str   # "HH:MM"
    end_time: str
    is_available: bool = True


class AvailabilityResponse(BaseModel):
    availability: list[AvailabilityEntry]


# --- Sessions ---

class SessionCreateRequest(BaseModel):
    purpose: Optional[str] = None
    duration_minutes: int = 30
    participant_usernames: list[str]  # ["@bob", "@alice"]


class ParticipantInfo(BaseModel):
    user_id: str
    username: str
    name: str
    role: str
    approval_status: str
    rejection_reason: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    sender_user_id: str
    username: str
    name: str
    sender_type: str
    content: str
    message_type: str
    metadata: Optional[dict] = None
    created_at: str


class SessionResponse(BaseModel):
    id: str
    initiated_by: str
    purpose: Optional[str]
    duration_minutes: Optional[int]
    status: str
    proposed_start: Optional[str]
    proposed_end: Optional[str]
    escalation_reason: Optional[str]
    created_at: str
    updated_at: str
    participants: list[ParticipantInfo] = []


class SessionDetailResponse(SessionResponse):
    messages: list[MessageResponse] = []


class ApprovalRequest(BaseModel):
    pass


class RejectionRequest(BaseModel):
    reason: str


# --- Bookings ---

class BookingParticipantInfo(BaseModel):
    user_id: str
    username: str
    name: str


class BookingResponse(BaseModel):
    id: str
    session_id: str
    title: str
    start_time: str
    end_time: str
    status: str
    created_at: str
    participants: list[BookingParticipantInfo] = []


# --- Internal broadcast ---

class BroadcastPayload(BaseModel):
    type: str
    session_id: Optional[str] = None
    model_config = {"extra": "allow"}
