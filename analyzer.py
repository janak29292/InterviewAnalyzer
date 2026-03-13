"""
Interview Video Analyzer — Processing Pipeline
Stage 1: Audio extraction + Whisper transcription
Stage 2: Speech fluency analysis (pauses, fillers, stuttering, pace)
Stage 3: Smart frame extraction + deduplication
Stage 4: Gemini analysis with coding interview prompt
"""

import json
import os
import re
import subprocess
import shutil
import tempfile
import time
from pathlib import Path
from collections import Counter

import numpy as np
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# ─── Progress Callback ───────────────────────────────────────
# Set by the server to push progress updates to the frontend
_progress_callback = None


def set_progress_callback(cb):
    global _progress_callback
    _progress_callback = cb


def _progress(stage: str, detail: str, pct: int = -1):
    """Report progress to the frontend."""
    print(f"  [{stage}] {detail}" + (f" ({pct}%)" if pct >= 0 else ""))
    if _progress_callback:
        _progress_callback(stage, detail, pct)


# ─── Stage 1: Audio Extraction + Transcription ────────────────

def extract_audio(video_path: str, output_dir: str) -> str:
    """Extract audio from video using FFmpeg."""
    _progress("extract", "Extracting audio from video...")
    audio_path = os.path.join(output_dir, "audio.wav")

    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn",                     # no video
        "-acodec", "pcm_s16le",    # WAV format
        "-ar", "16000",            # 16kHz (optimal for Whisper)
        "-ac", "1",                # mono
        "-y",                      # overwrite
        audio_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr[-500:]}")

    _progress("extract", "Audio extracted successfully", 100)
    return audio_path


def transcribe_audio(audio_path: str) -> dict:
    """Transcribe audio using Whisper with word-level timestamps."""
    import whisper

    model_name = os.getenv("WHISPER_MODEL", "base")
    _progress("transcribe", f"Loading Whisper model '{model_name}'...")

    model = whisper.load_model(model_name)
    _progress("transcribe", "Transcribing audio (this may take a while)...")

    result = model.transcribe(
        audio_path,
        word_timestamps=True,
        verbose=False,
    )

    # Extract structured data
    segments = []
    all_words = []

    for seg in result.get("segments", []):
        seg_words = []
        for w in seg.get("words", []):
            word_info = {
                "word": w["word"].strip(),
                "start": round(w["start"], 2),
                "end": round(w["end"], 2),
            }
            seg_words.append(word_info)
            all_words.append(word_info)

        segments.append({
            "id": seg["id"],
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip(),
            "words": seg_words,
        })

    _progress("transcribe", f"Transcription complete — {len(segments)} segments, {len(all_words)} words", 100)

    return {
        "text": result["text"].strip(),
        "language": result.get("language", "en"),
        "segments": segments,
        "words": all_words,
    }


# ─── Stage 2: Speech Fluency Analysis ─────────────────────────

FILLER_WORDS = {
    "um", "uh", "uhm", "umm", "hmm", "hm",
    "like", "you know", "basically", "actually",
    "so", "right", "okay", "well", "I mean",
    "sort of", "kind of", "literally", "honestly",
}

FILLER_SINGLES = {w for w in FILLER_WORDS if " " not in w}
FILLER_PAIRS = {w for w in FILLER_WORDS if " " in w}


