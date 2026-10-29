"""Optional YouTube upload via the official YouTube Data API (you log in with your own Google account).

One-time setup (about 10 minutes):
 1. console.cloud.google.com -> create a project -> enable "YouTube Data API v3".
 2. APIs & Services -> OAuth consent screen: External, add yourself as a Test user.
 3. Credentials -> Create credentials -> OAuth client ID -> Desktop app -> download JSON.
 4. Save it as data/client_secret.json (or upload it in the app sidebar).
The first upload opens a browser to ask permission; after that the token is cached in data/token.json.

Uploads default to PRIVATE so you can review in YouTube Studio and publish yourself.
The API allows about 100 uploads per day on the default quota, far more than you should ever post.
"""
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service(secrets_path: Path, token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload_video(video_path, title, description, tags, secrets_path, token_path,
                 thumbnail_path=None, privacy="private", contains_synthetic_media=False,
                 category_id="27", is_short=False, progress_cb=None):
    """Returns (studio_url, thumbnail_note). category 27 = Education, 28 = Science & Technology, 22 = People & Blogs."""
    from googleapiclient.http import MediaFileUpload

    yt = _service(Path(secrets_path), Path(token_path))
    desc = description
    if is_short and "#shorts" not in desc.lower():
        desc = (desc + "\n\n#Shorts").strip()
    body = {
        "snippet": {
            "title": title[:100],
            "description": desc[:4900],
            "tags": [t for t in tags if t][:15],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": bool(contains_synthetic_media),
        },
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status and progress_cb:
            progress_cb(status.progress())
    vid = resp["id"]
    thumb_note = ""
    if thumbnail_path and not is_short:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail_path))).execute()
        except Exception as e:  # custom thumbnails need a verified channel
            thumb_note = f" (thumbnail not set: {e})"
    return f"https://studio.youtube.com/video/{vid}/edit", thumb_note
