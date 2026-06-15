<div align="center">

# 🎙️ Steno

### Video-to-Script Stenographer

**A fully local, offline video & audio transcription web app.**
No API keys. No cloud. No data ever leaves your machine. Completely free.

Upload a 500 MB video — watch the transcript stream into your browser word by word, in real time.

</div>

---

## Why I built this

Most transcription tools are either cloud SaaS products that charge per minute and ship your private recordings to someone else's servers, or command-line utilities with no usable interface. I wanted to prove you could have **both**: the convenience of a polished web app and the privacy and zero cost of running everything on your own hardware.

Steno does the entire pipeline locally — audio extraction, speech recognition, and live streaming of results — using nothing but open-source models. A 500 MB interview, lecture, or podcast goes in; a clean, copyable transcript comes out, appearing live as the model works rather than after a long opaque wait.

## What makes it interesting (the engineering)

The headline feature is **real-time segment streaming**: as the speech model recognizes each chunk of audio, that text appears in the browser immediately — not buffered and dumped at the end. Getting that right on top of a synchronous, CPU-bound ML model is the core technical story of the project.

- **Bridging blocking ML work to an async web server.** `faster-whisper.transcribe()` is a blocking generator. Naively iterating it inside an async endpoint would freeze the entire server's event loop. Steno runs the whole pipeline in a **worker thread** that pushes events onto a thread-safe `queue.Queue`, which the async **Server-Sent Events** endpoint drains and streams to the browser. The event loop stays responsive; segments flow out the instant they're produced.

- **Streaming 500 MB uploads without exhausting memory.** Uploads are read in 1 MB chunks and written straight to a temp file on disk — the server never holds the whole video in RAM. A two-phase flow (`POST /upload` → `GET /transcribe/{job_id}` via `EventSource`) cleanly separates the large binary upload from the live event stream, since SSE can't ride on a multipart POST response.

- **An efficient, verifiable transcription pipeline.** `ffmpeg` compresses a 500 MB video down to ~50 MB of 16 kHz mono WAV before recognition. The model runs `int8`-quantized for practical CPU performance, with voice-activity detection to skip silence. Every temp file is cleaned up in a `finally` block whether the run succeeds or fails.

- **Honest, friendly failure modes.** Missing `ffmpeg`, corrupt or unsupported files, and model-load failures each surface a specific, human-readable message in the UI instead of a stack trace.

> This wasn't just written to compile — the streaming was **verified end-to-end**: a real spoken video was pushed through the running server, and timestamps on each SSE event confirmed segments arrived incrementally (later segments landing seconds after earlier ones), not all at once at the end.

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| **Backend** | FastAPI + Uvicorn | Async, first-class streaming responses, minimal boilerplate |
| **Speech recognition** | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper `medium`, `int8`) | OpenAI-quality transcription, 4× faster than reference Whisper, runs on CPU |
| **Audio extraction** | `ffmpeg` via subprocess | Universal format support; normalizes any video/audio to 16 kHz mono |
| **Streaming** | Server-Sent Events | Native browser `EventSource`, perfect for one-way live updates |
| **Frontend** | Vanilla JS + Tailwind (CDN) | Zero build step, single self-contained `index.html` |

No databases, no message brokers, no external services. The entire system is three Python files and one HTML file.

## Demo

<!-- Add a screen recording or GIF here showing the transcript streaming in live. -->
<!-- e.g. ![Steno demo](docs/demo.gif) -->

```
┌─────────────────────────────┬─────────────────────────────┐
│  Drop a video / audio file  │   Transcript           0 words │
│  ┌─────────────────────┐  │  ┌───────────────────────────┐ │
│  │   ⬆  Click or drag    │  │  │ Your transcript appears   │ │
│  └─────────────────────┘  │  │ here, live, as it is      │ │
│                             │  │ generated…                │ │
│  📄 interview.mp4  487 MB   │  │                           │ │
│  [    Transcribe    ]       │  └───────────────────────────┘ │
│  ⟳ Transcribing…            │                                │
│  Live preview:              │  [   Copy   ] [ Download .txt ] │
│  "Hello there, today we…"   │                                │
└───────────────────────────────┴─────────────────────────────┘
```

## Quick start

### 1. Install ffmpeg

ffmpeg must be installed and on your `PATH`.

**Windows**
```powershell
winget install Gyan.FFmpeg
# or: choco install ffmpeg
```
**macOS**
```bash
brew install ffmpeg
```
**Linux (Debian/Ubuntu)**
```bash
sudo apt update && sudo apt install ffmpeg
```
Verify: `ffmpeg -version`

### 2. Install & run

```bash
cd transcriber

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies and launch
pip install -r requirements.txt
uvicorn main:app --reload
```

Open **http://localhost:8000** and drop in a file.

> **First run:** the Whisper `medium` model (~1.5 GB) downloads and caches automatically during the "Loading model…" step. This happens once — subsequent runs reuse the cached model.

## How it works

```
 Browser                    FastAPI                  Worker thread
 ───────                    ───────                  ─────────────
 1. POST /upload  ───────▶  stream to disk (1 MB chunks) ─▶ temp file
                  ◀───────  { job_id }
 2. EventSource           ┌────────────────────────────────┐
    GET /transcribe/{id}  │  spawn worker, drain queue.Queue      │
                          │                                       │
                  ◀─ SSE ─┤  status:  "Extracting audio…"  ◀── ffmpeg → 16kHz WAV
                  ◀─ SSE ─┤  status:  "Loading model…"     ◀── load faster-whisper
                  ◀─ SSE ─┤  segment: "Hello there."       ◀── ┐
                  ◀─ SSE ─┤  segment: "This is a test…"    ◀── ├ generator yields,
                  ◀─ SSE ─┤  segment: …                    ◀── ┘ pushed live
                  ◀─ SSE ─┤  done:    "<full transcript>"  ◀── join + cleanup
                          └─────────────────────────────────┘
 3. UI appends each segment to the transcript as it arrives; temp files deleted.
```

## Project structure

```
Steno/
├── README.md
└── transcriber/
    ├── main.py            # FastAPI: serves UI, streams uploads, streams SSE
    ├── transcribe.py      # ffmpeg + faster-whisper pipeline (worker thread → queue)
    ├── static/
    │   └── index.html     # Single-page frontend (vanilla JS + Tailwind)
    └── requirements.txt
```

## Features

- 🎬 **Any format in** — any video or audio file (ffmpeg handles the conversion)
- ⚡ **Live transcription** — segments stream to the browser as they're recognized
- 🔒 **100% local & private** — nothing is uploaded anywhere; runs offline after setup
- 💸 **Free forever** — no per-minute API billing
- 📋 **Copy & download** — one-click copy or download as `.txt` named after your file
- 📊 **Live word count** and scrollable transcript you can edit in place
- 🧹 **Self-cleaning** — temp files removed automatically after every run
- 🪟 **Responsive** — two-column on wide screens, single column on mobile

## Possible extensions

Ideas I'd reach for next, in rough priority order:

- **Timestamps & subtitle export** (`.srt` / `.vtt`) — faster-whisper already returns per-segment timing
- **Speaker diarization** ("who said what") via `pyannote`
- **GPU acceleration** — a one-line switch to `device="cuda"`, `compute_type="float16"`
- **Language selection & translation** — Whisper supports both out of the box
- **A job queue** to handle multiple concurrent uploads

## License

MIT — free to use, modify, and learn from.

---

<div align="center">
<sub>Built with FastAPI, faster-whisper, and ffmpeg. Runs entirely on your machine.</sub>
</div>
