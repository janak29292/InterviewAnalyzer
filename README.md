# 🎬 Video Transcriber

An asynchronous, queue-based video transcription application powered by **FastAPI**, **Faster-Whisper**, and **Svelte 5**. Upload videos of any size to extract audio, transcribe speech with high accuracy, and download formatted SubRip (`.srt`) transcripts with real-time WebSocket progress tracking.

---

## ✨ Features

- **Sequential Processing Queue:** Upload multiple large video files without overloading CPU, GPU, or RAM. Jobs are processed sequentially in a strictly managed FIFO queue.
- **High-Performance Transcription:** Powered by [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) with automatic CUDA detection (`float16` on GPU, `int8` on CPU) and Voice Activity Detection (VAD) filtering.
- **Real-Time WebSocket Updates:** Live progress percentages, timestamps, and stage transitions (Audio Extraction ➔ Transcribing ➔ Complete) streamed directly to the UI.
- **Crash Recovery & Fault Tolerance:** Automatic recovery on server startup — any jobs interrupted or stuck in `QUEUED` or `PROCESSING` state are automatically recovered and re-enqueued.
- **Memory-Optimized Pipeline:** Streams audio extraction directly through FFmpeg without loading raw video files into RAM; temporary audio files (`.wav`) are cleaned up immediately after transcription.
- **Multi-Format Support:** Accepts MP4, WebM, MOV, AVI, MKV, MPEG, and OGG formats.
- **Modern Svelte 5 Frontend:** Built with Svelte 5 runes (`$state`), Tailwind CSS v4, dark glassmorphism styling, and interactive queue management dashboard.
- **Direct SRT Downloads:** Download cleanly formatted `.srt` subtitle/transcript files named after your original video file.

---

## 🏗️ System Architecture

```
IntervewAnalyzer/
├── backend/                  # FastAPI Application (Runs in WSL / Linux)
│   ├── api/
│   │   └── urls.py           # Declarative API and WebSocket route mappings
│   ├── core/
│   │   ├── config.py         # App configuration & environment variables
│   │   ├── database.py       # Async SQLAlchemy engine & session factory
│   │   ├── dependencies.py   # FastAPI dependency injection helpers
│   │   └── websockets.py     # Connection manager for live progress broadcast
│   ├── models/
│   │   └── video.py          # SQLAlchemy 2.0 models (VideoSession, ProcessingState)
│   ├── schemas/
│   │   └── video.py          # Pydantic schemas for request/response serialization
│   ├── services/
│   │   └── views.py          # API request handlers and business logic
│   ├── workers/
│   │   ├── pipeline.py       # Audio extraction (FFmpeg) & transcription pipeline
│   │   └── queue_manager.py  # Async FIFO transcription queue worker
│   └── main.py               # FastAPI entrypoint, lifespan manager & recovery logic
├── frontend/                 # Svelte 5 + Vite Web Application
│   ├── src/
│   │   ├── lib/
│   │   │   ├── UploadSection.svelte     # Drag-and-drop video upload component
│   │   │   ├── QueueDashboard.svelte    # Live queue dashboard & status cards
│   │   │   ├── ProgressSection.svelte   # Active transcription progress bar
│   │   │   └── DownloadSection.svelte   # One-click transcript download
│   │   ├── App.svelte                   # Main dashboard view
│   │   └── app.css                      # Tailwind CSS v4 design system
│   ├── package.json
│   └── vite.config.js
├── data/                     # Persistent storage (auto-generated)
│   ├── interview_analyzer.db # SQLite database
│   ├── uploads/              # Uploaded raw video files
│   └── generated/            # Transcripts (.srt) and temporary files
└── requirements.txt          # Python dependencies
```

---

## 📋 Prerequisites

Before running the project, ensure you have the following installed:

1. **Python 3.10+** (in WSL or Linux recommended for CUDA / Faster-Whisper compatibility)
2. **FFmpeg** (installed on system path for audio extraction)
   ```bash
   # On Ubuntu / WSL:
   sudo apt update && sudo apt install -y ffmpeg
   ```
3. **Node.js (v18+) & npm** (installed on Windows or WSL)
4. *(Optional)* **NVIDIA GPU with CUDA drivers** for accelerated transcription.

---

## 🚀 Installation & Setup

### 1. Backend Setup (WSL / Linux)

Clone the repository and enter the project directory:

```bash
cd /mnt/e/IntervewAnalyzer
```

Create a virtual environment and install Python dependencies:

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Frontend Setup (Windows or WSL)

Navigate into the `frontend/` directory and install npm packages:

```bash
cd frontend
npm install
```

---

## 💻 Running the Application

Both services need to run simultaneously in separate terminals.

### Terminal 1: Backend Server (FastAPI)

Inside your **WSL terminal**:

```bash
cd /mnt/e/IntervewAnalyzer
source venv/bin/activate
cd backend
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

*Or via direct Python execution:*
```bash
cd /mnt/e/IntervewAnalyzer/backend
../venv/bin/python main.py
```

- **Backend API:** `http://localhost:8002`
- **Swagger Docs:** `http://localhost:8002/docs`
- **ReDoc Docs:** `http://localhost:8002/redoc`

---

### Terminal 2: Frontend Server (Vite)

In a **Windows PowerShell / Command Prompt** terminal:

```powershell
cd e:\IntervewAnalyzer\frontend
npm run dev
```

- **Web Application:** `http://localhost:5173`

---

## ⚙️ Configuration & Environment Variables

The backend can be configured using environment variables in a `.env` file or exported in your shell:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8002` | Port for the FastAPI server |
| `WHISPER_MODEL` | `large-v3` | Model size (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `DATA_DIR` | `<root>/data` | Directory where database, uploads, and transcripts are saved |
| `DATABASE_URL` | `sqlite+aiosqlite:///<DATA_DIR>/interview_analyzer.db` | SQLAlchemy database connection string |

### Model Recommendations

| Model | Memory (RAM / VRAM) | Speed | Recommended For |
| :--- | :--- | :--- | :--- |
| `small` | ~1.5 GB | Very Fast | Quick drafts, testing, low memory machines |
| `medium` | ~3.0 GB | Fast | Excellent balance of accuracy and resource usage |
| `large-v3` *(Default)* | ~5.0 - 7.0 GB | Moderate | Highest accuracy, multi-lingual / Hinglish recognition |

> [!TIP]
> If your system runs into memory constraints on very long videos in WSL, switch to `WHISPER_MODEL=medium` in your environment for a significant reduction in RAM usage with minimal loss in accuracy.

---

## 🔌 API Reference

### REST Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/upload` | Upload a video file and enqueue it for transcription |
| `GET` | `/api/sessions` | List recent transcription sessions for the dashboard |
| `GET` | `/api/sessions/{session_id}` | Retrieve current status and details for a specific session |
| `GET` | `/api/sessions/{session_id}/transcript` | Download the completed `.srt` transcript file |

### WebSocket Endpoint

| Protocol | Endpoint | Description |
| :--- | :--- | :--- |
| `WS` | `/ws/{session_id}` | Real-time stream of progress percentages, current phase, and completion status |

---

## 🛠️ Tech Stack

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/), [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), [CTranslate2](https://github.com/OpenNMT/CTranslate2), [FFmpeg](https://ffmpeg.org/), [SQLAlchemy 2.0](https://www.sqlalchemy.org/) (Async), [aiosqlite](https://github.com/omnilib/aiosqlite), [Uvicorn](https://www.uvicorn.org/)
- **Frontend:** [Svelte 5](https://svelte.dev/), [Vite](https://vitejs.dev/), [Tailwind CSS v4](https://tailwindcss.com/)
