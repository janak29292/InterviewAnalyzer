"""
Centralized configuration for the Interview Analyzer backend.
All paths and settings are resolved here, configurable via environment variables.
"""

import os
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────
# DATA_DIR resolves to <project_root>/data by default.
# In Docker, override with DATA_DIR=/app/data
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent

DATA_DIR = Path(os.getenv("DATA_DIR", str(_PROJECT_ROOT / "data")))
UPLOAD_DIR = DATA_DIR / "uploads"
GENERATED_DIR = DATA_DIR / "generated"

# ─── Database ─────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{DATA_DIR / 'interview_analyzer.db'}"
)

# ─── Whisper / ML ─────────────────────────────────────────────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")

# TODO: Make these configurable via env vars in the future
# WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "7"))
# WHISPER_TEMPERATURES = [0.0, 0.2, 0.4, 0.6]

# ─── Server ───────────────────────────────────────────────────
PORT = int(os.getenv("PORT", "8002"))

# ─── Allowed upload MIME types ────────────────────────────────
ALLOWED_VIDEO_TYPES = [
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/mpeg",
    "video/ogg",
]
