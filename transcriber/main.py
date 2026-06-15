"""
FastAPI app: serves the frontend, accepts large file uploads (streamed to disk),
and streams transcription progress over Server-Sent Events.

Flow:
  1. Browser POSTs the file to /upload (streamed to disk, never buffered in
     memory). Returns a job_id.
  2. Browser opens an EventSource on /transcribe/{job_id}, which runs the
     pipeline and streams SSE events as segments arrive.
  3. Temp files are removed in a finally block once the stream ends.
"""

import os
import shutil
import tempfile
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse

from transcribe import stream_transcription, sse_format

app = FastAPI(title="Local Video Transcriber")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# In-memory registry of uploaded jobs: job_id -> {"dir": ..., "path": ..., "name": ...}
# Fine for a single-user local app.
_jobs: dict[str, dict] = {}

# 1 MB chunks when streaming the upload to disk.
_CHUNK = 1024 * 1024


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Stream an uploaded file to a temp dir without buffering it in memory."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    job_id = uuid.uuid4().hex
    work_dir = tempfile.mkdtemp(prefix="transcriber_")
    # Preserve the original extension so ffmpeg can detect the format.
    _, ext = os.path.splitext(file.filename)
    dest_path = os.path.join(work_dir, f"input{ext}")

    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Failed to save upload.")
    finally:
        await file.close()

    _jobs[job_id] = {"dir": work_dir, "path": dest_path, "name": file.filename}
    return JSONResponse({"job_id": job_id})


@app.get("/transcribe/{job_id}")
async def transcribe(job_id: str):
    """Stream transcription progress for a previously uploaded job as SSE."""
    job = _jobs.pop(job_id, None)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job.")

    work_dir = job["dir"]
    input_path = job["path"]

    def event_stream():
        try:
            for event in stream_transcription(input_path, work_dir):
                yield sse_format(event)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # disable proxy buffering if present
    }
    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=headers
    )
