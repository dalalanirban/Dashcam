"""
Motion Trimmer Module.
Analyzes dashcam footage to detect periods of stop-and-go traffic (e.g., at red lights).
Generates an optimized FFmpeg proxy video and runs Farneback Optical Flow on the GPU
to detect motion magnitudes, returning timestamps of dynamic segments to keep.
"""
import os
import cv2
import numpy as np
from .audio_handler import run_ffmpeg
from .logger import get_logger

def get_video_duration(video_path):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return frames / fps

def analyze_motion(video_path, crop_y, threshold=1.0, min_stop_duration=5.0, progress_callback=None):
    """
    Main entry point for motion analysis.
    1. Extracts a 640x360 proxy video strictly centered on the road.
    2. Analyzes optical flow vectors across frames.
    3. Identifies contiguous segments where average flow < threshold for >= min_stop_duration.
    
    Returns:
        List of tuples: [(start_time_sec, end_time_sec), ...] representing segments where the car is STOPPED.
    """
    logger = get_logger()
    logger.info(f"Analyzing motion for: {video_path}")
    
    # Determine crop top
    crop_w, crop_h = 2592, 1458
    crop_top = 326
    if crop_y is not None:
        crop_top = max(0, int(crop_y - crop_h))
        
    proxy_path = video_path + ".proxy.mp4"
    logger.debug(f"Generating low-res proxy for motion analysis: {proxy_path}")
    run_ffmpeg([
        "-y", "-hwaccel", "cuda", "-c:v", "hevc_cuvid", "-i", video_path,
        "-vf", f"crop={crop_w}:{crop_h}:0:{crop_top},scale=640:360",
        "-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "2M", "-an",
        proxy_path
    ])

    cap = cv2.VideoCapture(proxy_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or not np.isfinite(fps):
        fps = 30.0
        
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    frame_skip = int(fps / 5)
    if frame_skip < 1: frame_skip = 1
    sample_fps = fps / frame_skip
    
    ret, prev_frame = cap.read()
    if not ret: 
        if os.path.exists(proxy_path): os.remove(proxy_path)
        return []

    def process_frame(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        roi_y1 = int(h * 0.3)
        roi_y2 = int(h * 0.9)
        roi_x1 = int(w * 0.1)
        roi_x2 = int(w * 0.9)
        return gray[roi_y1:roi_y2, roi_x1:roi_x2]

    prev_gray = process_frame(prev_frame)
    frame_idx = 0
    motion_magnitudes = []
    
    logger.info("Calculating optical flow...")
    use_cuda = False
    try:
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            use_cuda = True
            cuda_prev_gray = cv2.cuda_GpuMat()
            cuda_gray = cv2.cuda_GpuMat()
            cuda_flow = cv2.cuda_FarnebackOpticalFlow.create()
    except:
        pass

    while True:
        ret, frame = cap.read()
        if not ret: break
        frame_idx += 1
        
        if frame_idx % int(fps * 2) == 0 and progress_callback and frames > 0:
            pct = 20 + (frame_idx / frames) * 30
            progress_callback("Motion Analysis", pct)
            
        if frame_idx % frame_skip != 0: continue
            
        gray = process_frame(frame)
        if use_cuda:
            cuda_prev_gray.upload(prev_gray)
            cuda_gray.upload(gray)
            flow = cuda_flow.calc(cuda_prev_gray, cuda_gray, None)
            flow_host = flow.download()
            mag, _ = cv2.cartToPolar(flow_host[..., 0], flow_host[..., 1])
        else:
            flow = cv2.calcOpticalFlowFarneback(prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            
        mean_mag = np.mean(mag)
        motion_magnitudes.append((frame_idx / fps, mean_mag))
        prev_gray = gray
        
    cap.release()
    
    window_size = int(2.0 * sample_fps)
    if window_size % 2 == 0: window_size += 1
    mags = [m for t, m in motion_magnitudes]
    smoothed_mags = np.convolve(mags, np.ones(window_size)/window_size, mode='same')
    
    is_stopped = smoothed_mags < threshold
    stopped_segments = []
    current_start = None
    
    for i, stopped in enumerate(is_stopped):
        time_sec = motion_magnitudes[i][0]
        if stopped and current_start is None:
            current_start = time_sec
        elif not stopped and current_start is not None:
            if (time_sec - current_start) >= min_stop_duration:
                stopped_segments.append((current_start, time_sec))
            current_start = None
            
    if current_start is not None:
        time_sec = motion_magnitudes[-1][0]
        if (time_sec - current_start) >= min_stop_duration:
            stopped_segments.append((current_start, time_sec))

    if os.path.exists(proxy_path):
        os.remove(proxy_path)

    return stopped_segments
