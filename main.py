"""
Interview Video Analyzer — FastAPI Server
Handles video uploads, runs the analysis pipeline, and serves the frontend.
"""

import os
import uuid
import shutil
import threading
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

import analyzer

load_dotenv()

# Ensure upload directory exists
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# In-memory store for job progress and results
jobs: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    print("=" * 60)
    print("  Interview Video Analyzer")
    print("  Server running at http://localhost:8000")
    print("=" * 60)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_free_api_key_here":
        print("\n  ⚠️  WARNING: GEMINI_API_KEY not set!")
        print("  Copy .env.example to .env and add your free API key.")
        print("  Get one at: https://aistudio.google.com/apikey\n")
    else:
        print(f"\n  ✅ Gemini API key configured (ends in ...{api_key[-4:]})")

    whisper_model = os.getenv("WHISPER_MODEL", "base")
    print(f"  📝 Whisper model: {whisper_model}")
    print(f"  📁 Upload directory: {UPLOAD_DIR.resolve()}\n")

    yield

    # Cleanup uploads on shutdown
    if UPLOAD_DIR.exists():
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)


app = FastAPI(
    title="Interview Video Analyzer",
    description="Analyze coding interview recordings with AI-powered feedback",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pipeline runner (background thread) ─────────────────────

def run_pipeline_in_background(job_id: str, video_path: str):
    """Run the full analysis pipeline in a background thread."""

    def progress_callback(stage, detail, pct):
        jobs[job_id]["stage"] = stage
        jobs[job_id]["detail"] = detail
        if pct >= 0:
            jobs[job_id]["pct"] = pct

    analyzer.set_progress_callback(progress_callback)

    try:
        jobs[job_id]["status"] = "running"
        result = analyzer.run_full_pipeline(video_path)
        jobs[job_id]["status"] = "complete"
        jobs[job_id]["result"] = result
        jobs[job_id]["stage"] = "complete"
        jobs[job_id]["detail"] = "Analysis complete!"
        jobs[job_id]["pct"] = 100

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        jobs[job_id]["stage"] = "error"
        jobs[job_id]["detail"] = str(e)
        print(f"[ERROR] Pipeline failed for job {job_id}: {e}")

    finally:
        # Clean up uploaded file
        try:
            Path(video_path).unlink(missing_ok=True)
        except Exception:
            pass
        analyzer.set_progress_callback(None)


# ─── Endpoints ────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload a video file and start analysis."""
    # Validate file type
    allowed_types = [
        "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo",
        "video/x-matroska", "video/mpeg", "video/ogg",
    ]

    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Please upload a video file."
        )

    # Save file locally
    job_id = str(uuid.uuid4())[:8]
    ext = Path(file.filename).suffix or ".mp4"
    local_path = UPLOAD_DIR / f"{job_id}{ext}"

    try:
        with open(local_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        file_size_mb = local_path.stat().st_size / (1024 * 1024)
        print(f"[Server] File saved: {local_path} ({file_size_mb:.1f} MB)")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Create job and start pipeline in background
    jobs[job_id] = {
        "status": "starting",
        "filename": file.filename,
        "size_mb": round(file_size_mb, 1),
        "stage": "upload",
        "detail": "File uploaded, starting pipeline...",
        "pct": 0,
        "result": None,
        "error": None,
    }

    thread = threading.Thread(
        target=run_pipeline_in_background,
        args=(job_id, str(local_path)),
        daemon=True,
    )
    thread.start()

    return JSONResponse({
        "job_id": job_id,
        "filename": file.filename,
        "size_mb": round(file_size_mb, 1),
        "message": "Upload complete. Analysis started.",
    })


@app.get("/api/progress/{job_id}")
async def get_progress(job_id: str):
    """Poll for job progress."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    job = jobs[job_id]
    response = {
        "job_id": job_id,
        "status": job["status"],
        "stage": job["stage"],
        "detail": job["detail"],
        "pct": job.get("pct", 0),
        "filename": job["filename"],
    }

    if job["status"] == "complete":
        response["result"] = job["result"]
    elif job["status"] == "error":
        response["error"] = job["error"]

    return JSONResponse(response)


# ─── Static files & frontend ─────────────────────────────────

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_frontend():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"message": "API running. Frontend not found."})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
