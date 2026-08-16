import logging
import os
import time

def setup_logger():
    """
    Configures the central logger for the Dashcam pipeline.
    Creates a unique log file for each run in the out/log directory.
    """
    logger = logging.getLogger("dashcam")
    logger.setLevel(logging.DEBUG)
    
    # Reset handlers if they exist so each run gets a fresh file handler
    if logger.handlers:
        logger.handlers.clear()
        
    log_dir = r"D:\Dashcam\out\log"
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"run_{timestamp}.log")
    
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(module)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    logger.info(f"Logger initialized. Logging to: {log_file}")
    
    return logger

def get_logger():
    """Returns the pre-configured dashcam logger."""
    return logging.getLogger("dashcam")
