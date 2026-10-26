"""Descarga las estadísticas de TikTok de un perfil de Upload-Post (vídeos y analíticas por publicación)."""
import json, os, sys, requests
from pathlib import Path
API = "https://api.upload-post.com/api"
H = {"Authorization": f"Apikey {os.environ['UPLOADPOST_API_KEY'].strip()}"}
perfil = sys.argv[1] if len(sys.argv) > 1 else "paraguasochanclas"
out = Path("estadisticas"); out.mkdir(exist_ok=True)
def get(ruta, **p):
    r = requests.get(f"{API}/{ruta}", headers=H, params=p, timeout=60)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:500])
media, cursor = [], None
for _ in range(6):
    p = {"platform": "tiktok", "user": perfil, "limit": 50}
    if cursor: p["cursor"] = cursor
    st, j = get("uploadposts/media", **p)
    print("media", st, str(j)[:200])
    if st != 200: break
    media += j.get("media", [])
    pag = j.get("pagination") or {}
    cursor = pag.get("next_cursor") or pag.get("cursor")
    if not cursor or not pag.get("has_more", pag.get("has_next")): break
print("vídeos:", len(media))
analit = {}
for m in media:
    for params in ({"platform": "tiktok", "user": perfil, "platform_post_id": m["id"]},
                   {"platform": "tiktok", "profile_username": perfil, "platform_post_id": m["id"]}):
        st, j = get("uploadposts/post-analytics", **params)
        if st == 200:
            analit[m["id"]] = j; break
    else:
        analit[m["id"]] = {"error": st, "detalle": str(j)[:300]}
for ruta, p in (("analytics", {"profile_username": perfil, "platforms": "tiktok"}),
                (f"analytics/{perfil}", {"platforms": "tiktok"}),
                ("uploadposts/analytics", {"user": perfil, "platform": "tiktok"})):
    st, j = get(ruta, **p)
    (out / f"perfil_{ruta.replace('/', '_')}.json").write_text(json.dumps({"status": st, "data": j}, ensure_ascii=False, indent=1))
    print(ruta, st, str(j)[:300])
(out / "media.json").write_text(json.dumps(media, ensure_ascii=False, indent=1))
(out / "analiticas.json").write_text(json.dumps(analit, ensure_ascii=False, indent=1))
print("ejemplo analítica:", json.dumps(next(iter(analit.values()), {}), ensure_ascii=False)[:800])

# Comentarios de los 3 vídeos con más visitas
top = sorted(media, key=lambda m: -((analit.get(m["id"], {}).get("platforms") or {}).get("tiktok", {}).get("post_metrics", {}).get("views", 0)))[:3]
coms = {}
for m in top:
    st, j = get("uploadposts/comments", platform="tiktok", user=perfil, post_id=m["id"], limit=50)
    coms[m["id"]] = j if st == 200 else {"error": st}
(out / "comentarios.json").write_text(json.dumps(coms, ensure_ascii=False, indent=1))
