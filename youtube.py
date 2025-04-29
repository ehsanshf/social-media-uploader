import yt_dlp
import os

# Channel URL
channel_url = "https://www.youtube.com/@Mywonderland13"

# Directory for saving videos
DOWNLOAD_DIR = "videos/Youtube"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Extract all videos from the channel
def get_video_list(channel_url):
    """Fetch list of videos from a channel (sorted from oldest to newest)"""
    ydl_opts = {
        "quiet": False,
        "extract_flat": True,  # Get video URLs only
        "playlistreverse": True,  # Forces the oldest video to be first
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

        # Ensure "entries" exists and is a list
        if "entries" in info and isinstance(info["entries"], list):
            video_urls = []
            for entry in info["entries"]:
                # Some entries might be dictionaries without "url", so we handle that safely
                if isinstance(entry, dict) and "url" in entry:
                    video_urls.append(entry["url"])
            
            return video_urls

    return []

# Download one video at a time, starting from the oldest
def download_video(video_url):
    """Download a single video"""
    ydl_opts = {
        "format": "best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

# Get sorted video list
video_list = get_video_list(channel_url)

if not video_list:
    print("No videos found!")
else:
    print(f"Total videos found: {len(video_list)}")

    # Download each video one by one
    for index, video_url in enumerate(video_list):
        print(f"Downloading {index + 1}/{len(video_list)}: {video_url}")
        download_video(video_url)
