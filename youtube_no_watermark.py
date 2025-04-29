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
from pytube import YouTube
import yt_dlp
from datetime import datetime

class YouTubeChannelReuploader:
    def __init__(self):
        self.download_dir = r"C:\Users\ehsan\Videos\Youtube"
        self.client_secret_file = r"G:\My Drive\Random codes\client_secrets.json"
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
        """Authenticate with the YouTube API"""
        # Disable OAuthlib's HTTPS verification when running locally.
        # *DO NOT* leave this option enabled in production.
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        
        flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
            self.client_secret_file, self.scopes)
        credentials = flow.run_local_server(port=8080)
        
        return googleapiclient.discovery.build(
            self.api_service_name, self.api_version, credentials=credentials)
    
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
        """Get a random video from a source channel that hasn't been downloaded before"""
        try:
            # Get all videos from the channel
            video_links = self.get_channel_videos(channel_url)
            
            if not video_links:
                print("No videos found on this channel")
                return None
            
            # Filter out videos we've already downloaded
            available_videos = []
            count = 0
            
            for video_url in video_links:
                if count >= max_videos_to_check:
                    break
                
                # Extract video ID
                video_id = video_url.split("=")[-1].split("&")[0]
                
                if not self.is_video_downloaded(video_id):
                    available_videos.append(video_url)
                
                count += 1
            
            if not available_videos:
                print("No new videos available to download from this channel")
                return None
            
            # Choose a random video
            random_video = random.choice(available_videos)
            return random_video
            
        except Exception as e:
            print(f"Error getting random channel video: {e}")
            return None
    
    def download_video_with_ytdlp(self, video_url):
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
            
            return {
                "filepath": filepath,
                "title": title,
                "description": description + "\n\n#shorts" if len(description) < 5000 else description[:4990] + "\n\n#shorts",
                "tags": ["shorts", "trending"],
                "video_id": video_id
            }
            
        except Exception as e:
            print(f"Error downloading with yt-dlp {video_url}: {e}")
            return None
    
    def download_video(self, video_url):
        """Download a single video from YouTube - tries multiple methods"""
        # First try PyTube
        try:
            yt = YouTube(video_url)
            
            # Extract video ID
            video_id = video_url.split("=")[-1].split("&")[0]
            
            # Check if already downloaded
            if self.is_video_downloaded(video_id):
                print(f"Video {yt.title} already downloaded previously. Skipping.")
                return None
                
            video_stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            
            if not video_stream:
                print(f"No suitable stream found for {video_url}")
                raise Exception("No suitable stream found")
            
            # Clean the title to make it a valid filename
            clean_title = "".join([c for c in yt.title if c.isalpha() or c.isdigit() or c == ' ']).rstrip()
            if not clean_title:
                clean_title = video_id  # Use video ID if title is empty after cleaning
            filename = f"{clean_title}.mp4"
            filepath = os.path.join(self.download_dir, filename)
            
            print(f"Downloading with PyTube: {yt.title}")
            video_stream.download(output_path=self.download_dir, filename=filename)
            print(f"Downloaded: {filepath}")
            
            # Mark video as downloaded
            self.mark_video_downloaded(video_id)
            
            return {
                "filepath": filepath,
                "title": yt.title,
                "description": yt.description + "\n\n#shorts" if len(yt.description) < 5000 else yt.description[:4990] + "\n\n#shorts",
                "tags": ["shorts", "trending"],
                "video_id": video_id
            }
            
        except Exception as e:
            print(f"PyTube download failed: {e}")
            print("Trying alternative download method...")
            
            # If PyTube fails, try yt-dlp
            return self.download_video_with_ytdlp(video_url)
    
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
    
    def process_source_channel(self, channel_url):
        """Process a single source channel - download one random video and upload to your channel"""
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
                # Upload the video to YOUR channel
                video_id = self.upload_video_to_my_channel(video_data)
                
                if video_id:
                    print(f"Successfully uploaded video to YOUR channel: {video_data['title']}")
                    print(f"View at: https://www.youtube.com/watch?v={video_id}")
                    return True
                else:
                    print(f"Failed to upload video to YOUR channel: {video_data['title']}")
            
            print(f"Attempt {attempt+1} failed. Trying another video...")
            
        print("All attempts failed. Will try again at next scheduled run.")
        return False

# Main function to schedule the task
def main():
    # List of source channel URLs to download FROM (not yours)
    source_channel_urls = [
        "https://www.youtube.com/@Mywonderland13",  # Using @ username format
        # Add more channels here
    ]
    
    reuploader = YouTubeChannelReuploader()
    
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

if __name__ == "__main__":
    main()