def analyze_speech_fluency(transcript_data: dict) -> dict:
    """Analyze speech patterns from Whisper word timestamps."""
    _progress("fluency", "Analyzing speech fluency...")

    words = transcript_data["words"]
    if not words:
        return _empty_fluency()

    full_text = transcript_data["text"].lower()
    total_duration = words[-1]["end"] - words[0]["start"] if words else 0

    # ── Filler word detection ──
    filler_counts = Counter()

    # Single-word fillers
    for w in words:
        clean = w["word"].lower().strip(".,!?;:'\"")
        if clean in FILLER_SINGLES:
            filler_counts[clean] += 1

    # Multi-word fillers
    for filler in FILLER_PAIRS:
        filler_counts[filler] = len(re.findall(r'\b' + re.escape(filler) + r'\b', full_text))

    total_fillers = sum(filler_counts.values())
    filler_details = dict(filler_counts.most_common(10))

    # ── Pause detection ──
    pauses = []
    long_pause_threshold = 1.5  # seconds
    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i - 1]["end"]
        if gap >= long_pause_threshold:
            pauses.append({
                "start": round(words[i - 1]["end"], 2),
                "end": round(words[i]["start"], 2),
                "duration": round(gap, 2),
                "after_word": words[i - 1]["word"],
                "before_word": words[i]["word"],
                "timestamp": _format_time(words[i - 1]["end"]),
            })

    # ── Stuttering detection (repeated words within 2-word window) ──
    stutters = []
    for i in range(1, len(words)):
        w1 = words[i - 1]["word"].lower().strip(".,!?;:'\"")
        w2 = words[i]["word"].lower().strip(".,!?;:'\"")
        if w1 == w2 and len(w1) > 1 and w1 not in FILLER_SINGLES:
            stutters.append({
                "word": w1,
                "timestamp": _format_time(words[i - 1]["start"]),
                "start": words[i - 1]["start"],
            })

    # ── Speaking pace (words per minute, rolling) ──
    total_words = len(words)
    overall_wpm = round((total_words / total_duration) * 60) if total_duration > 0 else 0

    # Calculate WPM in 60-second windows
    pace_segments = []
    if words and total_duration > 30:
        window = 60  # seconds
        step = 30
        t = words[0]["start"]
        while t < words[-1]["end"] - window / 2:
            window_words = [w for w in words if t <= w["start"] < t + window]
            wpm = round(len(window_words) * (60 / window))
            pace_segments.append({
                "time": _format_time(t),
                "wpm": wpm,
            })
            t += step

    # ── Speaking vs silence ──
    speaking_time = sum(w["end"] - w["start"] for w in words)
    silence_time = total_duration - speaking_time
    speaking_ratio = round(speaking_time / total_duration * 100, 1) if total_duration > 0 else 0

    _progress("fluency", "Speech fluency analysis complete", 100)

    return {
        "total_duration_seconds": round(total_duration, 1),
        "total_duration_formatted": _format_time(total_duration),
        "total_words": total_words,
        "overall_wpm": overall_wpm,
        "speaking_ratio_percent": speaking_ratio,
        "silence_seconds": round(silence_time, 1),
        "filler_words": {
            "total_count": total_fillers,
            "per_minute": round(total_fillers / (total_duration / 60), 1) if total_duration > 60 else total_fillers,
            "breakdown": filler_details,
        },
        "pauses": {
            "count": len(pauses),
            "avg_duration": round(sum(p["duration"] for p in pauses) / len(pauses), 2) if pauses else 0,
            "longest": max((p["duration"] for p in pauses), default=0),
            "details": pauses[:20],  # top 20 longest pauses
        },
        "stutters": {
            "count": len(stutters),
            "details": stutters[:15],
        },
        "pace_over_time": pace_segments,
    }


def _empty_fluency():
    return {
        "total_duration_seconds": 0, "total_words": 0, "overall_wpm": 0,
        "speaking_ratio_percent": 0, "silence_seconds": 0,
        "filler_words": {"total_count": 0, "per_minute": 0, "breakdown": {}},
        "pauses": {"count": 0, "avg_duration": 0, "longest": 0, "details": []},
        "stutters": {"count": 0, "details": []},
        "pace_over_time": [],
    }


