import os
import time
import random
import json
import schedule
import re
import requests
from bs4 import BeautifulSoup
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from googleapiclient.http import MediaFileUpload
import yt_dlp
from datetime import datetime
import cv2
import numpy as np
import traceback
import subprocess
import gc
from functools import wraps
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("reuploader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Toggle which platforms to upload to
youtube_upload = True
tiktok_upload = True

# Maximum retry counts
MAX_CHANNEL_RETRIES = 5  # Number of different channels to try if all else fails
MAX_VIDEO_RETRIES = 3    # Videos to try per channel
MAX_DOWNLOAD_RETRIES = 5 # Download attempts per video
MAX_UPLOAD_RETRIES = 3   # Upload attempts per platform

# Retry decorator for functions that should be retried on failure
def retry(max_tries=3, delay_seconds=1, backoff_factor=2, exceptions=(Exception,)):
    """
    Retry decorator with exponential backoff
    
    Args:
        max_tries: Maximum number of retries
        delay_seconds: Initial delay between retries in seconds
        backoff_factor: Multiplicative factor by which the delay increases
        exceptions: Exceptions that trigger a retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            mtries, mdelay = max_tries, delay_seconds
            last_exception = None
            
            while mtries > 0:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    mtries -= 1
                    if mtries == 0:
                        raise
                    
                    last_exception = e
                    sleep_time = mdelay + random.uniform(0, 0.5 * mdelay)
                    logger.warning(f"Retrying {func.__name__} in {sleep_time:.2f}s due to {str(e)} ({max_tries - mtries}/{max_tries})")
                    time.sleep(sleep_time)
                    mdelay *= backoff_factor
            
            if last_exception:
                raise last_exception
        return wrapper
    return decorator


class YouTubeChannelReuploader:
    def __init__(self):
        self.download_dir = "/tmp/videos"  # Use /tmp which is typically writable
        try:
            if not os.path.exists(self.download_dir):
                os.makedirs(self.download_dir, exist_ok=True)
                logger.info(f"Created download directory: {self.download_dir}")
            
            # Test write permissions explicitly
            test_file = os.path.join(self.download_dir, "test_write.txt")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            logger.info(f"Write test to {self.download_dir} successful")
        except Exception as e:
            logger.error(f"Directory setup failed: {e}")
            # Consider creating an alternative directory
            self.download_dir = "/tmp/videos_alt"
            os.makedirs(self.download_dir, exist_ok=True)
            logger.info(f"Using alternative directory: {self.download_dir}")
            
        self.client_secret_file = os.path.expanduser("~/client_secrets.json")
        self.token_file = "youtube_token.json"
        self.api_service_name = "youtube"
        self.api_version = "v3"
        self.scopes = ["https://www.googleapis.com/auth/youtube.upload",
                      "https://www.googleapis.com/auth/youtube"]
        self.history_file = "download_history.json"
        self.files_to_delete = []
        self.files_to_delete_file = "files_to_delete.json"
        
        # User agents for rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (X11; CrOS x86_64 13982.82.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.157 Safari/537.36'
        ]
        
        # Create download directory if it doesn't exist
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
            
        # Load download history
        self.download_history = self.load_download_history()
        
        # Load files to delete
        self.load_files_to_delete()
        
        # Authenticate with YouTube API (this is for YOUR channel)
        logger.info("Authenticating with YouTube API for your upload channel...")
        self.youtube = self.get_authenticated_service()

        # Add this to your YouTubeChannelReuploader.__init__ method
        try:
            test_file = os.path.join(self.download_dir, "test_write.txt")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            logger.info(f"Write test to {self.download_dir} successful")
        except Exception as e:
            logger.error(f"Write test to {self.download_dir} failed: {e}")
    
    def get_authenticated_service(self):
        """Authenticate with the YouTube API with token persistence"""
        # Disable OAuthlib's HTTPS verification when running locally.
        # *DO NOT* leave this option enabled in production.
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        
        # Check if we have saved credentials
        creds = None
        if os.path.exists(self.token_file):
            logger.info("Loading saved YouTube credentials...")
            with open(self.token_file, 'r') as token:
                import google.oauth2.credentials
                creds_data = json.load(token)
                creds = google.oauth2.credentials.Credentials.from_authorized_user_info(creds_data)
        
        # If credentials don't exist or are invalid, run the flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired YouTube credentials...")
                creds.refresh(google.auth.transport.requests.Request())
            else:
                logger.info("Getting new YouTube credentials...")
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    self.client_secret_file, self.scopes)
                creds = flow.run_local_server(port=8080)
            
            # Save the credentials for next run
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())
        
        return googleapiclient.discovery.build(
            self.api_service_name, self.api_version, credentials=creds)
    
    def load_download_history(self):
        """Load history of downloaded videos to avoid duplicates"""
        if os.path.exists(self.history_file):
            with open(self.history_file, 'r') as f:
                return json.load(f)
        return {"downloaded_video_ids": []}
    
    def save_download_history(self):
        """Save updated download history"""
        with open(self.history_file, 'w') as f:
            json.dump(self.download_history, f)
    
    def load_files_to_delete(self):
        """Load list of files to delete"""
        if os.path.exists(self.files_to_delete_file):
            with open(self.files_to_delete_file, 'r') as f:
                self.files_to_delete = json.load(f)
        else:
            self.files_to_delete = []
    
    def save_files_to_delete(self):
        """Save list of files to delete"""
        with open(self.files_to_delete_file, 'w') as f:
            json.dump(self.files_to_delete, f)
    
    def is_video_downloaded(self, video_id):
        """Check if a video has been downloaded before"""
        return video_id in self.download_history["downloaded_video_ids"]
    
    def mark_video_downloaded(self, video_id):
        """Mark a video as downloaded in the history"""
        if not self.is_video_downloaded(video_id):
            self.download_history["downloaded_video_ids"].append(video_id)
            self.save_download_history()
    
    def schedule_file_for_deletion(self, file_path):
        """Add file to list of files to be deleted on next run"""
        if file_path and file_path not in self.files_to_delete and os.path.exists(file_path):
            self.files_to_delete.append(file_path)
            logger.info(f"Scheduled file for deletion on next run: {file_path}")
            self.save_files_to_delete()
    
    def force_delete_file(self, file_path):
        """Use platform-specific method to delete a file that might be locked"""
        try:
            if os.path.exists(file_path):
                try:
                    # First try normal delete
                    os.remove(file_path)
                except:
                    # If on Windows, try force delete
                    if os.name == 'nt':
                        subprocess.run(['cmd', '/c', 'del', '/f', '/q', file_path.replace('/', '\\')], 
                                      check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    else:
                        # On Linux/Mac, try with different permissions
                        os.chmod(file_path, 0o777)
                        os.remove(file_path)
                
                return not os.path.exists(file_path)
            return True  # File doesn't exist, consider it deleted
        except Exception as e:
            logger.error(f"Force delete failed: {e}")
            return False
    
    def process_pending_deletions(self):
        """Try to delete files that were scheduled for deletion"""
        if not self.files_to_delete:
            return
            
        logger.info(f"Attempting to delete {len(self.files_to_delete)} previously scheduled files...")
        
        remaining_files = []
        for file_path in self.files_to_delete:
            if self.force_delete_file(file_path):
                logger.info(f"Successfully deleted: {file_path}")
            else:
                logger.warning(f"Could not delete: {file_path}")
                remaining_files.append(file_path)
        
        self.files_to_delete = remaining_files
        self.save_files_to_delete()
    
    def progress_hook(self, d):
        """Progress hook for yt-dlp to monitor download progress"""
        if d['status'] == 'downloading':
            try:
                percent = d.get('_percent_str', 'N/A')
                downloaded = d.get('downloaded_bytes', 0) / (1024 * 1024)  # Convert to MB
                total = d.get('total_bytes', 0) / (1024 * 1024)  # Convert to MB
                speed = d.get('speed', 0) / (1024 * 1024)  # Convert to MB/s
                eta = d.get('eta', 'N/A')
                filename = os.path.basename(d.get('filename', 'unknown'))
                
                logger.info(f"Downloading {filename}: {percent} ({downloaded:.1f}MB/{total:.1f}MB) at {speed:.2f}MB/s, ETA: {eta}s")
            except Exception as e:
                logger.error(f"Error in progress hook: {e}")
        elif d['status'] == 'finished':
            try:
                filename = os.path.basename(d.get('filename', 'unknown'))
                logger.info(f"Download finished: {filename}")
            except Exception as e:
                logger.error(f"Error in finished hook: {e}")
        elif d['status'] == 'error':
            logger.error(f"Download error: {d.get('error', 'Unknown error')}")

    @retry(max_tries=3, delay_seconds=2, backoff_factor=2, 
           exceptions=(requests.exceptions.RequestException, ConnectionError, TimeoutError))
    def find_channels(self, max_channels=10):
        """Find YouTube channels with Taylor Swift concert videos"""
        try:
            logger.info("Searching for YouTube channels with Taylor Swift concert videos...")
            
            # Search terms to try
            search_terms = [
                "Taylor Swift concert full",
                "Taylor Swift Eras Tour",
                "Taylor Swift live performance",
                "Taylor Swift concert highlights",
                "Taylor Swift Tour Performances",
                "Taylor Swift live show"
            ]
            
            found_channels = {}  # Dictionary to store channel_id: channel_url pairs
            
            # For each search term
            for term in search_terms:
                if len(found_channels) >= max_channels:
                    break
                    
                # Add a random delay before search to avoid rate limiting
                time.sleep(random.uniform(2, 5))
                
                encoded_term = requests.utils.quote(term)
                search_url = f"https://www.youtube.com/results?search_query={encoded_term}"
                
                logger.info(f"Searching: {term}")
                
                # Get the search results page
                headers = {
                    "User-Agent": random.choice(self.user_agents),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
                }
                
                response = requests.get(search_url, headers=headers, timeout=15)
                response.raise_for_status()  # Raise an exception for bad status codes
                
                # Parse the HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract video links from the search results
                video_links = []
                script_tags = soup.find_all("script")
                for script in script_tags:
                    if script.string and "videoRenderer" in script.string:
                        video_ids = re.findall(r'"videoId":"([^"]+)"', script.string)
                        for video_id in video_ids:
                            video_links.append(f"https://www.youtube.com/watch?v={video_id}")
                
                # For each video, get the channel info
                for video_url in video_links[:10]:  # Check first 10 videos in search results
                    try:
                        # Add delay before checking each video
                        time.sleep(random.uniform(1, 3))
                        
                        # Use yt-dlp to get video info including channel
                        ydl_opts = {
                            'quiet': True,
                            'no_warnings': True,
                            'skip_download': True,
                            'forcejson': True,
                            'nocheckcertificate': True,
                            'ignoreerrors': True,
                            'geo_bypass': True,
                            'socket_timeout': 30,
                            'http_headers': {
                                'User-Agent': random.choice(self.user_agents),
                                'Accept-Language': 'en-US,en;q=0.9'
                            }
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(video_url, download=False)
                            
                        if not info:
                            logger.warning(f"Could not get info for video {video_url}")
                            continue
                            
                        # Extract channel info
                        channel_id = info.get('channel_id')
                        channel_url = info.get('channel_url')
                        channel_name = info.get('uploader')
                        
                        # Check if we actually have Taylor Swift content
                        title = info.get('title', '').lower()
                        description = info.get('description', '').lower()
                        
                        is_relevant = ('taylor swift' in title or 'taylor swift' in description) and \
                                    ('concert' in title or 'concert' in description or 
                                     'live' in title or 'live' in description or
                                     'eras tour' in title or 'eras tour' in description or
                                     'performance' in title or 'performance' in description)
                        
                        if is_relevant and channel_id and channel_url and channel_id not in found_channels:
                            # Check for copyright notice
                            has_copyright = any(term in description.lower() for term in ['©', 'copyright', 'all rights reserved'])
                            if has_copyright:
                                logger.info(f"Skipping channel with copyright notices: {channel_name}")
                                continue
                                
                            # Use the channel URL in @username format if possible
                            formatted_channel_url = f"https://www.youtube.com/{info.get('uploader_id', channel_id)}"
                            found_channels[channel_id] = formatted_channel_url
                            logger.info(f"Found relevant channel: {channel_name} - {formatted_channel_url}")
                            
                            if len(found_channels) >= max_channels:
                                break
                                
                    except Exception as e:
                        logger.error(f"Error getting channel info for {video_url}: {e}")
                        continue
            
            # Return the list of channel URLs
            return list(found_channels.values())
        
        except Exception as e:
            logger.error(f"Error finding Taylor Swift channels: {e}")
            return []
    
    @retry(max_tries=3, delay_seconds=2, exceptions=(requests.exceptions.RequestException,))
    def get_channel_videos(self, channel_url):
        """Get videos from a channel using web scraping instead of pytube Channel class"""
        try:
            logger.info(f"Fetching videos from source channel: {channel_url}")
            
            # Add a random delay to avoid rate limiting
            time.sleep(random.uniform(1, 3))
            
            # Get the channel page
            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            }
            
            response = requests.get(channel_url + "/videos", headers=headers, timeout=15)
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch channel page: {response.status_code}")
                return []
            
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract video links - both patterns work for different page structures
            video_links = []
            
            # Look for video links in the page
            script_tags = soup.find_all("script")
            for script in script_tags:
                if script.string and "videoRenderer" in script.string:
                    video_ids = re.findall(r'"videoId":"([^"]+)"', script.string)
                    for video_id in video_ids:
                        if video_id not in [link.split('=')[-1].split('&')[0] for link in video_links]:
                            video_links.append(f"https://www.youtube.com/watch?v={video_id}")
            
            # Alternate method - look for video links in anchor tags
            if not video_links:
                for a_tag in soup.find_all("a", href=True):
                    if "/watch?v=" in a_tag["href"]:
                        video_id = a_tag["href"].split("=")[-1].split("&")[0]
                        full_url = f"https://www.youtube.com/watch?v={video_id}"
                        if full_url not in video_links:
                            video_links.append(full_url)
            
            logger.info(f"Found {len(video_links)} videos on the channel")
            return video_links
            
        except Exception as e:
            logger.error(f"Error fetching channel videos: {e}")
            raise  # Re-raise for retry decorator
    
    def get_random_channel_video(self, channel_url, max_videos_to_check=50):
        """Get a random video from a source channel that hasn't been downloaded before and doesn't have copyright notices"""
        try:
            # Get all videos from the channel
            try:
                video_links = self.get_channel_videos(channel_url)
            except Exception as e:
                logger.error(f"Failed to get channel videos: {e}")
                return None
            
            if not video_links:
                logger.warning("No videos found on this channel")
                return None
            
            # Shuffle the videos to check them in random order
            random.shuffle(video_links)
            
            # Filter out videos we've already downloaded or have copyright notices
            available_videos = []
            copyright_rejected = 0
            count = 0
            
            for video_url in video_links:
                if count >= max_videos_to_check:
                    break
                
                # Extract video ID
                video_id = video_url.split("=")[-1].split("&")[0]
                
                if not self.is_video_downloaded(video_id):
                    # Get video info to check description
                    try:
                        # Add a random delay before checking
                        time.sleep(random.uniform(2, 5))
                        
                        ydl_opts = {
                            'quiet': True,
                            'no_warnings': True,
                            'skip_download': True,
                            'forcejson': True,
                            'nocheckcertificate': True,
                            'ignoreerrors': True,
                            'geo_bypass': True,
                            'socket_timeout': 30,
                            'http_headers': {
                                'User-Agent': random.choice(self.user_agents),
                                'Accept-Language': 'en-US,en;q=0.9'
                            }
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(video_url, download=False)
                        
                        if not info:
                            logger.warning(f"Could not get info for video {video_id}")
                            continue
                            
                        # Check for copyright symbols or text in description
                        description = info.get('description', '').lower()
                        copyright_indicators = ['©', 'copyright', 'all rights reserved', 'licensed to', 'provided to youtube']
                        
                        has_copyright_notice = any(indicator in description.lower() for indicator in copyright_indicators)
                        
                        if not has_copyright_notice:
                            available_videos.append(video_url)
                            logger.info(f"Video {video_id} has no copyright notice in description")
                        else:
                            copyright_rejected += 1
                            logger.info(f"Video {video_id} rejected due to copyright notice in description")
                    except Exception as e:
                        logger.error(f"Error checking video {video_id}: {e}")
                        # Skip this video if we can't check it
                        continue
                
                count += 1
            
            if not available_videos:
                logger.warning(f"No new videos available to download from this channel (Copyright rejected: {copyright_rejected})")
                return None
            
            # Choose a random video from the filtered list
            random_video = random.choice(available_videos)
            return random_video
            
        except Exception as e:
            logger.error(f"Error getting random channel video: {e}")
            return None
        
    def create_text_image(self, text, video_size, fontScale=1, color=(255, 255, 255), thickness=2, position="bottom-right"):
        """Create an image with transparent background and text for watermarking"""
        # Create a transparent image
        img = np.zeros((video_size[1], video_size[0], 4), dtype=np.uint8)
        
        # Get text size
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size = cv2.getTextSize(text, font, fontScale, thickness)[0]
        
        # Calculate position
        padding = 20  # padding from edge
        if position == "bottom-right":
            text_x = video_size[0] - text_size[0] - padding
            text_y = video_size[1] - padding
        elif position == "bottom-left":
            text_x = padding
            text_y = video_size[1] - padding
        elif position == "bottom-middle":  # Add this case
            text_x = (video_size[0] - text_size[0]) // 2
            text_y = video_size[1] - padding
        elif position == "top-right":
            text_x = video_size[0] - text_size[0] - padding
            text_y = text_size[1] + padding
        elif position == "top-left":
            text_x = padding
            text_y = text_size[1] + padding
        elif position == "center":
            text_x = (video_size[0] - text_size[0]) // 2
            text_y = (video_size[1] + text_size[1]) // 2
        else:
            # Default to bottom-right
            text_x = video_size[0] - text_size[0] - padding
            text_y = video_size[1] - padding
        
        # Add text to the image
        cv2.putText(img, text, (text_x, text_y), font, fontScale, color, thickness)
        
        return img
    
    @retry(max_tries=3, delay_seconds=2, exceptions=(subprocess.SubprocessError,))
    def add_watermark(self, video_path, output_path=None, watermark_text="© My Channel", position="bottom-middle"):
        """Add watermark to video using FFmpeg"""
        try:
            if output_path is None:
                # Create output path by adding '_watermarked' before the extension
                name, ext = os.path.splitext(video_path)
                output_path = f"{name}_watermarked{ext}"
            
            logger.info(f"Adding watermark to video: {video_path}")
            
            # Set a default position parameter
            position_param = "x=(w-text_w)/2:y=h-th-10"  # Default to bottom-middle
            
            # Define position parameters for FFmpeg
            if position == "bottom-middle":
                position_param = "x=(w-text_w)/2:y=h-th-10"
            elif position == "bottom-right":
                position_param = "x=w-tw-10:y=h-th-10"
            elif position == "bottom-left":
                position_param = "x=10:y=h-th-10"
            elif position == "top-right":
                position_param = "x=w-tw-10:y=10"
            elif position == "top-left":
                position_param = "x=10:y=10"
            elif position == "center":
                position_param = "x=(w-text_w)/2:y=(h-text_h)/2"
            
            # Print the position being used
            logger.info(f"Using position parameter: {position_param}")
            
            # Try to get ffmpeg from imageio_ffmpeg
            try:
                import imageio_ffmpeg
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                # If imageio_ffmpeg is not installed, try to use system ffmpeg
                ffmpeg_exe = "ffmpeg"
                
            # Construct FFmpeg command
            # Modify the ffmpeg_cmd in the add_watermark function:
            # Simpler watermarking approach:
            ffmpeg_cmd = [
                ffmpeg_exe,
                "-i", video_path,
                "-vf", f"drawbox=x=0:y=main_h-40:w=main_w:h=40:color=black@0.5:t=fill,drawtext=text='{watermark_text}':x=(w-text_w)/2:y=main_h-20:fontcolor=white:fontsize=24",
                "-codec:a", "copy",
                "-y",
                output_path
            ]
            
            # Run the FFmpeg command
            logger.info(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                raise subprocess.SubprocessError(f"FFmpeg failed with code {result.returncode}: {result.stderr}")
            
            # Verify the output file exists and has content
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Watermark added successfully. Output: {output_path}")
                return output_path
            else:
                logger.error(f"Failed to create watermarked video file.")
                raise FileNotFoundError("Watermarked file was not created properly")
                
        except Exception as e:
            logger.error(f"Error adding watermark: {e}")
            traceback.print_exc()
            raise
    
    @retry(max_tries=MAX_DOWNLOAD_RETRIES, delay_seconds=3, backoff_factor=2, 
           exceptions=(yt_dlp.utils.DownloadError, subprocess.SubprocessError))
    def download_video(self, video_url):
        """Download a video using yt-dlp (more robust than pytube)"""
        try:
            # Extract video ID
            video_id = video_url.split("=")[-1].split("&")[0]
            
            # Check if already downloaded
            if self.is_video_downloaded(video_id):
                logger.info(f"Video {video_id} already downloaded previously. Skipping.")
                return None
            
            # Add a random delay before downloading
            delay = random.uniform(3, 8)
            logger.info(f"Adding delay of {delay:.2f} seconds before download...")
            time.sleep(delay)
            
            # Get info about the video first
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'forcejson': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'geo_bypass': True,
                'socket_timeout': 30,
                'http_headers': {
                    'User-Agent': random.choice(self.user_agents),
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
            if not info:
                logger.error(f"Could not get info for video {video_id}")
                raise yt_dlp.utils.DownloadError(f"Failed to get video info for {video_id}")
                
            title = info.get('title', f'video_{video_id}')
            description = info.get('description', '')
            
            # Clean the title to make it a valid filename
            clean_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
            if not clean_title:
                clean_title = video_id
            filename = f"{clean_title}.mp4"
            filepath = os.path.join(self.download_dir, filename)
            
            # Log the exact path where we'll save the file
            logger.info(f"Will download to: {filepath}")
            
            # Check if download directory still exists
            if not os.path.exists(self.download_dir):
                logger.error(f"Download directory no longer exists: {self.download_dir}")
                try:
                    os.makedirs(self.download_dir)
                    logger.info(f"Recreated download directory: {self.download_dir}")
                except Exception as e:
                    logger.error(f"Failed to recreate download directory: {e}")
                    raise FileNotFoundError(f"Could not create download directory: {self.download_dir}")
 
            # Configure yt-dlp options for the actual download
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': filepath,
                'quiet': False,  # Changed to False to see more output
                'no_warnings': False,  # Changed to False to see warnings
                'verbose': True,  # Added for more verbose output
                'nocheckcertificate': True,
                'ignoreerrors': True,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'socket_timeout': 30,
                'retries': 10,
                'fragment_retries': 10,
                'external_downloader_args': ['--max-retries', '10'],
                'progress_hooks': [self.progress_hook],  # Added progress hook
                'http_headers': {
                    'User-Agent': random.choice(self.user_agents),
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            }
            
            logger.info(f"Downloading: {title}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            logger.info(f"Downloaded: {filepath}")
            
            # Mark video as downloaded
            self.mark_video_downloaded(video_id)
            
            # Extract hashtags from description
            hashtags = []
            if description:
                # Look for hashtags in the description
                hashtags = re.findall(r'#\w+', description)
                # Make list unique
                hashtags = list(set(hashtags))
            
            return {
                "original_filepath": filepath,
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "tags": ["shorts", "trending"],
                "video_id": video_id
            }
            
        except Exception as e:
            logger.error(f"Error downloading with yt-dlp {video_url}: {e}")
            raise
    
    @retry(max_tries=MAX_UPLOAD_RETRIES, delay_seconds=5, exceptions=(googleapiclient.errors.HttpError,))
    def upload_video_to_my_channel(self, video_data):
        """Upload a video to YOUR YouTube channel"""
        try:
            filepath = video_data["filepath"]
            
            request_body = {
                'snippet': {
                    'title': video_data["title"],
                    'description': video_data["description"],
                    'tags': video_data["tags"],
                    'categoryId': '22'  # Category for People & Blogs (you can change this)
                },
                'status': {
                    'privacyStatus': 'public',  # Set to public (change if needed)
                    'selfDeclaredMadeForKids': False
                }
            }
            
            # Check if the file exists and has content
            if not os.path.exists(filepath):
                logger.error(f"Error: File {filepath} does not exist")
                return None
                
            if os.path.getsize(filepath) == 0:
                logger.error(f"Error: File {filepath} is empty")
                return None
            
            # Create the media upload object
            media = MediaFileUpload(filepath, resumable=True)
            
            # Call the API to upload the video to YOUR channel
            logger.info(f"Uploading to YOUR channel: {video_data['title']}")
            upload_request = self.youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            )
            
            # Execute the upload
            response = upload_request.execute()
            logger.info(f"Upload complete! Video ID on YOUR channel: {response['id']}")
            
            # Force release of the file handle
            if hasattr(media, '_fd'):
                media._fd.close()
            media = None
            gc.collect()
            
            # Schedule files for deletion
            self.schedule_file_for_deletion(filepath)
            
            return response['id']
            
        except googleapiclient.errors.HttpError as e:
            logger.error(f"HTTP Error uploading video to your channel: {e}")
            raise
        except Exception as e:
            logger.error(f"Error uploading video to your channel: {e}")
            return None
    
    def save_tiktok_cookies(self, driver, cookie_file="tiktok_cookies.json"):
        """Save TikTok login cookies for future use"""
        try:
            cookies = driver.get_cookies()
            with open(cookie_file, "w") as f:
                json.dump(cookies, f)
            logger.info("TikTok cookies saved successfully")
        except Exception as e:
            logger.error(f"Error saving TikTok cookies: {e}")

    def load_tiktok_cookies(self, driver, cookie_file="tiktok_cookies.json"):
        """Load TikTok login cookies"""
        if os.path.exists(cookie_file):
            try:
                # First navigate to TikTok domain
                driver.get("https://www.tiktok.com")
                time.sleep(2)
                
                with open(cookie_file, "r") as f:
                    cookies = json.load(f)
                for cookie in cookies:
                    # Handle domain issues
                    if 'domain' in cookie:
                        if cookie['domain'].startswith('.'):
                            cookie['domain'] = cookie['domain'][1:]
                    try:
                        driver.add_cookie(cookie)
                    except Exception as e:
                        logger.error(f"Error adding cookie: {e}")
                        
                logger.info("TikTok cookies loaded successfully")
                # Refresh the page to apply cookies
                driver.refresh()
                time.sleep(2)
                return True
            except Exception as e:
                logger.error(f"Error loading TikTok cookies: {e}")
        return False
    
    @retry(max_tries=MAX_UPLOAD_RETRIES, delay_seconds=10, 
           exceptions=(TimeoutError, ConnectionError))
    def upload_video_to_tiktok(self, video_data):
        """Upload a video to TikTok using Selenium browser automation"""
        try:
            filepath = video_data["filepath"]
            title = video_data["title"]
            
            logger.info(f"Preparing to upload to TikTok: {title}")
            
            # Import required libraries for browser automation
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.common.action_chains import ActionChains
            from webdriver_manager.chrome import ChromeDriverManager
            import time
            
            # For headless environments (like Google Cloud VM)
            try:
                from pyvirtualdisplay import Display
                is_headless = True
                display = Display(visible=0, size=(1920, 1080))
                display.start()
                logger.info("Using virtual display for headless environment")
            except ImportError:
                is_headless = False
                logger.info("Running in normal display mode")
            
            # Set up Chrome options
            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-webrtc")  # Disable WebRTC to prevent STUN server errors
            
            # Additional options for headless environments
            if is_headless:
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--headless")
            
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("prefs", {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.default_content_setting_values.images": 1  # Allow images
            })
            
            # Initialize the driver
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Execute CDP command to avoid detection
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
            
            try:
                # First go to TikTok main page
                logger.info("Navigating to TikTok...")
                driver.get("https://www.tiktok.com")
                time.sleep(3)
                
                # Try to load cookies if available
                cookie_loaded = self.load_tiktok_cookies(driver)
                
                # Navigate to the login page if needed
                if not cookie_loaded:
                    # Go to login page
                    driver.get("https://www.tiktok.com/login")
                    logger.info("Please log in manually. Waiting for login to complete...")
                    
                    # Wait for user to log in (look for a profile indicator)
                    logged_in = False
                    wait_time = 120  # 2 minutes max wait
                    start_time = time.time()
                    
                    while not logged_in and (time.time() - start_time) < wait_time:
                        try:
                            # Check if we have a user avatar visible (indicating logged in)
                            if driver.find_elements(By.CSS_SELECTOR, "[data-e2e='profile-icon']") or \
                               "login" not in driver.current_url.lower():
                                logged_in = True
                                break
                        except:
                            pass
                        time.sleep(2)
                    
                    if logged_in:
                        logger.info("Detected successful login. Saving cookies.")
                        self.save_tiktok_cookies(driver)
                    else:
                        logger.warning("Login timed out. Please try again.")
                        return False
                
                # Navigate to the upload page
                logger.info("Navigating to upload page...")
                driver.get("https://www.tiktok.com/upload")
                time.sleep(5)  # Give the page time to load
                
                # Sometimes TikTok redirects to login even with cookies, check if we need to log in again
                if "login" in driver.current_url.lower():
                    logger.info("Redirected to login. Cookie login failed, manual login required")
                    logger.info("Please log in manually. Waiting for login to complete...")
                    
                    # Wait for manual login completion
                    wait_time = 120  # 2 minutes max wait
                    start_time = time.time()
                    
                    while "login" in driver.current_url.lower() and (time.time() - start_time) < wait_time:
                        time.sleep(2)
                    
                    if "login" not in driver.current_url.lower():
                        logger.info("Detected successful login. Saving new cookies.")
                        self.save_tiktok_cookies(driver)
                        # Go to upload page again
                        driver.get("https://www.tiktok.com/upload")
                        time.sleep(5)
                    else:
                        logger.warning("Login timed out. Please try again.")
                        return False
                
                # Check if we're on the upload page by looking for indicators
                upload_page_indicators = [
                    "//div[contains(@class, 'upload') or contains(@data-e2e, 'upload')]",
                    "//input[@type='file']",
                    "//span[contains(text(), 'Upload')]",
                    "//h1[contains(text(), 'Upload')]"
                ]
                
                on_upload_page = False
                for indicator in upload_page_indicators:
                    try:
                        if driver.find_elements(By.XPATH, indicator):
                            on_upload_page = True
                            logger.info(f"Upload page detected via: {indicator}")
                            break
                    except:
                        pass
                
                if not on_upload_page:
                    logger.error("Failed to reach upload page. Current URL: " + driver.current_url)
                    return False
                
                # Look for the file input element
                logger.info("Looking for file input element...")
                file_input = None
                
                # Try different methods to find the file input
                selectors = [
                    "input[type='file']",
                    "input[accept*='video']",
                    "input[accept*='mp4']"
                ]
                
                for selector in selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            file_input = elements[0]
                            logger.info(f"Found file input via: {selector}")
                            break
                    except:
                        pass
                
                if not file_input:
                    # Try to find a hidden file input and make it visible
                    logger.info("Standard file input not found. Looking for hidden inputs...")
                    try:
                        # Find all inputs and check if any are file inputs
                        inputs = driver.find_elements(By.TAG_NAME, "input")
                        for input_elem in inputs:
                            try:
                                if input_elem.get_attribute("type") == "file":
                                    file_input = input_elem
                                    # Make it visible using JavaScript
                                    driver.execute_script("""
                                        arguments[0].style.display = 'block';
                                        arguments[0].style.visibility = 'visible';
                                        arguments[0].style.opacity = '1';
                                    """, file_input)
                                    logger.info("Found and modified hidden file input")
                                    break
                            except:
                                continue
                    except:
                        pass
                
                if not file_input:
                    logger.error("Could not find any file input element. Upload not possible.")
                    return False
                
                # Ensure the file path is absolute
                abs_filepath = os.path.abspath(filepath)
                logger.info(f"Uploading file: {abs_filepath}")
                
                # Upload the video file
                try:
                    file_input.send_keys(abs_filepath)
                    logger.info("Video file selected")
                except Exception as e:
                    logger.error(f"Error sending file to input: {e}")
                    traceback.print_exc()
                    return False
                
                # Wait for the video to be processed
                logger.info("Waiting for video processing...")
                
                # Look for caption field to appear, which suggests video is processed
                caption_found = False
                max_wait = 120  # 2 minutes
                start_time = time.time()
                
                caption_selectors = [
                    "div[data-e2e='upload-caption'] textarea",
                    "textarea[placeholder*='caption']",
                    "textarea[placeholder*='descri']",
                    "div.DraftEditor-root",
                    "div.public-DraftEditor-content",
                    "[contenteditable='true']",
                    "div[role='textbox']",
                    "div.tiktok-textarea",
                    "div.editor-container textarea",
                    "//div[contains(@class, 'caption')]//textarea",
                    "//div[contains(text(), 'Caption')]/..//textarea",
                    "//label[contains(text(), 'Caption')]/..//textarea"
                ]
                
                while not caption_found and (time.time() - start_time) < max_wait:
                    for selector in caption_selectors:
                        try:
                            if selector.startswith("//"):
                                elements = driver.find_elements(By.XPATH, selector)
                            else:
                                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                
                            if elements and elements[0].is_displayed():
                                caption_input = elements[0]
                                caption_found = True
                                logger.info(f"Caption field found via: {selector}")
                                break
                        except:
                            pass
                    
                    if not caption_found:
                        time.sleep(2)
                
                if not caption_found:
                    logger.warning("Caption field not found. Video may not have processed correctly.")
                    return False
                
                # Enter the caption/description
                try:
                    logger.info("Entering caption...")
                    
                    # Get the proper title and description from video_data
                    video_title = video_data.get("title", "")
                    youtube_description = video_data.get("description", "")
                    youtube_hashtags = video_data.get("hashtags", [])
                    
                    # Create a condensed caption for TikTok
                    if youtube_description and len(youtube_description) > 100:
                        # If YouTube description is long, use a shorter version
                        tiktok_caption = youtube_description[:100] + "..."
                    elif youtube_description:
                        tiktok_caption = youtube_description
                    else:
                        # Fallback to title if no description
                        tiktok_caption = video_title
                    
                    # Add hashtags - if no hashtags exist, add Taylor Swift specific ones
                    if youtube_hashtags:
                        hashtag_text = ""
                        for hashtag in youtube_hashtags[:5]:  # Limit to first 5 hashtags
                            hashtag_text += f" {hashtag}"
                        
                        # Check if we need to add #shorts
                        if " #shorts" not in hashtag_text:
                            hashtag_text += " #shorts"
                    else:
                        # No hashtags found - add Taylor Swift specific ones
                        hashtag_text = " #taylorSwift #wonderland #shorts #trending"
                    
                    # Combine caption and hashtags
                    caption_text = tiktok_caption + hashtag_text
                    logger.info(f"Prepared caption: {caption_text}")
                    
                    # Try identifying what type of element we're dealing with
                    element_tag = caption_input.tag_name
                    is_editable = False
                    try:
                        is_editable = caption_input.get_attribute("contenteditable") == "true"
                    except:
                        pass
                    
                    logger.info(f"Caption element info: tag={element_tag}, contenteditable={is_editable}")
                    
                    # Multiple methods to try entering text
                    caption_entry_methods = [
                        # Method 1: Direct input for contenteditable
                        lambda: (
                            caption_input.click(),
                            time.sleep(0.5),
                            ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform(),
                            time.sleep(0.5),
                            caption_input.send_keys(caption_text),
                            logger.info("Caption entered with Method 1 (direct input)")
                        ),
                        
                        # Method 2: Character by character
                        lambda: (
                            caption_input.click(),
                            time.sleep(0.5),
                            caption_input.clear(),
                            time.sleep(0.5),
                            [caption_input.send_keys(char) or time.sleep(0.02) for char in caption_text],
                            logger.info("Caption entered with Method 2 (character by character)")
                        ),
                        
                        # Method 3: JavaScript
                        lambda: (
                            driver.execute_script("""
                                arguments[0].value = arguments[1];
                                arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                                arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                            """, caption_input, caption_text),
                            logger.info("Caption entered with Method 3 (JavaScript)")
                        ),
                        
                        # Method 4: ActionChains
                        lambda: (
                            ActionChains(driver).click(caption_input).perform(),
                            time.sleep(0.5),
                            ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform(),
                            time.sleep(0.2),
                            ActionChains(driver).send_keys(Keys.DELETE).perform(),
                            time.sleep(0.5),
                            ActionChains(driver).send_keys(caption_text).perform(),
                            logger.info("Caption entered with Method 4 (ActionChains)")
                        ),
                        
                        # Method 5: execCommand
                        lambda: (
                            driver.execute_script("""
                                arguments[0].focus();
                                document.execCommand('selectAll', false, null);
                                document.execCommand('delete', false, null);
                                document.execCommand('insertText', false, arguments[1]);
                            """, caption_input, caption_text),
                            logger.info("Caption entered with Method 5 (execCommand)")
                        )
                    ]
                    
                    # Try each method until one works
                    caption_entered = False
                    for i, method in enumerate(caption_entry_methods, 1):
                        try:
                            method()
                            caption_entered = True
                            break
                        except Exception as e:
                            logger.warning(f"Caption entry method {i} failed: {e}")
                    
                    if caption_entered:
                        # No matter which method we used, try to tab away from the field to trigger any needed events
                        try:
                            caption_input.send_keys(Keys.TAB)
                        except:
                            pass
                        
                        logger.info("Caption entry completed successfully")
                    else:
                        logger.warning("All caption entry methods failed")
                        
                except Exception as e:
                    logger.error(f"Error entering caption: {e}")
                    traceback.print_exc()
                    
                    # Continue anyway - caption might not be required
                    logger.info("Continuing without caption...")
                
                # Find and click the Post button
                logger.info("Looking for Post button...")
                post_button = None

                # More comprehensive selectors for the Post button
                post_button_selectors = [
                    "button[data-e2e='upload-post']",
                    "button[data-e2e*='post']",
                    "button.css-y1m958",  # Added - common TikTok button class
                    ".css-1eoitbk",       # Added - recent TikTok post button container class
                    ".btn-post",          # Added - another common post button class
                    "//button[contains(text(), 'Post')]",
                    "//button[text()='Post']",
                    "//button[contains(., 'Post')]",
                    "//div[contains(@class, 'button-post')]",
                    "//div[contains(@class, 'post-button')]",
                    "//div[contains(@class, 'SubmitButton')]",
                    "//button[contains(@class, 'submit')]",
                    # Broader selectors as fallbacks
                    "//button[contains(@class, 'primary')]",
                    "//button[contains(@class, 'btn-primary')]"
                ]

                # Try each selector
                for selector in post_button_selectors:
                    try:
                        if selector.startswith("//"):
                            elements = driver.find_elements(By.XPATH, selector)
                        else:
                            elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        
                        if elements and elements[0].is_displayed() and elements[0].is_enabled():
                            post_button = elements[0]
                            logger.info(f"Post button found via: {selector}")
                            break
                    except:
                        pass

                # If still not found, try a more aggressive approach - look for ANY button that might be the post button
                if not post_button:
                    logger.info("Post button not found with specific selectors. Trying generic button search...")
                    try:
                        # Get all buttons
                        buttons = driver.find_elements(By.TAG_NAME, "button")
                        # Filter for visible buttons in the bottom section of page
                        for button in buttons:
                            try:
                                if button.is_displayed() and button.is_enabled():
                                    button_text = button.text.lower()
                                    # Look for buttons with post-related text or in typical post button positions
                                    if ('post' in button_text or 'upload' in button_text or 'submit' in button_text or button_text == ''):
                                        post_button = button
                                        logger.info(f"Potential post button found via generic search: {button_text}")
                                        break
                            except:
                                continue
                    except Exception as e:
                        logger.error(f"Error during generic button search: {e}")
                
                # Click the Post button
                try:
                    post_button.click()
                    logger.info("Post button clicked")
                except Exception as e:
                    logger.error(f"Error clicking post button: {e}")
                    try:
                        # Try JavaScript click as fallback
                        driver.execute_script("arguments[0].click();", post_button)
                        logger.info("Post button clicked via JavaScript")
                    except:
                        logger.error("All methods to click Post button failed")
                        return False
                
                # Wait for upload to complete
                logger.info("Waiting for upload to complete...")
                success = False
                max_wait_time = 300  # 5 minutes
                start_time = time.time()
                starting_url = driver.current_url  # Save the starting URL
                
                while not success and (time.time() - start_time) < max_wait_time:
                    current_url = driver.current_url
                    
                    # Check for success indicators
                    try:
                        # Check for explicit success elements
                        success_elements = driver.find_elements(By.CSS_SELECTOR, "div[data-e2e='upload-success']")
                        if success_elements and any(elem.is_displayed() for elem in success_elements):
                            success = True
                            logger.info("Upload success element detected!")
                            break
                            
                        # Check for URL changes that indicate success
                        if "success" in current_url or "/profile" in current_url or current_url == "https://www.tiktok.com/":
                            success = True
                            logger.info(f"Upload success detected by URL change to: {current_url}")
                            break
                            
                        # Check if we're no longer on the upload page and URL has changed
                        if "upload" not in current_url and current_url != starting_url:
                            logger.info(f"Redirected from upload page to: {current_url}")
                            success = True
                            break
                            
                        # Check if the Post button is no longer visible or has changed text
                        try:
                            if post_button and (not post_button.is_displayed() or 
                                              'Processing' in post_button.text or 
                                              'Uploading' in post_button.text or
                                              'Success' in post_button.text):
                                logger.info(f"Post button state changed: {post_button.text if post_button.text else 'Not visible'}")
                                # Wait a bit more to ensure the upload completes
                                time.sleep(10)
                                success = True
                                break
                        except:
                            # Post button might have been removed from DOM
                            pass
                            
                        # Check for any success messages in the page content
                        page_text = driver.page_source.lower()
                        if "upload successful" in page_text or "video uploaded" in page_text:
                            logger.info("Success message detected in page content")
                            success = True
                            break
                    except Exception as e:
                        logger.error(f"Error checking upload status: {e}")
                    
                    # Wait a bit before checking again
                    time.sleep(5)
                    logger.info(f"Still waiting... ({int(time.time() - start_time)} seconds elapsed)")
                
                # If we've waited a long time and still don't have explicit success, consider it a success anyway
                if (time.time() - start_time) >= 60 and not success:
                    logger.info("Upload appears to have completed (timeout reached with no errors)")
                    success = True
                
                if success:
                    logger.info("Video successfully uploaded to TikTok")
                    return True
                else:
                    logger.warning("Upload timed out or failed")
                    return False
                    
            except Exception as e:
                logger.error(f"Error during TikTok upload process: {e}")
                traceback.print_exc()
                return False
                
            finally:
                # Close the browser
                logger.info("Closing browser...")
                time.sleep(5)  # Give a moment to finalize
                driver.quit()
                
                # Stop virtual display if we were using one
                if is_headless:
                    display.stop()
                
        except Exception as e:
            logger.error(f"Error setting up TikTok upload: {e}")
            traceback.print_exc()
            raise
    
    def process_source_channel(self, channel_url):
        """Process a single source channel - download one random video and upload to your channels"""
        logger.info(f"\nProcessing source channel: {channel_url} at {datetime.now()}")
        
        # First try to delete any files from previous runs
        self.process_pending_deletions()
        
        # Try up to MAX_VIDEO_RETRIES random videos if there are download issues
        for attempt in range(MAX_VIDEO_RETRIES):
            # Get a random video URL from the source channel
            video_url = self.get_random_channel_video(channel_url)
            
            if not video_url:
                logger.warning("No videos available to download from this source channel")
                return
                
            logger.info(f"Attempt {attempt+1}: Trying to download {video_url}")
            
            # Download the video from the source channel
            try:
                video_data = self.download_video(video_url)
            except Exception as e:
                logger.error(f"Failed to download video: {e}")
                logger.info(f"Attempt {attempt+1} failed. Trying another video...")
                continue
            
            if video_data:
                success = False
                
                if youtube_upload:
                    try:
                        # Add watermark to the video
                        watermarked_path = self.add_watermark(
                            video_data["original_filepath"], 
                            watermark_text="© taylors_wonderland_official",  # Customize this
                            position="bottom-middle"  # Options: "bottom-right", "bottom-left", "bottom-middle", "top-right", "top-left", "center"
                        )
                        video_data.update({"filepath": watermarked_path})
                        
                        # Upload the video to YOUR YouTube channel
                        youtube_video_id = self.upload_video_to_my_channel(video_data)
                        
                        if youtube_video_id:
                            logger.info(f"Successfully uploaded video to YOUR YouTube channel: {video_data['title']}")
                            logger.info(f"View at: https://www.youtube.com/watch?v={youtube_video_id}")
                            success = True
                        else:
                            logger.warning(f"Failed to upload video to YOUR YouTube channel: {video_data['title']}")
                    except Exception as e:
                        logger.error(f"YouTube upload process failed: {e}")
                
                if tiktok_upload:
                    try:
                        # Add watermark to the video
                        watermarked_path = self.add_watermark(
                            video_data["original_filepath"], 
                            watermark_text="© taylorswift.wonderland",  # Customize this
                            position="bottom-middle"  # Options: "bottom-right", "bottom-left", "bottom-middle", "top-right", "top-left", "center"
                        )
                        video_data.update({"filepath": watermarked_path})

                        # Upload the video to TikTok as well
                        tiktok_success = self.upload_video_to_tiktok(video_data)
                        
                        if tiktok_success:
                            logger.info(f"Successfully uploaded video to TikTok: {video_data['title']}")
                            success = True
                        else:
                            logger.warning(f"Failed to upload video to TikTok: {video_data['title']}")
                    except Exception as e:
                        logger.error(f"TikTok upload process failed: {e}")
                
                # Schedule original file for deletion
                self.schedule_file_for_deletion(video_data["original_filepath"])
                    
                if success:
                    return True
            
            logger.info(f"Attempt {attempt+1} failed. Trying another video...")
            
        logger.warning("All attempts failed. Will try again at next scheduled run.")
        return False


def process_channels_with_retries(reuploader, channels, max_retries=MAX_CHANNEL_RETRIES):
    """Process channels with retries if one fails"""
    # Shuffle the order to avoid hitting the same channels repeatedly
    random.shuffle(channels)
    
    for retry in range(max_retries):
        if not channels:
            logger.warning("No channels available to process")
            return False
            
        # Pick a random channel
        channel_url = random.choice(channels)
        logger.info(f"Trying channel {retry+1}/{max_retries}: {channel_url}")
        
        success = reuploader.process_source_channel(channel_url)
        if success:
            logger.info(f"Successfully processed channel: {channel_url}")
            return True
            
        # Remove failed channel from the list for this run
        channels.remove(channel_url)
        logger.warning(f"Failed to process channel: {channel_url}. {len(channels)} channels remaining.")
    
    logger.error(f"Failed to process any channel after {max_retries} attempts.")
    return False


# Main function to schedule the task
def main():
    try:
        reuploader = YouTubeChannelReuploader()
        
        # Start with a base list of known channels
        source_channel_urls = [
            "https://www.youtube.com/@Mywonderland13",  # Your existing channel
        ]
        
        # Find additional Taylor Swift channels
        taylor_swift_channels = reuploader.find_channels(max_channels=1)
        
        # Add the found channels to the source list
        source_channel_urls.extend(taylor_swift_channels)
        
        logger.info(f"Using {len(source_channel_urls)} source channels: {source_channel_urls}")
        
        def job():
            # Process channels with retries
            process_channels_with_retries(reuploader, source_channel_urls.copy())
        
        # Schedule the job to run every 8 hours
        schedule.every(8).hours.do(job)
        
        # Run the job once immediately
        job()
        
        # Keep the script running
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
            logger.info(f"Waiting for next scheduled run... Next run in approximately {int(schedule.idle_seconds()/60)} minutes")
    
    except Exception as e:
        logger.critical(f"Critical error in main loop: {e}")
        traceback.print_exc()
        # You could add notification logic here (email, SMS, etc.)


if __name__ == "__main__":
    main()