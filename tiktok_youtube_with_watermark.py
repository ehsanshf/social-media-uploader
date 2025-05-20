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
from googleapiclient.http import MediaFileUpload
import yt_dlp
from datetime import datetime
import cv2
import numpy as np
import traceback


scheduler = False
youtube_upload = True
tiktok_upload = True


class YouTubeChannelReuploader:
    def __init__(self):
        self.download_dir = r"C:\Users\ehsan\Videos\Youtube"
        self.client_secret_file = r"C:\Users\ehsan\CursorProjects\Social Media Upload automation\client_secrets.json"
        self.token_file = "youtube_token.json"
        self.api_service_name = "youtube"
        self.api_version = "v3"
        self.scopes = ["https://www.googleapis.com/auth/youtube.upload",
                      "https://www.googleapis.com/auth/youtube"]
        self.history_file = "download_history.json"
        
        # Create download directory if it doesn't exist
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
            
        # Load download history
        self.download_history = self.load_download_history()
        
        # Authenticate with YouTube API (this is for YOUR channel)
        print("Authenticating with YouTube API for your upload channel...")
        self.youtube = self.get_authenticated_service()
    
    def get_authenticated_service(self):
        """Authenticate with the YouTube API with token persistence"""
        # Disable OAuthlib's HTTPS verification when running locally.
        # *DO NOT* leave this option enabled in production.
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        
        # Check if we have saved credentials
        creds = None
        if os.path.exists(self.token_file):
            print("Loading saved YouTube credentials...")
            with open(self.token_file, 'r') as token:
                import google.oauth2.credentials
                creds_data = json.load(token)
                creds = google.oauth2.credentials.Credentials.from_authorized_user_info(creds_data)
        
        # If credentials don't exist or are invalid, run the flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("Refreshing expired YouTube credentials...")
                creds.refresh(google.auth.transport.requests.Request())
            else:
                print("Getting new YouTube credentials...")
                flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                    self.client_secret_file, self.scopes)
                creds = flow.run_local_server(port=8080)
            
            # Save the credentials for next run
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())
        
        return googleapiclient.discovery.build(
            self.api_service_name, self.api_version, credentials=creds)
    
    def find_channels(self, max_channels=2):
        """Find YouTube channels with Taylor Swift concert videos"""
        try:
            print("Searching for YouTube channels with Taylor Swift concert videos...")
            
            # Search terms to try
            search_terms = [
                "Taylor Swift",
                "Taylor Swift performs #shorts",
                "Taylor Swift act performance #shorts",
                "Taylor Swift highlights #shorts"
            ]
            
            found_channels = {}  # Dictionary to store channel_id: channel_url pairs
            
            # For each search term
            for term in search_terms:
                if len(found_channels) >= max_channels:
                    break
                    
                encoded_term = requests.utils.quote(term)
                search_url = f"https://www.youtube.com/results?search_query={encoded_term}"
                
                print(f"Searching: {term}")
                
                # Get the search results page
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
                response = requests.get(search_url, headers=headers)
                
                if response.status_code != 200:
                    print(f"Failed to fetch search results: {response.status_code}")
                    continue
                
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
                for video_url in video_links[:20]:  # Check first 10 videos in search results
                    try:
                        # Use yt-dlp to get video info including channel
                        ydl_opts = {
                            'quiet': True,
                            'no_warnings': True,
                            'skip_download': True,
                            'forcejson': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(video_url, download=False)
                        
                        duration = info.get('duration', 0)
                        duration_limit = 120
                        if duration > duration_limit:
                            print(f"Skipping video {video_id} - duration {duration}s is longer than {duration_limit}s (not a short).")
                            return None

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
                                    'eras tour' in title or 'eras tour' in description)
                        
                        if is_relevant and channel_id and channel_url and channel_id not in found_channels:
                            # Use the channel URL in @username format if possible
                            formatted_channel_url = f"https://www.youtube.com/{info.get('uploader_id', channel_id)}"
                            found_channels[channel_id] = formatted_channel_url
                            print(f"Found relevant channel: {channel_name} - {formatted_channel_url}")
                            
                            if len(found_channels) >= max_channels:
                                break
                                
                    except Exception as e:
                        print(f"Error getting channel info for {video_url}: {e}")
                        continue
            
            # Return the list of channel URLs
            return list(found_channels.values())
        
        except Exception as e:
            print(f"Error finding Taylor Swift channels: {e}")
            return []

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
    
    def is_video_downloaded(self, video_id):
        """Check if a video has been downloaded before"""
        return video_id in self.download_history["downloaded_video_ids"]
    
    def mark_video_downloaded(self, video_id):
        """Mark a video as downloaded in the history"""
        if not self.is_video_downloaded(video_id):
            self.download_history["downloaded_video_ids"].append(video_id)
            self.save_download_history()
    
    def get_channel_videos(self, channel_url):
        """Get videos from a channel using web scraping instead of pytube Channel class"""
        try:
            print(f"Fetching videos from source channel: {channel_url}")
            
            # Get the channel page
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(channel_url + "/videos", headers=headers)
            
            if response.status_code != 200:
                print(f"Failed to fetch channel page: {response.status_code}")
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
            
            print(f"Found {len(video_links)} videos on the channel")
            return video_links
            
        except Exception as e:
            print(f"Error fetching channel videos: {e}")
            return []
    
    def get_random_channel_video(self, channel_url, max_videos_to_check=50):
        """Get a random video from a source channel that hasn't been downloaded before and doesn't have copyright notices"""
        try:
            # Get all videos from the channel
            video_links = self.get_channel_videos(channel_url)
            
            if not video_links:
                print("No videos found on this channel")
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
                        ydl_opts = {
                            'quiet': True,
                            'no_warnings': True,
                            'skip_download': True,
                            'forcejson': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(video_url, download=False)
                        
                        # Check for copyright symbols or text in description
                        description = info.get('description', '').lower()
                        copyright_indicators = ['©', 'copyright', 'all rights reserved', 'licensed to', 'provided to youtube']
                        
                        has_copyright_notice = any(indicator in description.lower() for indicator in copyright_indicators)
                        
                        if not has_copyright_notice:
                            available_videos.append(video_url)
                            print(f"Video {video_id} has no copyright notice in description")
                        else:
                            copyright_rejected += 1
                            print(f"Video {video_id} rejected due to copyright notice in description")
                    except Exception as e:
                        print(f"Error checking video {video_id}: {e}")
                        # Skip this video if we can't check it
                        continue
                
                count += 1
            
            if not available_videos:
                print(f"No new videos available to download from this channel (Copyright rejected: {copyright_rejected})")
                return None
            
            # Choose a random video from the filtered list
            random_video = random.choice(available_videos)
            return random_video
            
        except Exception as e:
            print(f"Error getting random channel video: {e}")
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
    
    def add_watermark(self, video_path, output_path=None, watermark_text="© My Channel", position="bottom-middle"):
        """Add watermark to video using FFmpeg"""
        try:
            if output_path is None:
                # Create output path by adding '_watermarked' before the extension
                name, ext = os.path.splitext(video_path)
                output_path = f"{name}_watermarked{ext}"
            
            print(f"Adding watermark to video: {video_path}")
            
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
            print(f"Using position parameter: {position_param}")
            
            # Try to get ffmpeg from imageio_ffmpeg
            try:
                import imageio_ffmpeg
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                # If imageio_ffmpeg is not installed, try to use system ffmpeg
                ffmpeg_exe = "ffmpeg"
                
            # Construct FFmpeg command
            ffmpeg_cmd = [
                ffmpeg_exe,
                "-i", video_path,
                "-vf", f"drawtext=text='{watermark_text}':fontcolor=white:fontsize=24:box=1:boxcolor=black@0.5:boxborderw=5:{position_param}",
                "-codec:a", "copy",
                "-y",  # Overwrite output file if it exists
                output_path
            ]
            
            # Run the FFmpeg command
            print(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
            import subprocess
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                print(f"FFmpeg error: {result.stderr}")
                return video_path
            
            # Verify the output file exists and has content
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"Watermark added successfully. Output: {output_path}")
                return output_path
            else:
                print(f"Failed to create watermarked video file.")
                return video_path
                
        except Exception as e:
            print(f"Error adding watermark: {e}")
            traceback.print_exc()
            return video_path  # Return original path if watermarking fails
    
    def download_video(self, video_url):
        """Download a video using yt-dlp (more robust than pytube)"""
        try:
            # Extract video ID
            video_id = video_url.split("=")[-1].split("&")[0]
            
            # Check if already downloaded
            if self.is_video_downloaded(video_id):
                print(f"Video {video_id} already downloaded previously. Skipping.")
                return None
            
            # Get info about the video first
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'forcejson': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
            title = info.get('title', f'video_{video_id}')
            description = info.get('description', '')
            
            # Clean the title to make it a valid filename
            clean_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
            if not clean_title:
                clean_title = video_id
            filename = f"{clean_title}.mp4"
            filepath = os.path.join(self.download_dir, filename)
            
            # Configure yt-dlp options for the actual download
            ydl_opts = {
                'format': 'best[ext=mp4]',
                'outtmpl': filepath,
                'quiet': False,
                'no_warnings': False,
            }
            
            print(f"Downloading: {title}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            print(f"Downloaded: {filepath}")
            
            # Mark video as downloaded
            self.mark_video_downloaded(video_id)
            
            # Extract hashtags from description
            hashtags = []
            if description:
                # Look for hashtags in the description
                import re
                hashtags = re.findall(r'#\w+', description)
                # Make list unique
                hashtags = list(set(hashtags))
            
            return {
                "original_filepath": filepath,
                "title": title,
                "description": description,  # Store full description without appending
                "hashtags": hashtags,  # Store extracted hashtags
                "tags": ["shorts", "trending"],
                "video_id": video_id
            }
            
        except Exception as e:
            print(f"Error downloading with yt-dlp {video_url}: {e}")
            return None
    
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
                print(f"Error: File {filepath} does not exist")
                return None
                
            if os.path.getsize(filepath) == 0:
                print(f"Error: File {filepath} is empty")
                return None
            
            # Create the media upload object
            media = MediaFileUpload(filepath, resumable=True)
            
            # Call the API to upload the video to YOUR channel
            print(f"Uploading to YOUR channel: {video_data['title']}")
            upload_request = self.youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            )
            
            # Execute the upload
            response = upload_request.execute()
            print(f"Upload complete! Video ID on YOUR channel: {response['id']}")
            return response['id']
            
        except Exception as e:
            print(f"Error uploading video to your channel: {e}")
            return None
    
    def save_tiktok_cookies(self, driver, cookie_file="tiktok_cookies.json"):
        """Save TikTok login cookies for future use"""
        try:
            cookies = driver.get_cookies()
            with open(cookie_file, "w") as f:
                json.dump(cookies, f)
            print("TikTok cookies saved successfully")
        except Exception as e:
            print(f"Error saving TikTok cookies: {e}")

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
                        print(f"Error adding cookie: {e}")
                        
                print("TikTok cookies loaded successfully")
                # Refresh the page to apply cookies
                driver.refresh()
                time.sleep(2)
                return True
            except Exception as e:
                print(f"Error loading TikTok cookies: {e}")
        return False
    
    def upload_video_to_tiktok(self, video_data):
        """Upload a video to TikTok using Selenium browser automation"""
        try:
            filepath = video_data["filepath"]
            title = video_data["title"]
            
            print(f"Preparing to upload to TikTok: {title}")
            
            # Import required libraries for browser automation
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys
            from webdriver_manager.chrome import ChromeDriverManager
            import time
            
            # Set up Chrome options
            chrome_options = Options()
            chrome_options.add_argument("--start-maximized")
            chrome_options.add_argument("--disable-webrtc")  # Disable WebRTC to prevent STUN server errors
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
                print("Navigating to TikTok...")
                driver.get("https://www.tiktok.com")
                time.sleep(3)
                
                # Try to load cookies if available
                cookie_loaded = self.load_tiktok_cookies(driver)
                
                # Navigate to the login page if needed
                if not cookie_loaded:
                    # Go to login page
                    driver.get("https://www.tiktok.com/login")
                    print("Please log in manually. Waiting for login to complete...")
                    
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
                        print("Detected successful login. Saving cookies.")
                        self.save_tiktok_cookies(driver)
                    else:
                        print("Login timed out. Please try again.")
                        return False
                
                # Navigate to the upload page
                print("Navigating to upload page...")
                driver.get("https://www.tiktok.com/upload")
                time.sleep(5)  # Give the page time to load
                
                # Sometimes TikTok redirects to login even with cookies, check if we need to log in again
                if "login" in driver.current_url.lower():
                    print("Redirected to login. Cookie login failed, manual login required")
                    print("Please log in manually. Waiting for login to complete...")
                    
                    # Wait for manual login completion
                    wait_time = 120  # 2 minutes max wait
                    start_time = time.time()
                    
                    while "login" in driver.current_url.lower() and (time.time() - start_time) < wait_time:
                        time.sleep(2)
                    
                    if "login" not in driver.current_url.lower():
                        print("Detected successful login. Saving new cookies.")
                        self.save_tiktok_cookies(driver)
                        # Go to upload page again
                        driver.get("https://www.tiktok.com/upload")
                        time.sleep(5)
                    else:
                        print("Login timed out. Please try again.")
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
                            print(f"Upload page detected via: {indicator}")
                            break
                    except:
                        pass
                
                if not on_upload_page:
                    print("Failed to reach upload page. Current URL:", driver.current_url)
                    return False
                
                # Look for the file input element
                print("Looking for file input element...")
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
                            print(f"Found file input via: {selector}")
                            break
                    except:
                        pass
                
                if not file_input:
                    # Try to find a hidden file input and make it visible
                    print("Standard file input not found. Looking for hidden inputs...")
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
                                    print("Found and modified hidden file input")
                                    break
                            except:
                                continue
                    except:
                        pass
                
                if not file_input:
                    print("Could not find any file input element. Upload not possible.")
                    return False
                
                # Ensure the file path is absolute
                abs_filepath = os.path.abspath(filepath)
                print(f"Uploading file: {abs_filepath}")
                
                # Upload the video file
                try:
                    file_input.send_keys(abs_filepath)
                    print("Video file selected")
                except Exception as e:
                    print(f"Error sending file to input: {e}")
                    traceback.print_exc()
                    return False
                
                # Wait for the video to be processed
                print("Waiting for video processing...")
                
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
                                print(f"Caption field found via: {selector}")
                                break
                        except:
                            pass
                    
                    if not caption_found:
                        time.sleep(2)
                
                if not caption_found:
                    print("Caption field not found. Video may not have processed correctly.")
                    return False
                
                # Enter the caption/description
                # Enter the caption/description
                try:
                    print("Entering caption...")
                    
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
                    print(f"Prepared caption: {caption_text}")
                    
                    # Wait a moment for any animations to complete
                    time.sleep(2)
                    
                    # Try identifying what type of element we're dealing with
                    element_tag = caption_input.tag_name
                    is_editable = False
                    try:
                        is_editable = caption_input.get_attribute("contenteditable") == "true"
                    except:
                        pass
                    
                    print(f"Caption element info: tag={element_tag}, contenteditable={is_editable}")
                    
                    # Method specific to editable divs (contenteditable elements)
                    if is_editable:
                        try:
                            caption_input.click()
                            time.sleep(0.5)
                            # Clear existing content
                            caption_input.clear()
                            # If clear doesn't work, try to select all and delete
                            action = webdriver.ActionChains(driver)
                            action.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()
                            time.sleep(0.5)
                            # Send text
                            caption_input.send_keys(caption_text)
                            print("Caption entered for contenteditable element")
                        except Exception as e:
                            print(f"Contenteditable method failed: {e}")
                    
                    # Method for textareas and input elements
                    elif element_tag in ["textarea", "input"]:
                        try:
                            # Try to interact directly with the element
                            caption_input.click()
                            time.sleep(0.5)
                            caption_input.clear()
                            time.sleep(0.5)
                            
                            # Try character by character input
                            for char in caption_text:
                                caption_input.send_keys(char)
                                time.sleep(0.02)
                            print("Caption entered character by character")
                        except Exception as e:
                            print(f"Character by character method failed: {e}")
                            
                            # Try JavaScript as a fallback
                            try:
                                driver.execute_script("""
                                    arguments[0].value = arguments[1];
                                    arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                                    arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                                """, caption_input, caption_text)
                                print("Caption entered with JavaScript")
                            except Exception as e2:
                                print(f"JavaScript method failed: {e2}")
                    
                    # If we can't identify the element type, try all approaches
                    else:
                        # Try using ActionChains instead of direct send_keys
                        try:
                            action = webdriver.ActionChains(driver)
                            action.click(caption_input).perform()
                            time.sleep(0.5)
                            
                            # Try to clear existing text
                            action = webdriver.ActionChains(driver)
                            action.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
                            time.sleep(0.2)
                            action = webdriver.ActionChains(driver)
                            action.send_keys(Keys.DELETE).perform()
                            time.sleep(0.5)
                            
                            # Input the text
                            action = webdriver.ActionChains(driver)
                            action.send_keys(caption_text).perform()
                            print("Caption entered using ActionChains")
                        except Exception as e:
                            print(f"ActionChains method failed: {e}")
                            
                            # Last resort - try JavaScript for TikTok specific elements
                            try:
                                # Use a TikTok-specific approach using document.execCommand
                                driver.execute_script("""
                                    arguments[0].focus();
                                    document.execCommand('selectAll', false, null);
                                    document.execCommand('delete', false, null);
                                    document.execCommand('insertText', false, arguments[1]);
                                """, caption_input, caption_text)
                                print("Caption entered with execCommand")
                            except Exception as e2:
                                print(f"All caption entry methods failed: {e2}")
                    
                    # No matter which method we used, try to tab away from the field to trigger any needed events
                    try:
                        caption_input.send_keys(Keys.TAB)
                    except:
                        pass
                    
                    print("Caption entry attempts completed")
                except Exception as e:
                    print(f"Error entering caption: {e}")
                    traceback.print_exc()                
                
                # Find and click the Post button
                print("Looking for Post button...")
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
                            print(f"Post button found via: {selector}")
                            break
                    except:
                        pass

                # If still not found, try a more aggressive approach - look for ANY button that might be the post button
                if not post_button:
                    print("Post button not found with specific selectors. Trying generic button search...")
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
                                        print(f"Potential post button found via generic search: {button_text}")
                                        break
                            except:
                                continue
                    except Exception as e:
                        logger.error(f"Error during generic button search: {e}")
                
                # Click the Post button
                try:
                    post_button.click()
                    print("Post button clicked")
                except Exception as e:
                    print(f"Error clicking post button: {e}")
                    try:
                        # Try JavaScript click as fallback
                        driver.execute_script("arguments[0].click();", post_button)
                        print("Post button clicked via JavaScript")
                    except:
                        print("All methods to click Post button failed")
                        return False
                
                # Wait for upload to complete
                print("Waiting for upload to complete...")
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
                            print("Upload success element detected!")
                            break
                            
                        # Check for URL changes that indicate success
                        if "success" in current_url or "/profile" in current_url or current_url == "https://www.tiktok.com/":
                            success = True
                            print(f"Upload success detected by URL change to: {current_url}")
                            break
                            
                        # Check if we're no longer on the upload page and URL has changed
                        if "upload" not in current_url and current_url != starting_url:
                            print(f"Redirected from upload page to: {current_url}")
                            success = True
                            break
                            
                        # Check if the Post button is no longer visible or has changed text
                        try:
                            if post_button and (not post_button.is_displayed() or 
                                            'Processing' in post_button.text or 
                                            'Uploading' in post_button.text or
                                            'Success' in post_button.text):
                                print(f"Post button state changed: {post_button.text if post_button.text else 'Not visible'}")
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
                            print("Success message detected in page content")
                            success = True
                            break
                    except Exception as e:
                        print(f"Error checking upload status: {e}")
                    
                    # Wait a bit before checking again
                    time.sleep(5)
                    print(f"Still waiting... ({int(time.time() - start_time)} seconds elapsed)")

                # If we've waited a long time and still don't have explicit success, consider it a success anyway
                if (time.time() - start_time) >= 60 and not success:
                    print("Upload appears to have completed (timeout reached with no errors)")
                    success = True

                if success:
                    print("Video successfully uploaded to TikTok")
                    return True
                else:
                    print("Upload timed out or failed")
                    return False
                    
            except Exception as e:
                print(f"Error during TikTok upload process: {e}")
                traceback.print_exc()
                return False
                
            finally:
                # Close the browser
                print("Closing browser...")
                time.sleep(5)  # Give a moment to finalize
                driver.quit()
                
        except Exception as e:
            print(f"Error setting up TikTok upload: {e}")
            traceback.print_exc()
            return False
    
    def process_source_channel(self, channel_url):
        """Process a single source channel - download one random video and upload to your channels"""
        print(f"\nProcessing source channel: {channel_url} at {datetime.now()}")
        
        # Try up to 3 random videos if there are download issues
        for attempt in range(3):
            # Get a random video URL from the source channel
            video_url = self.get_random_channel_video(channel_url)
            
            if not video_url:
                print("No videos available to download from this source channel")
                return
                
            print(f"Attempt {attempt+1}: Trying to download {video_url}")
            
            # Download the video from the source channel
            video_data = self.download_video(video_url)
            
            if video_data:
                success = False
                
                if youtube_upload:
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
                        print(f"Successfully uploaded video to YOUR YouTube channel: {video_data['title']}")
                        print(f"View at: https://www.youtube.com/watch?v={youtube_video_id}")
                        success = True
                    else:
                        print(f"Failed to upload video to YOUR YouTube channel: {video_data['title']}")
                
                if tiktok_upload:
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
                        print(f"Successfully uploaded video to TikTok: {video_data['title']}")
                        success = True
                    else:
                        print(f"Failed to upload video to TikTok: {video_data['title']}")
                    
                    if success:
                        return True
            
            print(f"Attempt {attempt+1} failed. Trying another video...")
            
        print("All attempts failed.")
        return False

# Main function to schedule the task
def main():
    reuploader = YouTubeChannelReuploader()
    
    # Start with a base list of known channels
    source_channel_urls = [
        "https://www.youtube.com/@Mywonderland13",  # Your existing channel
    ]
    
    # Find additional Taylor Swift channels
    taylor_swift_channels = reuploader.find_channels(max_channels=5)
    
    # Add the found channels to the source list
    if taylor_swift_channels:
        source_channel_urls.extend(taylor_swift_channels)
    else:
        print("No new channels found to extend source list.")
    
    print(f"Using {len(source_channel_urls)} source channels: {source_channel_urls}")
    
    if scheduler:
        def job():
            # Choose a random source channel
            random_source_channel = random.choice(source_channel_urls)
            reuploader.process_source_channel(random_source_channel)
        
        # Schedule the job to run every 8 hours
        schedule.every(8).hours.do(job)
        
        # Run the job once immediately
        job()
        
        # Keep the script running
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
            print(f"Waiting for next scheduled run... Next run in approximately {int(schedule.idle_seconds()/60)} minutes")
    else:
        random_source_channel = random.choice(source_channel_urls)
        reuploader.process_source_channel(random_source_channel)

if __name__ == "__main__":
    main()