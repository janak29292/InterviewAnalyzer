"""
View handlers — all business logic for API endpoints.

Pure functions, no routing decorators. Mapped to URLs in api/urls.py.
"""

import logging
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import ALLOWED_VIDEO_TYPES, UPLOAD_DIR, GENERATED_DIR
from core.dependencies import get_db_session
from core.websockets import manager
from models.video import ProcessingState, VideoSession
from schemas.video import UploadResponse, SessionStatusResponse, SessionListResponse
from workers.queue_manager import get_queue_manager

logger = logging.getLogger(__name__)


# ─── POST /api/upload ────────────────────────────────────────

async def upload_video(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
) -> UploadResponse:
    """Upload a video file, persist a DB record, and enqueue for transcription."""

    # Validate file type
    if file.content_type and file.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Please upload a video file.",
        )

    # Generate session ID and save file
    session_id = str(uuid.uuid4())[:8]
    ext = Path(file.filename).suffix or ".mp4"
    local_path = UPLOAD_DIR / f"{session_id}{ext}"

    try:
        content = await file.read()
        with open(local_path, "wb") as buffer:
            buffer.write(content)

        file_size_mb = local_path.stat().st_size / (1024 * 1024)
        logger.info(f"File saved: {local_path} ({file_size_mb:.1f} MB)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Create DB record with QUEUED state
    session = VideoSession(
        id=session_id,
        filename=file.filename,
        size_mb=round(file_size_mb, 1),
        state=ProcessingState.QUEUED,
    )
    db.add(session)
    await db.commit()

    # Enqueue for transcription (processed sequentially by queue worker)
    qm = get_queue_manager()
    qm.enqueue(session_id, str(local_path), file.filename)

    logger.info(f"Session {session_id} queued for transcription")

    return UploadResponse(
        session_id=session_id,
        filename=file.filename,
        size_mb=round(file_size_mb, 1),
        message="Upload complete. Queued for transcription.",
    )


# ─── GET /api/sessions ──────────────────────────────────────

async def list_sessions(
    db: AsyncSession = Depends(get_db_session),
) -> SessionListResponse:
    """Fetch all recent sessions for the queue dashboard."""

    stmt = (
        select(VideoSession)
        .order_by(VideoSession.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return SessionListResponse(
        sessions=[
            SessionStatusResponse(
                id=s.id,
                filename=s.filename,
                state=s.state.value,
                size_mb=s.size_mb,
                transcript_file_path=s.transcript_file_path,
                error_message=s.error_message,
                created_at=s.created_at,
            )
            for s in sessions
        ]
    )


# ─── GET /api/sessions/{session_id} ──────────────────────────

async def get_session_status(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> SessionStatusResponse:
    """Fetch current session state from database (for page load / refresh)."""

    stmt = select(VideoSession).where(VideoSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    return SessionStatusResponse(
        id=session.id,
        filename=session.filename,
        state=session.state.value,
        size_mb=session.size_mb,
        transcript_file_path=session.transcript_file_path,
        error_message=session.error_message,
        created_at=session.created_at,
    )


# ─── GET /api/sessions/{session_id}/transcript ───────────────

async def download_transcript(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    """Download the generated SRT file with the original video filename."""

    stmt = select(VideoSession).where(VideoSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    if session.state != ProcessingState.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Transcript not available. Session state: {session.state.value}",
        )

    if not session.transcript_file_path:
        raise HTTPException(status_code=404, detail="Transcript file path not set.")

    srt_path = GENERATED_DIR / session.transcript_file_path

    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="Transcript file not found on disk.")

    # Serve with original filename so user downloads as "my_interview.srt"
    original_stem = Path(session.filename).stem
    download_name = f"{original_stem}.srt"

    return FileResponse(
        path=str(srt_path),
        media_type="application/x-subrip",
        filename=download_name,
    )


# ─── WS /ws/{session_id} ─────────────────────────────────────

async def ws_progress(websocket: WebSocket, session_id: str) -> None:
    """
    WebSocket endpoint for real-time progress updates.

    The client connects here after uploading. The ConnectionManager
    broadcasts progress from the background pipeline thread.
    """
    await manager.connect(session_id, websocket)
    try:
        # Keep the connection alive — we only send, client just listens.
        # But we still need to read to detect disconnection.
        while True:
            # Wait for client messages (ping/pong or close).
            # If the client disconnects, this raises WebSocketDisconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)
        logger.info(f"WebSocket client disconnected for session {session_id}")
    except Exception:
        manager.disconnect(session_id, websocket)
