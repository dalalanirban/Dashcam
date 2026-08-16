"""
Orchestrator Module.
Provides the central processing function that manages the execution flow
for a single dashcam video clip. Sequentially invokes audio extraction,
motion analysis, cropping, and GPU stitching.
"""
import os
import tempfile
import shutil
from .logger import get_logger
from .audio_handler import strip_audio, process_audio
from .motion_trimmer import get_video_duration, analyze_motion
from .video_cropper import get_crop_dimensions
from .video_stitcher import trim_crop_and_stitch

def process_clip(input_video, output_video, crop_y=None, progress_callback=None):
    """
    Orchestrates the pipeline for a single clip.
    """
    temp_base = r"D:\Dashcam\out\temp"
    os.makedirs(temp_base, exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=temp_base)
    logger = get_logger()
    logger.info(f"Starting orchestration for: {input_video}")
    logger.debug(f"Created temp directory: {temp_dir}")
    
    try:
        # Step 1 & 2: Strip Audio & Process Audio
        if progress_callback: progress_callback("Audio Processing", 10)
        temp_raw_audio = os.path.join(temp_dir, "temp_raw_audio.wav")
        strip_audio(input_video, temp_raw_audio)
        clean_audio = process_audio(temp_raw_audio, temp_dir)
        
        # Step 3: Analyze Motion (Trimmer)
        if progress_callback: progress_callback("Motion Analysis", 20)
        stopped_segments = analyze_motion(
            input_video, crop_y, threshold=1.0, min_stop_duration=5.0, progress_callback=progress_callback
        )
        if progress_callback: progress_callback("Motion Analysis", 50)
        
        # Determine final segments
        duration = get_video_duration(input_video)
        segments_to_keep = []
        last_time = 0.0
        for start, end in stopped_segments:
            logger.info(f"Detected Stop: {start:.1f}s to {end:.1f}s")
            keep_end = start + 1.0
            segments_to_keep.append((last_time, keep_end))
            last_time = end
        segments_to_keep.append((last_time, duration))
        
        # Step 4: Crop Dimensions
        crop_params = get_crop_dimensions(crop_y)
        
        # Step 5 & 6: Execute Trim, Crop, and Stitch Audio
        if progress_callback: progress_callback("Video Cutting", 60)
        trim_crop_and_stitch(input_video, clean_audio, segments_to_keep, crop_params, output_video)
        
        if progress_callback: progress_callback("Final Stitching", 90)
        
    finally:
        try:
            shutil.rmtree(temp_dir)
            logger.debug(f"Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Cleanup error for {temp_dir}: {e}")
