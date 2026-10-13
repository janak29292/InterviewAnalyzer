"""
Video Transcriber — FastAPI Application

Entrypoint for the backend server.
Equivalent to Django's asgi.py — creates the app and includes the router.

Run with:
    uvicorn main:app --host 0.0.0.0 --port 8002 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.urls import api_router
from core.config import UPLOAD_DIR, GENERATED_DIR, WHISPER_MODEL, PORT, DATA_DIR
from core.database import init_db, close_db
from core.websockets import manager

# ─── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    import workers.queue_manager as qm_module
    from workers.queue_manager import TranscriptionQueue

    # Ensure data directories exist
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize database (create tables)
    await init_db()

    # Initialize and start the transcription queue worker
    queue = TranscriptionQueue(ws_manager=manager)
    qm_module.queue_manager = queue
    queue.start()

    # ─── Crash Recovery ───────────────────────────────────────
    # Re-enqueue any sessions stuck in QUEUED or PROCESSING from a previous crash
    from pathlib import Path
    from sqlalchemy import select, update
    from core.database import AsyncSessionLocal
    from models.video import ProcessingState, VideoSession

    async with AsyncSessionLocal() as db:
        stuck = await db.execute(
            select(VideoSession)
            .where(VideoSession.state.in_([ProcessingState.QUEUED, ProcessingState.PROCESSING]))
            .order_by(VideoSession.created_at.asc())
        )
        orphaned = stuck.scalars().all()

        if orphaned:
            # Reset any PROCESSING sessions back to QUEUED
            await db.execute(
                update(VideoSession)
                .where(VideoSession.state == ProcessingState.PROCESSING)
                .values(state=ProcessingState.QUEUED)
            )
            await db.commit()

            for session in orphaned:
                ext = Path(session.filename).suffix or ".mp4"
                video_path = str(UPLOAD_DIR / f"{session.id}{ext}")
                queue.enqueue(session.id, video_path, session.filename)

            logger.info(f"♻️  Re-enqueued {len(orphaned)} orphaned session(s) from previous crash")

    # Startup banner
    print("=" * 60)
    print("  Video Transcriber")
    print(f"  Server running at http://localhost:{PORT}")
    print("=" * 60)
    print(f"\n  📝 Whisper model: {WHISPER_MODEL}")
    print(f"  📁 Data directory: {DATA_DIR.resolve()}")
    print(f"  📁 Upload directory: {UPLOAD_DIR.resolve()}")
    print(f"  📁 Generated directory: {GENERATED_DIR.resolve()}")
    print(f"  🔄 Queue worker: active")
    if orphaned:
        print(f"  ♻️  Recovered: {len(orphaned)} session(s) re-enqueued")
    print()

    yield

    # Shutdown
    await queue.stop()
    qm_module.queue_manager = None

    await close_db()
    logger.info("Database connections closed.")


# ─── App Factory ──────────────────────────────────────────────

app = FastAPI(
    title="Video Transcriber",
    description="Upload videos and generate transcripts with AI-powered transcription",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routes from urls.py (Django-style)
app.include_router(api_router)


# ─── Direct Run ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
