"""
Background pipeline worker for video transcription.

Migrated from legacy analyzer.py + transcribe.py.
Provides both sync (threaded) and async entry points.

The async version (run_pipeline_async) is used by the queue manager.
The sync version (run_pipeline) is kept for backward compatibility.
"""

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import GENERATED_DIR, WHISPER_MODEL
from core.database import AsyncSessionLocal
from core.websockets import ConnectionManager
from models.video import ProcessingState, VideoSession

logger = logging.getLogger(__name__)


# ─── Audio Extraction ────────────────────────────────────────

def extract_audio(video_path: str, audio_path: str) -> None:
    """Extract audio from video using FFmpeg subprocess."""
    logger.info(f"Extracting audio from: {Path(video_path).name}")

    command = [
        "ffmpeg",
        "-i", video_path,
        "-vn",                  # Strip video
        "-acodec", "pcm_s16le", # Uncompressed WAV
        "-ar", "16000",         # 16kHz sample rate required by Whisper
        "-ac", "1",             # Mono audio
        "-y",                   # Overwrite existing
        audio_path,
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        err_msg = result.stderr[-500:] if result.stderr else "Unknown error"
        raise RuntimeError(f"FFmpeg failed to extract audio:\n{err_msg}")

    logger.info("Audio extraction complete.")


# ─── SRT Formatting ──────────────────────────────────────────

def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS,mmm format for SRT."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisec = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisec:03d}"


# ─── CUDA Detection ──────────────────────────────────────────

def _has_cuda() -> bool:
    """Check if PyTorch has CUDA access for the WhisperModel."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ─── Transcription ────────────────────────────────────────────

def transcribe_audio(
    audio_path: str,
    output_srt: str,
    model_size: str,
    progress_cb: Optional[Callable] = None,
) -> None:
    """Run VAD + Faster-Whisper transcription and generate SRT file."""

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper is not installed. "
            "Run: pip install faster-whisper"
        )

    def _report(stage: str, detail: str, pct: int = -1) -> None:
        if progress_cb:
            progress_cb(stage, detail, pct)

    # Init model
    _report("transcribe", f"Loading Faster-Whisper model ({model_size})...", 0)
    logger.info(f"Loading Faster-Whisper model ({model_size})...")

    device = "cuda" if _has_cuda() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    logger.info(f"Using device: {device.upper()} with precision: {compute_type}")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    _report("transcribe", "Starting transcription with VAD filtering...", 10)
    logger.info("Starting transcription with strict VAD filtering...")
    start_time = time.time()

    # Transcribe with VAD and Hinglish prompt
    # TODO: Make beam_size, temperature, vad_parameters, and initial_prompt
    #       configurable via environment variables for different use cases.
    hinglish_prompt = (
        "Hello, kaise ho aap? Let's start the interview. "
        "Aaj hum system design discuss karenge. Okay, theek hai, perfect."
    )

    segments, info = model.transcribe(
        audio_path,
        beam_size=7,
        initial_prompt=hinglish_prompt,
        condition_on_previous_text=False,
        temperature=[0.0, 0.2, 0.4, 0.6],
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=400,
        ),
    )

    logger.info(f"Language: '{info.language}' (probability: {info.language_probability:.2f})")

    # Write SRT
    _report("transcribe", "Generating transcript...", 0)
    word_count = 0
    total_duration = info.duration

    with open(output_srt, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            start = format_time(segment.start)
            end = format_time(segment.end)
            text = segment.text.strip()

            word_count += len(text.split())

            # Real-time transcription percentage
            current_pct = int((segment.end / total_duration) * 100) if total_duration > 0 else 0
            _report("transcribe", f"Transcribing... ({format_time(segment.end)[:8]})", current_pct)

            f.write(f"{i}\n")
            f.write(f"{start} --> {end}\n")
            f.write(f"{text}\n\n")

            # Log preview
            snippet = text[:50] + "..." if len(text) > 50 else text
            logger.debug(f"[{format_time(segment.start)[:8]}] {snippet}")

    elapsed = time.time() - start_time
    _report("transcribe", f"Finished transcription in {elapsed:.1f}s", 100)
    logger.info(f"Transcription complete in {elapsed:.2f}s — {word_count:,} words — saved to {output_srt}")


# ─── DB Update Helper ────────────────────────────────────────

async def _update_session(
    session_id: str,
    state: ProcessingState,
    transcript_path: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update a VideoSession record in the database."""
    async with AsyncSessionLocal() as db:
        values: dict = {"state": state}
        if transcript_path is not None:
            values["transcript_file_path"] = transcript_path
        if error_message is not None:
            values["error_message"] = error_message

        stmt = update(VideoSession).where(VideoSession.id == session_id).values(**values)
        await db.execute(stmt)
        await db.commit()


# ─── Async Progress Callback Factory ─────────────────────────

def _make_async_progress_callback(
    session_id: str,
    ws_manager: ConnectionManager,
) -> Callable:
    """
    Create a progress callback for use from within asyncio.to_thread.

    Since this runs in a thread, we use asyncio.run_coroutine_threadsafe
    to bridge back to the event loop for WebSocket broadcasts.
    """

    def callback(stage: str, detail: str, pct: int = -1) -> None:
        data = {
            "type": "progress",
            "session_id": session_id,
            "stage": stage,
            "detail": detail,
            "pct": pct,
        }
        logger.debug(f"[{session_id}] {stage}: {detail} ({pct}%)")

        # Get the running event loop from the main thread
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    ws_manager.broadcast(session_id, data),
                    loop,
                )
            else:
                # Fallback: create a new loop just for the broadcast
                asyncio.run(ws_manager.broadcast(session_id, data))
        except RuntimeError:
            # No event loop in this thread — use run_coroutine_threadsafe
            # with a reference we stash on the callback
            if hasattr(callback, '_loop') and callback._loop:
                asyncio.run_coroutine_threadsafe(
                    ws_manager.broadcast(session_id, data),
                    callback._loop,
                )

    return callback


