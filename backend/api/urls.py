"""
URL routing — Django-style route definitions.

All routes are registered via add_api_route() / add_api_websocket_route().
No @router.post decorators. Handlers live in services/views.py.
"""

from fastapi import APIRouter

from services.views import (
    upload_video,
    list_sessions,
    get_session_status,
    download_transcript,
    ws_progress,
)

api_router = APIRouter()

# ─── REST Endpoints ───────────────────────────────────────────
api_router.add_api_route(
    "/api/upload",
    upload_video,
    methods=["POST"],
    summary="Upload a video file and queue for transcription",
    tags=["Video"],
)

api_router.add_api_route(
    "/api/sessions",
    list_sessions,
    methods=["GET"],
    summary="List all recent sessions for the queue dashboard",
    tags=["Video"],
)

api_router.add_api_route(
    "/api/sessions/{session_id}",
    get_session_status,
    methods=["GET"],
    summary="Get current session state from database",
    tags=["Video"],
)

api_router.add_api_route(
    "/api/sessions/{session_id}/transcript",
    download_transcript,
    methods=["GET"],
    summary="Download the generated SRT transcript",
    tags=["Video"],
)

# ─── WebSocket Endpoint ──────────────────────────────────────
api_router.add_api_websocket_route(
    "/ws/{session_id}",
    ws_progress,
)
