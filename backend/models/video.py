"""
SQLAlchemy 2.0 models for video processing sessions.
"""

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ProcessingState(enum.Enum):
    """States a video session can be in."""
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoSession(Base):
    """
    Tracks a single video upload and its processing lifecycle.

    Progress percentages are NOT stored here (avoids aggressive write locking).
    Only state transitions are persisted. Live progress is pushed via WebSocket.
    """
    __tablename__ = "video_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_mb: Mapped[Optional[float]] = mapped_column(nullable=True)
    state: Mapped[ProcessingState] = mapped_column(
        SQLEnum(ProcessingState, values_callable=lambda x: [e.value for e in x]),
        default=ProcessingState.UPLOADED,
        nullable=False,
    )
    transcript_file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<VideoSession id={self.id} state={self.state.value} file={self.filename}>"