# ─── Sync Pipeline (CPU-bound, run via asyncio.to_thread) ────

def _run_pipeline_sync(
    session_id: str,
    video_path: str,
    original_filename: str,
    ws_manager: ConnectionManager,
    loop: asyncio.AbstractEventLoop,
) -> dict:
    """
    Execute the CPU-bound transcription pipeline synchronously.

    Returns a result dict with status info. Called via asyncio.to_thread().
    """
    progress_cb = _make_progress_callback_with_loop(session_id, ws_manager, loop)
    model_size = WHISPER_MODEL

    # Derived paths
    temp_audio = str(GENERATED_DIR / f"{session_id}_temp_audio.wav")
    output_srt = str(GENERATED_DIR / f"{session_id}_transcript.srt")

    try:
        progress_cb("pipeline", f"Extracting audio & transcribing with Faster-Whisper ({model_size})...")

        # Step 1: Extract audio
        progress_cb("extract", f"Extracting audio from {Path(video_path).name}...", -1)
        extract_audio(video_path, temp_audio)
        progress_cb("extract", "Audio extraction complete.", -1)

        # Step 2: Transcribe
        start_time = time.time()
        transcribe_audio(
            audio_path=temp_audio,
            output_srt=output_srt,
            model_size=model_size,
            progress_cb=progress_cb,
        )
        elapsed = time.time() - start_time

        return {
            "success": True,
            "srt_filename": f"{session_id}_transcript.srt",
            "elapsed": elapsed,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }

    finally:
        # Clean up temp audio file
        if os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
                logger.info(f"Cleaned up temp audio: {temp_audio}")
            except OSError:
                pass


# ─── Progress Callback Factory (with explicit loop) ──────────

def _make_progress_callback_with_loop(
    session_id: str,
    ws_manager: ConnectionManager,
    loop: asyncio.AbstractEventLoop,
) -> Callable:
    """
    Create a progress callback that bridges the sync background thread
    to the async WebSocket broadcast using an explicit event loop reference.
    """

    def callback(stage: str, detail: str, pct: int = -1) -> None:
        data = {
            "type": "progress",
            "session_id": session_id,
            "stage": stage,
            "detail": detail,
            "pct": pct,
        }
        logger.debug(f"[{session_id}] {stage}: {detail} ({pct}%)")
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast(session_id, data),
            loop,
        )

    return callback


# ─── Async Pipeline Entry Point ──────────────────────────────