def _format_time(seconds: float) -> str:
    """Format seconds to HH:MM:SS or MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ─── Stage 3: Smart Frame Extraction ──────────────────────────

def extract_frames(video_path: str, output_dir: str, fps: int = 1) -> list[str]:
    """Extract frames from video at specified fps using FFmpeg."""
    _progress("frames", f"Extracting frames at {fps} fps...")
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "3",  # good quality JPEG
        "-y",
        os.path.join(frames_dir, "frame_%06d.jpg")
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg frame extraction failed: {result.stderr[-500:]}")

    frame_files = sorted(Path(frames_dir).glob("frame_*.jpg"))
    _progress("frames", f"Extracted {len(frame_files)} raw frames")
    return [str(f) for f in frame_files]


def deduplicate_frames(frame_paths: list[str], threshold: float = 0.05) -> list[dict]:
    """
    Keep only frames where the screen content changed significantly.
    Uses pixel-level difference. threshold = fraction of pixels that must differ.
    Returns list of dicts with path, index, and timestamp info.
    """
    if not frame_paths:
        return []

    _progress("frames", f"Deduplicating {len(frame_paths)} frames...")

    kept = []
    prev_arr = None

    for i, path in enumerate(frame_paths):
        img = Image.open(path).convert("RGB").resize((640, 360))  # downscale for comparison
        arr = np.array(img, dtype=np.float32)

        if prev_arr is None:
            # Always keep the first frame
            kept.append({
                "path": path,
                "index": i,
                "timestamp_sec": i,  # at 1fps, frame index ≈ seconds
                "timestamp": _format_time(i),
            })
            prev_arr = arr
            continue

        # Pixel difference
        diff = np.abs(arr - prev_arr) / 255.0
        changed_pixels = np.mean(diff > 0.1)  # pixel-level threshold

        if changed_pixels > threshold:
            kept.append({
                "path": path,
                "index": i,
                "timestamp_sec": i,
                "timestamp": _format_time(i),
            })
            prev_arr = arr

        if (i + 1) % 500 == 0:
            _progress("frames", f"Processed {i + 1}/{len(frame_paths)} frames, kept {len(kept)} unique")

    _progress("frames", f"Deduplication complete: {len(frame_paths)} → {len(kept)} unique frames", 100)
    return kept


def prepare_frames_for_gemini(unique_frames: list[dict], max_frames: int = 250) -> list[dict]:
    """
    If there are too many unique frames, subsample evenly.
    Resize frames to 1280px wide for token efficiency.
    """
    if len(unique_frames) <= max_frames:
        selected = unique_frames
    else:
        # Evenly sample
        step = len(unique_frames) / max_frames
        indices = [int(i * step) for i in range(max_frames)]
        selected = [unique_frames[i] for i in indices]
        _progress("frames", f"Subsampled to {len(selected)} frames for analysis")

    # Resize frames
    prepared = []
    for f in selected:
        img = Image.open(f["path"]).convert("RGB")
        w, h = img.size
        if w > 1280:
            ratio = 1280 / w
            img = img.resize((1280, int(h * ratio)), Image.LANCZOS)
        resized_path = f["path"].replace(".jpg", "_resized.jpg")
        img.save(resized_path, quality=85)
        prepared.append({
            "path": resized_path,
            "timestamp": f["timestamp"],
            "timestamp_sec": f["timestamp_sec"],
        })

    return prepared


# ─── Stage 4: Gemini Analysis ─────────────────────────────────

CODING_INTERVIEW_PROMPT = """You are an expert coding interview coach. Analyze this coding interview recording.

You are given:
1. A complete transcript of the interview with timestamps
2. Speech fluency metrics (pauses, filler words, stuttering, speaking pace)
3. Screenshots of the candidate's screen at key moments (when code changed on screen)

The interview involves screen-shared coding — the candidate writes code while discussing their approach.

Analyze everything thoroughly and return a JSON object with EXACTLY this structure (no markdown, no code fences, just raw JSON):

{
  "overall_score": <number 1-100>,
  "overall_summary": "<2-3 sentence executive summary of interview performance>",

  "coding_quality": {
    "score": <number 1-100>,
    "code_correctness": "<assessment of whether the code logic was correct>",
    "code_cleanliness": "<readability, naming conventions, structure>",
    "efficiency": "<time/space complexity awareness, optimization>",
    "debugging_skills": "<how they handled bugs or errors>",
    "suggestions": ["<specific improvement>", "..."]
  },

  "problem_solving": {
    "score": <number 1-100>,
    "approach": "<how they broke down the problem — top-down, brute force first then optimize, etc>",
    "clarifying_questions": "<did they ask clarifying questions before jumping in?>",
    "edge_cases": "<did they consider edge cases?>",
    "time_management": "<how well they managed time across the problem>",
    "suggestions": ["<specific improvement>", "..."]
  },

  "communication": {
    "score": <number 1-100>,
    "think_aloud": "<how well they explained their thought process while coding>",
    "clarity": "<clarity of explanations>",
    "technical_vocabulary": "<appropriate use of technical terms>",
    "interaction_with_interviewer": "<how they responded to hints or follow-up questions>",
    "suggestions": ["<specific improvement>", "..."]
  },

  "speech_fluency": {
    "score": <number 1-100>,
    "overall_assessment": "<assessment based on the fluency metrics provided>",
    "filler_word_impact": "<how filler words affected their communication>",
    "pause_analysis": "<were pauses thoughtful or uncertain?>",
    "confidence_from_voice": "<perceived confidence level from speech patterns>",
    "suggestions": ["<specific improvement>", "..."]
  },

  "top_strengths": [
    "<strength 1 with brief explanation>",
    "<strength 2 with brief explanation>",
    "<strength 3 with brief explanation>"
  ],

  "areas_for_improvement": [
    {
      "area": "<improvement area>",
      "current_behavior": "<what they currently do>",
      "recommended_action": "<specific, actionable advice>",
      "priority": "<high/medium/low>"
    }
  ],

  "question_breakdown": [
    {
      "question_number": 1,
      "question_topic": "<what the coding problem/question was about>",
      "approximate_timestamp": "<e.g., '2:30 - 15:45'>",
      "score": <number 1-100>,
      "approach_used": "<how they approached this specific problem>",
      "what_went_well": "<what was good>",
      "what_to_improve": "<what could be better>",
      "code_feedback": "<specific feedback on the code they wrote for this question>",
      "suggested_approach": "<how they could do it better next time>"
    }
  ],

  "interview_readiness": {
    "score": <number 1-100>,
    "verdict": "<Not Ready / Needs Work / Almost There / Interview Ready / Excellent>",
    "next_steps": ["<actionable step 1>", "<actionable step 2>", "<actionable step 3>"]
  }
}

