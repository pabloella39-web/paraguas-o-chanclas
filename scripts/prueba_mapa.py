"""Comprueba qué redes tiene conectadas el perfil de Upload-Post."""
import json
import requests
from tiempo import uploadpost
r = requests.get("https://api.upload-post.com/api/uploadposts/users", headers=uploadpost._cabeceras(), timeout=40)
for p in r.json().get("profiles", []):
    print(p["username"], {k: (v.get("handle") if isinstance(v, dict) else v) for k, v in (p.get("social_accounts") or {}).items()})