async def run_pipeline_async(
    session_id: str,
    video_path: str,
    original_filename: str,
    ws_manager: ConnectionManager,
) -> None:
    """
    Async entry point for the transcription pipeline.

    1. Update DB state → PROCESSING
    2. Run CPU-bound work in a thread via asyncio.to_thread()
    3. Update DB state → COMPLETED (or FAILED)
    4. Broadcast result via WebSocket
    5. Clean up uploaded video on success
    """

    # Mark as processing
    await _update_session(session_id, ProcessingState.PROCESSING)

    # Get the current event loop to pass to the thread
    loop = asyncio.get_running_loop()

    # Run CPU-heavy work in a thread
    result = await asyncio.to_thread(
        _run_pipeline_sync,
        session_id,
        video_path,
        original_filename,
        ws_manager,
        loop,
    )

    if result["success"]:
        # Update DB with result
        srt_filename = result["srt_filename"]
        elapsed = result["elapsed"]

        await _update_session(
            session_id, ProcessingState.COMPLETED,
            transcript_path=srt_filename,
        )

        # Notify frontend of completion
        await ws_manager.broadcast(session_id, {
            "type": "progress",
            "session_id": session_id,
            "stage": "complete",
            "detail": f"Transcription generated in {elapsed:.1f}s",
            "pct": 100,
        })
        await ws_manager.broadcast(session_id, {
            "type": "completed",
            "session_id": session_id,
            "transcript_file": srt_filename,
        })

        logger.info(f"Pipeline complete for session {session_id}")

        # Delete uploaded video on success (save disk space)
        output_srt = str(GENERATED_DIR / srt_filename)
        if os.path.exists(video_path) and os.path.exists(output_srt):
            try:
                os.remove(video_path)
                logger.info(f"Cleaned up uploaded video: {video_path}")
            except OSError:
                pass

    else:
        error_msg = result["error"]
        logger.error(f"Pipeline failed for session {session_id}: {error_msg}")

        await _update_session(
            session_id, ProcessingState.FAILED,
            error_message=error_msg,
        )

        await ws_manager.broadcast(session_id, {
            "type": "error",
            "session_id": session_id,
            "error": error_msg,
        })


# ─── Legacy Sync Pipeline (kept for backward compatibility) ──

def run_pipeline(
    session_id: str,
    video_path: str,
    original_filename: str,
    ws_manager: ConnectionManager,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Execute the full transcription pipeline in a background thread.
    Legacy entry point — use run_pipeline_async for new code.
    """
    progress_cb = _make_progress_callback_with_loop(session_id, ws_manager, loop)
    model_size = WHISPER_MODEL

    # Derived paths
    temp_audio = str(GENERATED_DIR / f"{session_id}_temp_audio.wav")
    output_srt = str(GENERATED_DIR / f"{session_id}_transcript.srt")

    try:
        # Mark as processing
        asyncio.run_coroutine_threadsafe(
            _update_session(session_id, ProcessingState.PROCESSING), loop
        ).result(timeout=10)

        progress_cb("pipeline", f"Extracting audio & transcribing with Faster-Whisper ({model_size})...")

        # Step 1: Extract audio
        progress_cb("extract", f"Extracting audio from {Path(video_path).name}...", -1)
        extract_audio(video_path, temp_audio)
        progress_cb("extract", "Audio extraction complete.", -1)

        # Step 2: Transcribe
        start_time = time.time()
        transcribe_audio(
            audio_path=temp_audio,
            output_srt=output_srt,
            model_size=model_size,
            progress_cb=progress_cb,
        )
        elapsed = time.time() - start_time

        # Step 3: Update DB with result
        # Store path relative to GENERATED_DIR for portability
        srt_filename = f"{session_id}_transcript.srt"
        asyncio.run_coroutine_threadsafe(
            _update_session(session_id, ProcessingState.COMPLETED, transcript_path=srt_filename),
            loop,
        ).result(timeout=10)

        # Notify frontend of completion
        progress_cb("complete", f"Transcription generated in {elapsed:.1f}s", 100)

        # Broadcast completion with file info
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast(session_id, {
                "type": "completed",
                "session_id": session_id,
                "transcript_file": srt_filename,
            }),
            loop,
        )

        logger.info(f"Pipeline complete for session {session_id}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Pipeline failed for session {session_id}: {error_msg}")

        # Update DB with failure
        asyncio.run_coroutine_threadsafe(
            _update_session(session_id, ProcessingState.FAILED, error_message=error_msg),
            loop,
        )

        # Notify frontend of failure
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast(session_id, {
                "type": "error",
                "session_id": session_id,
                "error": error_msg,
            }),
            loop,
        )

    finally:
        # Clean up temp audio file
        if os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
                logger.info(f"Cleaned up temp audio: {temp_audio}")
            except OSError:
                pass

        # Delete uploaded video on success (save disk space)
        # Keep on failure for debugging/retry
        if os.path.exists(video_path) and os.path.exists(output_srt):
            try:
                os.remove(video_path)
                logger.info(f"Cleaned up uploaded video: {video_path}")
            except OSError:
                pass
