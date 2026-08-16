"""
Video Stitcher Module.
Constructs and executes complex multi-input FFmpeg filter graphs to flawlessly merge
processed audio, trimmed video segments, 16:9 crops, and crossfade transitions
in a single pass on the GPU.
"""
import os
import subprocess
from .audio_handler import run_ffmpeg, FFMPEG_EXE
from .logger import get_logger

def trim_crop_and_stitch(input_video, input_audio, segments_to_keep, crop_params, output_video, transition_duration=0.5):
    """
    Executes a single-pass FFmpeg command to trim segments, crop to 16:9,
    merge the processed audio, and apply crossfades.
    """
    crop_w, crop_h, crop_top = crop_params
    logger = get_logger()
    
    if len(segments_to_keep) == 0:
        logger.warning("No segments to keep!")
        return

    logger.info("Generating cut command...")
    if len(segments_to_keep) == 1:
        start, end = segments_to_keep[0]
        run_ffmpeg([
            "-y", "-hwaccel", "cuda", "-c:v", "hevc_cuvid", 
            "-i", input_video, 
            "-i", input_audio,
            "-ss", str(start), "-to", str(end), 
            "-map", "0:v:0", "-vf", f"crop={crop_w}:{crop_h}:0:{crop_top}", 
            "-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "15M",
            "-ss", str(start), "-to", str(end),
            "-map", "1:a:0", "-c:a", "aac", 
            output_video
        ])
        return

    filter_complex = []
    video_labels = []
    audio_labels = []
    
    for i, (start, end) in enumerate(segments_to_keep):
        filter_complex.append(f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS,fps=30,crop={crop_w}:{crop_h}:0:{crop_top}[v{i}]")
        filter_complex.append(f"[1:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a{i}]")
        video_labels.append(f"[v{i}]")
        audio_labels.append(f"[a{i}]")
        
    last_v = video_labels[0]
    last_a = audio_labels[0]
    current_duration = segments_to_keep[0][1] - segments_to_keep[0][0]
    
    for i in range(1, len(segments_to_keep)):
        offset = current_duration - transition_duration
        next_v = video_labels[i]
        next_a = audio_labels[i]
        out_v = f"[v_out{i}]"
        out_a = f"[a_out{i}]"
        
        filter_complex.append(f"{last_v}{next_v}xfade=transition=fade:duration={transition_duration}:offset={offset}{out_v}")
        filter_complex.append(f"{last_a}{next_a}acrossfade=d={transition_duration}{out_a}")
        
        last_v = out_v
        last_a = out_a
        current_duration += (segments_to_keep[i][1] - segments_to_keep[i][0]) - transition_duration
        
    filter_string = "; ".join(filter_complex)
    
    args = [
        "-y", "-hwaccel", "cuda", "-c:v", "hevc_cuvid", 
        "-i", input_video, 
        "-i", input_audio,
        "-filter_complex", filter_string,
        "-map", last_v, "-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "15M",
        "-map", last_a, "-c:a", "aac", 
        output_video
    ]
    logger.info("Executing FFmpeg cut and multiplexing...")
    run_ffmpeg(args)

def concat_clips(clip_paths, final_output):
    """Stitches multiple finalized video clips together."""
    list_path = final_output + ".txt"
    with open(list_path, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")
            
    cmd = [
        FFMPEG_EXE, "-y", "-f", "concat", "-safe", "0",
        "-i", list_path, "-c", "copy", final_output
    ]
    
    logger = get_logger()
    logger.debug(f"Stitching {len(clip_paths)} clips using concat list: {list_path}")
    
    subprocess.run(cmd, check=True)
    os.remove(list_path)
