"""Descarga la foto de perfil actual de TikTok (@paraguasochanclas)."""
import json
import os
import re
import urllib.request
from pathlib import Path

Path("prueba").mkdir(exist_ok=True)
urls = []
try:   # 1) Upload-Post: perfiles con sus cuentas conectadas
    from tiempo import uploadpost
    import requests
    r = requests.get("https://api.upload-post.com/api/uploadposts/users", headers=uploadpost._cabeceras(), timeout=40)
    t = r.text
    print("upload-post", r.status_code, t[:300])
    urls += re.findall(r'https://[^"\s]+(?:tiktokcdn|ibyteimg|muscdn)[^"\s]*', t)
except Exception as e:  # noqa: BLE001
    print("upload-post", e)
try:   # 2) la página pública del perfil
    req = urllib.request.Request("https://www.tiktok.com/@paraguasochanclas",
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                          "(KHTML, like Gecko) Chrome/120 Safari/537.36", "Accept-Language": "es-ES"})
    html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
    for k in ("avatarLarger", "avatarMedium", "avatarThumb"):
        m = re.search(rf'"{k}":"([^"]+)"', html)
        if m:
            urls.append(m.group(1).encode().decode("unicode_escape"))
    print("pagina", len(html))
except Exception as e:  # noqa: BLE001
    print("pagina", e)
print("URLS", urls[:6])
for i, u in enumerate(urls[:4]):
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.tiktok.com/"})
        Path(f"prueba/avatar_{i}.img").write_bytes(urllib.request.urlopen(req, timeout=40).read())
        print("ok", i)
    except Exception as e:  # noqa: BLE001
        print("fallo", i, e)
