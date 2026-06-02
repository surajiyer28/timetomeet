import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    availability: Mapped[list["Availability"]] = relationship("Availability", back_populates="user", cascade="all, delete-orphan")
    agent_memories: Mapped[list["AgentMemory"]] = relationship("AgentMemory", back_populates="user", cascade="all, delete-orphan")
    session_participations: Mapped[list["SessionParticipant"]] = relationship("SessionParticipant", back_populates="user")
    booking_participations: Mapped[list["BookingParticipant"]] = relationship("BookingParticipant", back_populates="user")
