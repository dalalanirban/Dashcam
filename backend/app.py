from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import cv2
import base64
import os
import glob
import subprocess
import sys
import json
import asyncio
import time
import threading
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add root directory to path to import pipeline
sys.path.insert(0, r"D:\Dashcam")
from pipeline import orchestrator
from pipeline import video_stitcher
from pipeline.logger import setup_logger, get_logger

import imageio_ffmpeg
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

app = FastAPI()

RAW_DIR = r"D:\Dashcam\Raw_Footages\Front"
OUTPUT_DIR = r"D:\Dashcam\out\Processed_Dashcam"
app.mount("/out", StaticFiles(directory=OUTPUT_DIR), name="out")

# ---------------------------------------------------------------------------
# Global SSE progress state
# ---------------------------------------------------------------------------
progress_state = {
    "overall_percent": 0,
    "clips": {},
    "done": False,
    "error": None,
    "final_video_url": None,
}
_progress_lock = threading.Lock()


def _reset_progress():
    """Reset progress state for a new processing run."""
    with _progress_lock:
        progress_state["overall_percent"] = 0
        progress_state["clips"] = {}
        progress_state["done"] = False
        progress_state["error"] = None
        progress_state["final_video_url"] = None


def _update_clip_progress(clip_name: str, phase: str, percent: float):
    """Thread-safe update of a single clip's progress."""
    with _progress_lock:
        progress_state["clips"][clip_name] = {
            "phase": phase,
            "percent": round(percent, 1),
        }
        # Recompute overall percent as average of all clip percents
        clip_values = progress_state["clips"].values()
        if clip_values:
            progress_state["overall_percent"] = round(
                sum(c["percent"] for c in clip_values) / len(clip_values), 1
            )


def _mark_done(error: Optional[str] = None, final_video_url: Optional[str] = None):
    """Mark processing as finished (or failed)."""
    with _progress_lock:
        progress_state["done"] = True
        if error:
            progress_state["error"] = error
        else:
            progress_state["overall_percent"] = 100
            if final_video_url:
                progress_state["final_video_url"] = final_video_url


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class FrameRequest(BaseModel):
    file: str


class Clip(BaseModel):
    file: str
    bonnetY: int


class ProcessRequest(BaseModel):
    clips: List[Clip]


# ---------------------------------------------------------------------------
# GET /api/files – list MP4 files sorted by name
# ---------------------------------------------------------------------------
@app.get("/api/files")
def get_files():
    # List and sort chronologically based on filename
    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.MP4")))
    return {"files": [os.path.basename(f) for f in files]}