Be thorough, specific, and constructive. Reference specific timestamps and code snippets when possible.
Ensure all JSON fields are present.

---

SPEECH FLUENCY METRICS:
{fluency_metrics}

---

FULL TRANSCRIPT:
{transcript}
"""


def analyze_with_gemini(
    transcript_data: dict,
    fluency_data: dict,
    prepared_frames: list[dict],
) -> dict:
    """Send transcript + fluency metrics + frames to Gemini for analysis."""
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_free_api_key_here":
        raise RuntimeError("GEMINI_API_KEY not set. Get a free key at https://aistudio.google.com/apikey")

    client = genai.Client(api_key=api_key)

    _progress("analyze", f"Preparing analysis request ({len(prepared_frames)} frames)...")

    # Build the prompt
    fluency_summary = json.dumps(fluency_data, indent=2)
    transcript_text = transcript_data["text"]

    prompt_text = CODING_INTERVIEW_PROMPT.replace("{fluency_metrics}", fluency_summary).replace("{transcript}", transcript_text)

    # Build content parts: frames + prompt text
    parts = []

    # Add frames with timestamps as captions
    for i, frame in enumerate(prepared_frames):
        # Upload frame as inline image
        img_bytes = Path(frame["path"]).read_bytes()
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
        parts.append(types.Part.from_text(text=f"[Screen at {frame['timestamp']}]"))

        if (i + 1) % 50 == 0:
            _progress("analyze", f"Prepared {i + 1}/{len(prepared_frames)} frames...")

    # Add the main prompt
    parts.append(types.Part.from_text(text=prompt_text))

    _progress("analyze", "Sending to Gemini for analysis (this may take a minute)...")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=8192,
        ),
    )

    raw_text = response.text.strip()
    _progress("analyze", f"Response received ({len(raw_text)} chars)")

    # Clean markdown fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        raw_text = "\n".join(lines[1:-1])

    try:
        result = json.loads(raw_text)
        _progress("analyze", "Analysis complete!", 100)
        return result
    except json.JSONDecodeError as e:
        _progress("analyze", "Warning: response parsing fallback", 100)
        return {
            "overall_score": 0,
            "overall_summary": "Analysis completed but response could not be parsed. Raw analysis provided.",
            "raw_analysis": raw_text,
            "parse_error": str(e),
        }


# ─── Full Pipeline ────────────────────────────────────────────

def run_full_pipeline(video_path: str) -> dict:
    """
    Execute the complete analysis pipeline:
    1. Extract audio → Transcribe with Whisper
    2. Analyze speech fluency
    3. Extract & deduplicate frames
    4. Send to Gemini for comprehensive analysis
    Returns the full analysis result.
    """
    work_dir = tempfile.mkdtemp(prefix="interview_analyzer_")

    try:
        # Stage 1: Audio + Transcription
        _progress("pipeline", "Stage 1/4: Audio extraction & transcription")
        audio_path = extract_audio(video_path, work_dir)
        transcript = transcribe_audio(audio_path)

        # Stage 2: Speech fluency
        _progress("pipeline", "Stage 2/4: Speech fluency analysis")
        fluency = analyze_speech_fluency(transcript)

        # Stage 3: Frames
        _progress("pipeline", "Stage 3/4: Screen capture extraction & deduplication")
        raw_frames = extract_frames(video_path, work_dir, fps=1)
        unique_frames = deduplicate_frames(raw_frames, threshold=0.05)
        prepared = prepare_frames_for_gemini(unique_frames, max_frames=250)

        # Stage 4: Gemini
        _progress("pipeline", "Stage 4/4: AI analysis")
        analysis = analyze_with_gemini(transcript, fluency, prepared)

        # Attach local metrics to the result
        analysis["_local_metrics"] = {
            "fluency": fluency,
            "transcript_preview": transcript["text"][:2000],
            "total_raw_frames": len(raw_frames),
            "unique_frames_kept": len(unique_frames),
            "frames_sent_to_ai": len(prepared),
        }

        return analysis

    finally:
        # Clean up temp files
        shutil.rmtree(work_dir, ignore_errors=True)
