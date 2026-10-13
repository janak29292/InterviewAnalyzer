"""
Transcription Queue Manager — sequential job processing.

Ensures only one transcription runs at a time to avoid GPU/CPU contention.
Jobs are enqueued immediately on upload and processed in FIFO order.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from core.websockets import ConnectionManager

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionJob:
    """A pending transcription job."""
    session_id: str
    video_path: str
    original_filename: str


class TranscriptionQueue:
    """
    Manages a sequential queue of transcription jobs.

    Only one job runs at a time. When it completes (success or fail),
    the next job in the queue is picked up automatically.
    """

    def __init__(self, ws_manager: ConnectionManager) -> None:
        self._queue: asyncio.Queue[TranscriptionJob] = asyncio.Queue()
        self._ws_manager = ws_manager
        self._worker_task: Optional[asyncio.Task] = None
        self._current_job: Optional[TranscriptionJob] = None

    @property
    def current_job(self) -> Optional[TranscriptionJob]:
        """The job currently being processed, if any."""
        return self._current_job

    def enqueue(self, session_id: str, video_path: str, original_filename: str) -> None:
        """Add a job to the queue. Non-blocking."""
        job = TranscriptionJob(
            session_id=session_id,
            video_path=video_path,
            original_filename=original_filename,
        )
        self._queue.put_nowait(job)
        logger.info(f"Enqueued job {session_id} ({original_filename}) — "
                     f"queue depth: {self._queue.qsize()}")

    def start(self) -> None:
        """Start the background worker task."""
        if self._worker_task is not None:
            logger.warning("Queue worker already running.")
            return
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("Transcription queue worker started.")

    async def stop(self) -> None:
        """Gracefully stop the worker task."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("Transcription queue worker stopped.")

    async def _worker(self) -> None:
        """Consume jobs from the queue one at a time."""
        from workers.pipeline import run_pipeline_async

        logger.info("Queue worker waiting for jobs...")

        while True:
            try:
                job = await self._queue.get()
                self._current_job = job
                logger.info(f"Dequeued job {job.session_id} — starting pipeline...")

                try:
                    await run_pipeline_async(
                        session_id=job.session_id,
                        video_path=job.video_path,
                        original_filename=job.original_filename,
                        ws_manager=self._ws_manager,
                    )
                except Exception as e:
                    logger.error(f"Pipeline failed for {job.session_id}: {e}")

                self._current_job = None
                self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("Queue worker cancelled.")
                break
            except Exception as e:
                logger.error(f"Unexpected queue worker error: {e}")
                self._current_job = None


# Singleton instance — initialized in main.py lifespan
queue_manager: Optional[TranscriptionQueue] = None


def get_queue_manager() -> TranscriptionQueue:
    """Get the singleton queue manager instance."""
    if queue_manager is None:
        raise RuntimeError("Queue manager not initialized. Is the app running?")
    return queue_manager