# ---------------------------------------------------------------------------
# POST /api/frame – extract a single frame for preview
# ---------------------------------------------------------------------------
@app.post("/api/frame")
def get_frame(req: FrameRequest):
    filepath = os.path.join(RAW_DIR, req.file)
    if not os.path.exists(filepath):
        return {"error": "File not found"}

    # Use FFmpeg to extract frame 100 quickly using the GPU
    # This prevents the 10-15 minute CPU decoding hangs seen with OpenCV
    try:
        cap = cv2.VideoCapture(filepath)
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return {"error": "Could not read frame"}

        orig_h, orig_w = frame.shape[:2]

        # Downscale to 1200px width for the browser preview
        # This massively reduces the base64 payload size
        preview_w = 1200
        scale = preview_w / orig_w
        preview_h = int(orig_h * scale)
        preview = cv2.resize(frame, (preview_w, preview_h))

        _, buffer = cv2.imencode('.jpg', preview, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        img_b64 = base64.b64encode(buffer).decode('utf-8')

        print(f"Frame extracted: {orig_w}x{orig_h}, preview: {preview_w}x{preview_h}, b64 size: {len(img_b64)} bytes")

        return {
            "image_b64": img_b64,
            "width": orig_w,
            "height": orig_h,
            "preview_width": preview_w,
            "preview_height": preview_h,
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# GET /api/progress – SSE stream of progress updates
# ---------------------------------------------------------------------------
@app.get("/api/progress")
async def progress_stream():
    """Server-Sent Events endpoint that streams progress_state as JSON every second."""

    async def event_generator():
        while True:
            with _progress_lock:
                snapshot = json.dumps(progress_state)
            yield f"data: {snapshot}\n\n"
            # Stop streaming once processing is done
            if progress_state.get("done"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Processing helpers
# ---------------------------------------------------------------------------
def _make_progress_callback(clip_name: str):
    """Return a callback function that smart_editor can call to report progress."""

    def callback(phase: str, percent: float):
        _update_clip_progress(clip_name, phase, percent)

    return callback


def _process_single_clip(clip: Clip) -> str:
    """
    Process one clip through smart_editor.main().
    Returns the path to the processed output file.
    """
    clip_name = clip.file
    input_path = os.path.join(RAW_DIR, clip_name)
    base, ext = os.path.splitext(clip_name)
    output_path = os.path.join(OUTPUT_DIR, f"{base}_processed{ext}")

    _update_clip_progress(clip_name, "starting", 0)

    orchestrator.process_clip(
        input_video=input_path,
        output_video=output_path,
        crop_y=clip.bonnetY,
        progress_callback=_make_progress_callback(clip_name),
    )
    _update_clip_progress(clip_name, "done", 100)
    return output_path

def _run_pipeline(clips: List[Clip]):
    """
    Main processing pipeline (runs in a background thread).
    Processes clips in parallel with ThreadPoolExecutor(max_workers=2),
    then stitches results in chronological order.
    """
    logger = setup_logger()
    logger.info(f"Starting pipeline run for {len(clips)} clips")
    
    _reset_progress()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Sort clips chronologically by filename (filenames contain datetime stamps)
    sorted_clips = sorted(clips, key=lambda c: c.file)

    try:
        # Map from clip filename → output path (preserving order)
        output_map: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_to_clip = {
                executor.submit(_process_single_clip, clip): clip
                for clip in sorted_clips
            }

            for future in as_completed(future_to_clip):
                clip = future_to_clip[future]
                try:
                    out_path = future.result()
                    output_map[clip.file] = out_path
                    logger.info(f"[SUCCESS] Finished: {clip.file} → {out_path}")
                except Exception as exc:
                    logger.error(f"[FAILED] Failed: {clip.file} — {exc}", exc_info=True)
                    _mark_done(error=f"Clip {clip.file} failed: {exc}")
                    return

        # Stitch in chronological order
        ordered_outputs = [output_map[c.file] for c in sorted_clips]
        final_output = os.path.join(
            OUTPUT_DIR,
            f"final_stitched_{time.strftime('%Y%m%d_%H%M%S')}.mp4",
        )
        
        if len(ordered_outputs) == 1:
            import shutil
            shutil.copy2(ordered_outputs[0], final_output)
            logger.info("Only one clip processed. Bypassing FFmpeg stitch.")
        else:
            logger.info(f"Stitching {len(ordered_outputs)} clips → {final_output}")
            video_stitcher.concat_clips(ordered_outputs, final_output)

        logger.info(f"Pipeline complete → {final_output}")
        # Mount path is /out, directory is OUTPUT_DIR, so just append basename
        final_url = f"/out/{os.path.basename(final_output)}"
        _mark_done(final_video_url=final_url)

    except Exception as e:
        logger = get_logger()
        logger.error(f"Pipeline fatal error: {e}", exc_info=True)
        _mark_done(error=str(e))


# ---------------------------------------------------------------------------
# POST /api/process – kick off parallel processing
# ---------------------------------------------------------------------------
@app.post("/api/process")
def process_clips(req: ProcessRequest):
    if not req.clips:
        return {"error": "No clips provided"}

    # Launch pipeline in a daemon thread so the endpoint returns immediately
    thread = threading.Thread(target=_run_pipeline, args=(req.clips,), daemon=True)
    thread.start()

    return {"message": f"Processing {len(req.clips)} clip(s) in background."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
