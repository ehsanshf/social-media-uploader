import yt_dlp
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import google.auth

#Download
ydl_opts = {
    'format': 'best',
    'outtmpl': 'videos/Youtube/%(title)s.%(ext)s'
}

channel_url = "https://www.youtube.com/@Mywonderland13"

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download([channel_url])



# Upload
# Authenticate
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file(
    r"G:\My Drive\Random codes\client_secrets.json", SCOPES
)
creds = flow.run_local_server(port=0)


youtube = build("youtube", "v3", credentials=creds)

# Upload Video
request = youtube.videos().insert(
    part="snippet,status",
    body={
        "snippet": {
            "title": "Test",
            "description": "Hello",
            "tags": ["tag1", "tag2"],
            "categoryId": "22"  # 22 = People & Blogs
        },
        "status": {"privacyStatus": "public"}  # Can be 'private' or 'unlisted'
    },
    media_body=MediaFileUpload("videos/Youtube/test.mp4")
)
response = request.execute()

print("Uploaded Video ID:", response["id"])
