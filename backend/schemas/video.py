"""
Pydantic schemas for request/response validation.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel


class UploadResponse(BaseModel):
    """Response after a successful video upload."""
    session_id: str
    filename: str
    size_mb: float
    message: str


class SessionStatusResponse(BaseModel):
    """Current state of a video session (fetched from DB)."""
    id: str
    filename: str
    state: str
    size_mb: Optional[float] = None
    transcript_file_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    """List of all recent sessions for the queue dashboard."""
    sessions: List[SessionStatusResponse]

