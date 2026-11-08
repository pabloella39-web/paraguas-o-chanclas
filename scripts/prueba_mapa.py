"""Últimas publicaciones en TikTok e Instagram según Upload-Post."""
import requests
from tiempo import uploadpost
for plat, perfil in (("tiktok", uploadpost.perfil("tiempo")), ("instagram", uploadpost.perfil_instagram())):
    r = requests.get("https://api.upload-post.com/api/uploadposts/media", headers=uploadpost._cabeceras(),
                     params={"platform": plat, "user": perfil, "limit": 3}, timeout=40)
    for m in r.json().get("media", []):
        print(plat, m.get("id"), m.get("timestamp"), (m.get("caption") or "")[:70].replace("\n", " "))
