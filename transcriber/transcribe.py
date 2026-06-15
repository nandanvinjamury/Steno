"""
Transcription pipeline: ffmpeg audio extraction + faster-whisper.

The heavy lifting (ffmpeg subprocess and the faster-whisper generator) is
blocking and CPU-bound, so it runs in a worker thread. Events are pushed onto a
thread-safe queue.Queue that the async SSE endpoint in main.py drains. This keeps
the asyncio event loop free while segments stream out in real time.
"""

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from typing import Optional

# faster-whisper is imported lazily inside the worker so that importing this
# module (and starting the web server) is fast and does not require the model
# library to be present until the first transcription.

# Sentinel pushed onto the queue to signal the producer is finished.
_DONE = object()

# Module-level model cache. Loading the medium model takes time and memory, so we
# load it once and reuse it across requests.
_model = None
_model_lock = threading.Lock()

MODEL_SIZE = "medium"
COMPUTE_TYPE = "int8"  # CPU-efficient quantization


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _extract_audio(input_path: str, output_path: str) -> None:
    """Extract 16kHz mono WAV from any video/audio file using ffmpeg.

    Raises RuntimeError with a friendly message on failure.
    """
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        output_path,
        "-y",
    ]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        # ffmpeg writes diagnostics to stderr; surface the tail of it.
        tail = (proc.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else "unknown ffmpeg error"
        raise RuntimeError(f"Audio extraction failed: {detail}")


def _get_model():
    """Load (once) and return the faster-whisper model."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)
    return _model


def _worker(input_path: str, work_dir: str, q: "queue.Queue") -> None:
    """Producer thread: runs the full pipeline and pushes events onto the queue."""
    wav_path = os.path.join(work_dir, "audio.wav")
    try:
        # 1. ffmpeg check
        if not _ffmpeg_available():
            q.put({
                "type": "error",
                "message": (
                    "ffmpeg was not found on your system. Please install ffmpeg and "
                    "make sure it is on your PATH (see the README for instructions)."
                ),
            })
            return

        # 2. Extract audio
        q.put({"type": "status", "message": "Extracting audio..."})
        try:
            _extract_audio(input_path, wav_path)
        except RuntimeError as e:
            q.put({
                "type": "error",
                "message": (
                    f"{e}. The file may be corrupt or in an unsupported format."
                ),
            })
            return

        # 3. Load model
        q.put({"type": "status", "message": "Loading model..."})
        try:
            model = _get_model()
        except Exception as e:  # noqa: BLE001 - report any model load failure
            q.put({
                "type": "error",
                "message": f"Failed to load the Whisper model: {e}",
            })
            return

        # 4. Transcribe (streaming generator)
        q.put({"type": "status", "message": "Transcribing..."})
        try:
            segments, _info = model.transcribe(
                wav_path,
                beam_size=5,
                vad_filter=True,
            )
            parts = []
            for segment in segments:
                text = segment.text
                parts.append(text)
                q.put({"type": "segment", "text": text})

            transcript = "".join(parts).strip()
            q.put({"type": "done", "transcript": transcript})
        except Exception as e:  # noqa: BLE001 - report any transcription failure
            q.put({
                "type": "error",
                "message": f"Transcription failed: {e}",
            })
            return
    finally:
        # 8. Clean up all temp files (the whole work dir, including input + wav).
        q.put(_DONE)


def stream_transcription(input_path: str, work_dir: str):
    """Generator yielding SSE-ready event dicts as transcription progresses.

    Runs the blocking pipeline in a worker thread and yields each event as it is
    produced. The caller is responsible for SSE-formatting and for cleaning up
    `work_dir` after the generator is exhausted.
    """
    q: "queue.Queue" = queue.Queue()
    thread = threading.Thread(
        target=_worker, args=(input_path, work_dir, q), daemon=True
    )
    thread.start()

    while True:
        event = q.get()
        if event is _DONE:
            break
        yield event

    thread.join(timeout=1)


def sse_format(event: dict) -> str:
    """Format an event dict as a single SSE message."""
    return f"data: {json.dumps(event)}\n\n"
