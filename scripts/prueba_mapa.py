"""IDs de los últimos vídeos de TikTok según Upload-Post."""
import json
import requests
from tiempo import uploadpost
r = requests.get("https://api.upload-post.com/api/uploadposts/media", headers=uploadpost._cabeceras(),
                 params={"platform": "tiktok", "user": uploadpost.perfil("tiempo"), "limit": 6}, timeout=40)
for m in r.json().get("media", []):
    print(m.get("id"), m.get("timestamp"), (m.get("caption") or "")[:60].replace("\n", " "))
