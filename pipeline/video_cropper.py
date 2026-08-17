"""
Video Cropper Module.
Calculates crop coordinate math for 16:9 extracts from a 4K 4:3 dashcam canvas.
Reads dynamic Y-mark coordinates established by the AI object detection.
"""
import json

def get_crop_dimensions(crop_y=None):
    """
    Calculate crop parameters for a 16:9 4K extract (2592x1458).
    Returns (crop_w, crop_h, crop_top)
    """
    crop_w, crop_h = 2592, 1458
    
    if crop_y is None:
        try:
            with open(r"D:\Dashcam\project_config.json") as f:
                config = json.load(f)
            crop_top = config["established_crops"]["production_16_9"]["crop_top_y"]
            crop_y = crop_top + crop_h
        except:
            crop_y = 1944 * 0.75 # fallback

    crop_top = max(0, int(crop_y - crop_h))
    return crop_w, crop_h, crop_top
