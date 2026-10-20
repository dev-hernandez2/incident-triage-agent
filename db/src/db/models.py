"""SQLAlchemy models shared across triage-agent services."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "ix_incidents_fingerprint_received",
            "fingerprint",
            unique=True,
            postgresql_where=text("status = 'received'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    fingerprint: Mapped[str] = mapped_column(Text)
    alertname: Mapped[str] = mapped_column(Text)
    labels: Mapped[dict[str, str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    tool: Mapped[str] = mapped_column(Text)
    args: Mapped[dict[str, object]] = mapped_column(JSONB)
    duration_ms: Mapped[int] = mapped_column(Integer)
    output_bytes: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
