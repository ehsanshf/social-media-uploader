import os
import logging
import yt_dlp
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("reuploader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def download_video(video_url):
    """Download a video using yt-dlp (more robust than pytube)"""
    try:
        # Extract video ID
        video_id = video_url.split("=")[-1].split("&")[0]
        
        # Simple filename to avoid path issues
        filename = f"video_{video_id}.mp4"
        filepath = os.path.join("/tmp/videos", filename)  # Use /tmp for reliable write access
        
        # Ensure directory exists
        os.makedirs("/tmp/videos", exist_ok=True)
        
        # Configure yt-dlp options 
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': filepath,
            'quiet': False,
            'verbose': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Referer': 'https://www.youtube.com/'
            }
        }
        
        logger.info(f"Attempting to download video {video_id} to {filepath}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # Verify download success
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logger.info(f"Download successful: {filepath} ({os.path.getsize(filepath)} bytes)")
            return filepath
        else:
            logger.error(f"Download failed or file empty: {filepath}")
            return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

download_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")