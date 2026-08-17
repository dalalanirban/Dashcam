"""
Audio Handler Module.
Responsible for interacting with FFmpeg and Demucs to extract, process,
and clean audio tracks by isolating road noise from cabin speech.
"""
import os
import subprocess
import sys
import imageio_ffmpeg
from .logger import get_logger

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

def run_ffmpeg(args):
    command = [FFMPEG_EXE] + args
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        logger = get_logger()
        logger.error(f"FFmpeg error:\n{result.stderr}")
        raise RuntimeError("FFmpeg command failed.")
    return result

def strip_audio(video_path, output_audio_path):
    """Extract raw audio from video using GPU decode."""
    logger = get_logger()
    logger.info(f"Extracting raw audio to {output_audio_path}...")
    run_ffmpeg([
        "-y", "-hwaccel", "cuda", "-c:v", "hevc_cuvid", 
        "-i", video_path, 
        "-map", "0:a:0", "-c:a", "pcm_s16le", 
        output_audio_path
    ])
    return output_audio_path

def process_audio(raw_audio_path, output_dir):
    """Run Demucs to isolate background noise from vocals."""
    logger = get_logger()
    logger.info("Running Demucs to separate vocals from background noise (GPU)...")
    subprocess.run([
        sys.executable, "-m", "demucs.separate",
        raw_audio_path,
        "--two-stems=vocals",
        "-d", "cuda",
        "-o", output_dir
    ], check=True)
    
    basename = os.path.splitext(os.path.basename(raw_audio_path))[0]
    processed_audio = os.path.join(output_dir, "htdemucs", basename, "no_vocals.wav")
    return processed_audio
