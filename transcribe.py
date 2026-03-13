"""
Interview Transcript Extractor
Extracts a timestamped transcript from interview video recordings.
Automatically detects speakers and tries to identify them by name from the conversation.

Usage:
    python transcribe.py my_interview.mkv
    python transcribe.py my_interview.mkv --model medium
    python transcribe.py my_interview.mkv --no-speakers
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video using FFmpeg."""
    print(f"📼 Extracting audio from: {Path(video_path).name}")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ FFmpeg error: {result.stderr[-300:]}")
        sys.exit(1)
    print("✅ Audio extracted")
    return output_path


def format_time(seconds: float) -> str:
    """Format seconds to HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def transcribe(audio_path: str, model_name: str = "base") -> dict:
    """Transcribe audio using Whisper."""
    import whisper

    print(f"🧠 Loading Whisper model: {model_name}")
    model = whisper.load_model(model_name)

    print("📝 Transcribing (this may take a while for long videos)...")
    start = time.time()

    result = model.transcribe(
        audio_path,
        word_timestamps=True,
        verbose=False,
    )

    elapsed = time.time() - start
    print(f"✅ Transcription done in {format_time(elapsed)}")
    return result


def diarize(audio_path: str) -> list:
    """
    Perform speaker diarization using pyannote.audio.
    Automatically detects number of speakers.
    Returns list of (start, end, speaker_label) tuples, or None if unavailable.
    """
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        print("⚠️  pyannote.audio not installed.")
        print("   To enable speaker detection: pip install pyannote.audio")
        print("   Continuing without speaker labels.\n")
        return None

    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        print("⚠️  HF_TOKEN not set. Speaker detection requires a free HuggingFace token.")
        print("   One-time setup:")
        print("   1. Create a free token at https://huggingface.co/settings/tokens")
        print("   2. Accept model terms at https://huggingface.co/pyannote/speaker-diarization-3.1")
        print("   3. Set environment variable: HF_TOKEN=your_token")
        print("   Continuing without speaker labels.\n")
        return None

    print("🔊 Detecting speakers automatically...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=hf_token,
    )

    output = pipeline(audio_path)

    segments = []

    # pyannote v4: output has .exclusive_speaker_diarization (non-overlapping)
    # and .speaker_diarization (may have overlaps)
    annotation = None
    if hasattr(output, 'exclusive_speaker_diarization'):
        annotation = output.exclusive_speaker_diarization
    elif hasattr(output, 'speaker_diarization'):
        annotation = output.speaker_diarization
    else:
        annotation = output  # fallback for older versions

    # Extract segments from Annotation object
    if hasattr(annotation, 'itertracks'):
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            segments.append((turn.start, turn.end, speaker))
    else:
        print(f"⚠️  Unexpected output type: {type(annotation)}")
        print(f"   Available: {[m for m in dir(annotation) if not m.startswith('_')]}")
        return None

    speaker_count = len(set(s[2] for s in segments))
    print(f"✅ Detected {speaker_count} speaker(s)")
    return segments


def get_speaker_at_time(diarization_segments: list, time_sec: float) -> str:
    """Find which speaker is talking at a given time."""
    if not diarization_segments:
        return None
    for start, end, speaker in diarization_segments:
        if start <= time_sec <= end:
            return speaker
    return None


def guess_speaker_names(whisper_result: dict, diarization_segments: list) -> dict:
    """
    Try to identify speaker names from the transcript.
    Looks for introduction patterns like "Hi, I'm X", "My name is X",
    "This is X", etc. Maps pyannote speaker IDs to real names.
    Falls back to "Speaker 1", "Speaker 2", etc.
    """
    if not diarization_segments:
        return {}

    raw_speakers = sorted(set(s[2] for s in diarization_segments))
    name_map = {}

    # Patterns that often reveal a speaker's name
    name_patterns = [
        r"(?:my name is|i'm|i am|this is|myself)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:hi|hello|hey),?\s+(?:i'm|i am|this is)\s+([A-Z][a-z]+)",
        r"(?:good (?:morning|afternoon|evening)),?\s+(?:i'm|i am|this is)\s+([A-Z][a-z]+)",
    ]

    for seg in whisper_result.get("segments", []):
        text = seg["text"].strip()
        mid_time = (seg["start"] + seg["end"]) / 2
        speaker_id = get_speaker_at_time(diarization_segments, mid_time)

        if not speaker_id or speaker_id in name_map:
            continue

        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Basic validation — name should be 2-30 chars, not common words
                skip_words = {"the", "a", "an", "it", "we", "so", "just", "not", "here", "there", "very", "really"}
                if 2 <= len(name) <= 30 and name.lower() not in skip_words:
                    name_map[speaker_id] = name
                    break

    # Assign placeholder names for any unidentified speakers
    speaker_num = 1
    for sp in raw_speakers:
        if sp not in name_map:
            name_map[sp] = f"Speaker {speaker_num}"
            speaker_num += 1

    return name_map


def compute_speaker_stats(whisper_result: dict, diarization_segments: list, name_map: dict) -> dict:
    """Compute speaking time per speaker."""
    if not diarization_segments or not name_map:
        return {}

    stats = {name: 0.0 for name in name_map.values()}
    for start, end, speaker_id in diarization_segments:
        name = name_map.get(speaker_id, speaker_id)
        stats[name] += (end - start)

    return stats


def build_transcript_md(
    whisper_result: dict,
    diarization_segments: list = None,
    name_map: dict = None,
    speaker_stats: dict = None,
    video_name: str = "interview",
) -> str:
    """Build a clean markdown transcript."""
    lines = []
    lines.append(f"# Transcript: {video_name}")
    lines.append("")
    lines.append(f"**Model**: Whisper")
    lines.append(f"**Language**: {whisper_result.get('language', 'unknown')}")

    total_segs = len(whisper_result.get("segments", []))
    lines.append(f"**Segments**: {total_segs}")

    # Speaker info
    if name_map:
        names = list(name_map.values())
        lines.append(f"**Speakers**: {len(names)} — {', '.join(names)}")

    if speaker_stats:
        lines.append("")
        lines.append("### Speaking Time")
        lines.append("| Speaker | Time | Share |")
        lines.append("|---------|------|-------|")
        total = sum(speaker_stats.values())
        for name, secs in sorted(speaker_stats.items(), key=lambda x: -x[1]):
            pct = (secs / total * 100) if total > 0 else 0
            lines.append(f"| {name} | {format_time(secs)} | {pct:.0f}% |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Transcript body
    prev_speaker_name = None

    for seg in whisper_result.get("segments", []):
        start = seg["start"]
        end = seg["end"]
        text = seg["text"].strip()
        timestamp = f"[{format_time(start)} → {format_time(end)}]"

        if diarization_segments and name_map:
            mid_time = (start + end) / 2
            speaker_id = get_speaker_at_time(diarization_segments, mid_time)
            speaker_name = name_map.get(speaker_id, "Unknown") if speaker_id else None

            if speaker_name and speaker_name != prev_speaker_name:
                lines.append("")
                lines.append(f"### 🗣️ {speaker_name}")
                lines.append("")
                prev_speaker_name = speaker_name

            lines.append(f"**{timestamp}** {text}")
        else:
            lines.append(f"**{timestamp}** {text}")

        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Extract timestamped transcript from interview videos"
    )
    parser.add_argument("video", help="Path to video file (MKV, MP4, etc.)")
    parser.add_argument(
        "--model", default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: base). Larger = more accurate but slower.",
    )
    parser.add_argument(
        "--no-speakers", action="store_true",
        help="Disable speaker detection (skip diarization even if pyannote is available)",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output file path (default: <video_name>_transcript.md)",
    )

    args = parser.parse_args()

    video_path = args.video
    if not os.path.exists(video_path):
        print(f"❌ File not found: {video_path}")
        sys.exit(1)

    video_name = Path(video_path).stem

    # Output path
    if args.output:
        output_path = args.output
    else:
        output_path = str(Path(video_path).parent / f"{video_name}_transcript.md")

    # Extract audio to temp file
    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp_dir:
        audio_path = os.path.join(tmp_dir, "audio.wav")
        extract_audio(video_path, audio_path)

        # Transcribe
        whisper_result = transcribe(audio_path, model_name=args.model)

        # Speaker diarization (automatic unless --no-speakers)
        diarization_segments = None
        name_map = None
        speaker_stats = None

        if not args.no_speakers:
            diarization_segments = diarize(audio_path)

            if diarization_segments:
                # Try to identify speakers by name
                name_map = guess_speaker_names(whisper_result, diarization_segments)
                speaker_stats = compute_speaker_stats(
                    whisper_result, diarization_segments, name_map
                )

                identified = [n for n in name_map.values() if not n.startswith("Speaker ")]
                if identified:
                    print(f"🏷️  Identified speakers: {', '.join(identified)}")
                else:
                    print(f"🏷️  Could not identify names — using Speaker 1, Speaker 2, etc.")

    # Build markdown
    transcript_md = build_transcript_md(
        whisper_result,
        diarization_segments,
        name_map,
        speaker_stats,
        video_name=video_name,
    )

    # Save
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(transcript_md)

    print(f"\n📄 Transcript saved to: {output_path}")
    word_count = len(whisper_result.get("text", "").split())
    print(f"   Words: {word_count:,}")
    print(f"   Segments: {len(whisper_result.get('segments', []))}")

    if name_map:
        print(f"   Speakers: {', '.join(name_map.values())}")

    print(f"\n💡 Tip: Paste this transcript into Gemini to build your question bank!")


if __name__ == "__main__":
    main()
