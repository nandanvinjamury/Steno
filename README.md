# 🎙️ Steno

Video-to-script stenographer: a local, offline video and audio transcription web app. No API keys, no cloud, nothing leaves your machine, free to run.

Upload a 500 MB video and the transcript streams into your browser as the model produces it.

## 💡 Why I Built This

Most transcription tools are cloud services that charge per minute and send your recordings to someone else's servers, or command-line utilities with no interface. I wanted one that runs entirely on local hardware but still works through a browser.

Steno runs the whole pipeline locally with open-source models: audio extraction, speech recognition, and live streaming of results. A 500 MB interview, lecture, or podcast goes in; a transcript comes out, appearing as the model works rather than after the run finishes.

## ⚡ How the Streaming Works

As the speech model recognizes each chunk of audio, that text appears in the browser right away instead of being buffered and sent at the end. Doing that on top of a synchronous, CPU-bound model took a few specific choices.

`faster-whisper.transcribe()` is a blocking generator. Iterating it inside an async endpoint would freeze the server's event loop, so Steno runs the pipeline in a worker thread that pushes events onto a thread-safe `queue.Queue`. The async Server-Sent Events endpoint drains that queue and streams to the browser, so the event loop stays responsive and segments go out as they are produced.

Uploads are read in 1 MB chunks and written straight to a temp file on disk, so the server never holds the whole video in RAM. A two-phase flow separates the large binary upload from the live event stream: `POST /upload` saves the file and returns a job id, then `GET /transcribe/{job_id}` opens the `EventSource` stream. SSE cannot ride on a multipart POST response, which is why the two are split.

Before recognition, `ffmpeg` reduces a 500 MB video to roughly 50 MB of 16 kHz mono WAV. The model runs `int8`-quantized for usable CPU speed, with voice-activity detection to skip silence. Temp files are removed in a `finally` block whether the run succeeds or fails. Missing `ffmpeg`, corrupt or unsupported files, and model-load failures each return a specific message to the UI rather than a stack trace.

The streaming was tested end to end against a running server, not just compiled: a spoken video was pushed through, and per-event timestamps showed segments arriving incrementally, with later segments landing seconds after earlier ones.

## 🧰 Tech Stack

| Layer | Choice | Reason |
| --- | --- | --- |
| Backend | FastAPI + Uvicorn | Async, streaming responses, little boilerplate |
| Speech recognition | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper `medium`, `int8`) | Whisper-quality output, runs on CPU |
| Audio extraction | `ffmpeg` via subprocess | Reads any video/audio format; normalizes to 16 kHz mono |
| Streaming | Server-Sent Events | Native browser `EventSource` for one-way live updates |
| Frontend | Vanilla JS + Tailwind (CDN) | No build step, single `index.html` |

No databases, no message brokers, no external services. The system is three Python files and one HTML file.

## 🎬 Demo

<!-- Add a screen recording or GIF here showing the transcript streaming in live. -->
<!-- e.g. ![Steno demo](docs/demo.gif) -->

```
+-----------------------------+-----------------------------+
|  Drop a video / audio file  |  Transcript         0 words |
|  +-----------------------+  |  +-----------------------+  |
|  |   Click or drag here  |  |  | Your transcript       |  |
|  +-----------------------+  |  | appears here, live,   |  |
|                            |  | as it is generated.   |  |
|  interview.mp4   487 MB    |  |                       |  |
|  [    Transcribe    ]      |  +-----------------------+  |
|  Transcribing...           |                             |
|  Live preview:             |  [   Copy   ] [ Download ]  |
|  "Hello there, today we"   |                             |
+-----------------------------+-----------------------------+
```

## 🚀 Quick Start

### 1. Install ffmpeg

ffmpeg must be installed and on your `PATH`.

Windows:
```powershell
winget install Gyan.FFmpeg
# or: choco install ffmpeg
```
macOS:
```bash
brew install ffmpeg
```
Linux (Debian/Ubuntu):
```bash
sudo apt update && sudo apt install ffmpeg
```
Verify: `ffmpeg -version`

### 2. Install and Run

```bash
cd transcriber

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies and launch
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://localhost:8000 and drop in a file.

The first run downloads the Whisper `medium` model (~1.5 GB) and caches it during the "Loading model" step. This happens once; later runs reuse the cached model.

## 🔧 How It Works

```
 Browser                    FastAPI                  Worker thread
 -------                    -------                  -------------
 1. POST /upload  ------->  stream to disk (1 MB chunks) -> temp file
                  <-------  { job_id }
 2. EventSource           +---------------------------------------+
    GET /transcribe/{id}  |  spawn worker, drain queue.Queue      |
                          |                                       |
                  <- SSE -|  status:  "Extracting audio"  <-- ffmpeg -> 16kHz WAV
                  <- SSE -|  status:  "Loading model"     <-- load faster-whisper
                  <- SSE -|  segment: "Hello there."      <-- |
                  <- SSE -|  segment: "This is a test"    <-- | generator yields,
                  <- SSE -|  segment: ...                 <-- | pushed live
                  <- SSE -|  done:    "<full transcript>" <-- join + cleanup
                          +---------------------------------------+
 3. UI appends each segment to the transcript as it arrives; temp files deleted.
```

## 📂 Project Structure

```
Steno/
+-- README.md
+-- transcriber/
    +-- main.py            # FastAPI: serves UI, streams uploads, streams SSE
    +-- transcribe.py      # ffmpeg + faster-whisper pipeline (worker thread, queue)
    +-- static/
    |   +-- index.html     # Single-page frontend (vanilla JS + Tailwind)
    +-- requirements.txt
```

## ✨ Features

- 🎞️ Accepts any video or audio file; ffmpeg handles the conversion.
- ⚡ Segments stream to the browser as they are recognized.
- 🔒 Runs locally; nothing is uploaded anywhere, and it works offline after setup.
- 💸 No per-minute API billing.
- 📋 Copy the transcript or download it as a `.txt` named after the source file.
- 🔢 Live word count, with a transcript you can edit in place.
- 🧹 Temp files are removed after every run.
- 📱 Two-column layout on wide screens, single column on narrow ones.

## 🗺️ Possible Extensions

In rough priority order:

- Timestamps and subtitle export (`.srt`, `.vtt`); faster-whisper already returns per-segment timing.
- Speaker diarization (who said what) via `pyannote`.
- GPU support, by switching to `device="cuda"` and `compute_type="float16"`.
- Language selection and translation, both of which Whisper supports.
- A job queue for multiple concurrent uploads.

## 📄 License

MIT.
