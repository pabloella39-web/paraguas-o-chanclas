"""Publicación en TikTok con la Content Posting API (Direct Post o bandeja de borradores)."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)
API = "https://open.tiktokapis.com/v2"
MB = 1024 * 1024


class ErrorTikTok(RuntimeError):
    pass


def _comprobar(r: requests.Response) -> dict:
    try:
        j = r.json()
    except ValueError:
        raise ErrorTikTok(f"HTTP {r.status_code}: {r.text[:300]}")
    err = j.get("error", {})
    if r.status_code >= 400 or (isinstance(err, dict) and err.get("code") not in (None, "ok")):
        raise ErrorTikTok(f"HTTP {r.status_code} {err.get('code')}: {err.get('message')} (log_id {err.get('log_id')})")
    return j.get("data", j)


def refrescar_token() -> str:
    """Obtiene un access_token nuevo (dura 24 h) a partir del refresh_token (dura 365 días)."""
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    j = r.json()
    if "access_token" not in j:
        raise ErrorTikTok(f"No se pudo refrescar el token: {j}")
    nuevo = j.get("refresh_token")
    if nuevo and nuevo != os.environ["TIKTOK_REFRESH_TOKEN"]:
        _guardar_refresh_token(nuevo)
    return j["access_token"]


def _guardar_refresh_token(token: str):
    """TikTok puede rotar el refresh_token: se guarda en el secreto del repo si hay GH_PAT."""
    if not os.environ.get("GH_PAT") or not os.environ.get("GITHUB_REPOSITORY"):
        log.warning("TikTok ha devuelto un refresh_token nuevo pero no hay GH_PAT para guardarlo. "
                     "Actualiza el secreto TIKTOK_REFRESH_TOKEN a mano si la próxima ejecución falla.")
        return
    subprocess.run(["gh", "secret", "set", "TIKTOK_REFRESH_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"],
                    "--body", token], env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]}, check=True,
                   capture_output=True)
    log.info("refresh_token de TikTok actualizado en los secretos del repositorio")


def _info_creador(token: str) -> dict:
    r = requests.post(f"{API}/post/publish/creator_info/query/", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}, timeout=30)
    return _comprobar(r)


def _trozos(tam: int):
    if tam < 5 * MB:
        return tam, 1
    chunk = 10 * MB
    return chunk, tam // chunk  # el último trozo absorbe el resto


def _subir(url: str, ruta: Path, tam: int, chunk: int, n: int):
    with open(ruta, "rb") as f:
        for i in range(n):
            inicio = i * chunk
            fin = tam - 1 if i == n - 1 else inicio + chunk - 1
            f.seek(inicio)
            datos = f.read(fin - inicio + 1)
            for intento in range(4):
                r = requests.put(url, data=datos, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(datos)),
                    "Content-Range": f"bytes {inicio}-{fin}/{tam}"}, timeout=300)
                if r.status_code in (200, 201, 206):
                    break
                if r.status_code < 500:
                    raise ErrorTikTok(f"Subida trozo {i + 1}/{n}: HTTP {r.status_code} {r.text[:200]}")
                time.sleep(5 * (intento + 1))
            else:
                raise ErrorTikTok(f"Subida trozo {i + 1}/{n} falló tras reintentos")
            log.info("Subido trozo %d/%d", i + 1, n)


def _estado(token: str, publish_id: str, espera_max=600) -> dict:
    t0 = time.time()
    while time.time() - t0 < espera_max:
        r = requests.post(f"{API}/post/publish/status/fetch/", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={"publish_id": publish_id}, timeout=30)
        d = _comprobar(r)
        estado = d.get("status")
        log.info("Estado TikTok: %s", estado)
        if estado in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            return d
        if estado == "FAILED":
            raise ErrorTikTok(f"TikTok rechazó el vídeo: {d.get('fail_reason')}")
        time.sleep(10)
    raise ErrorTikTok("Tiempo de espera agotado consultando el estado de la publicación")


def publicar(ruta: Path, caption: str, portada_ms: int = 2000) -> dict:
    token = refrescar_token()
    tam = ruta.stat().st_size
    chunk, n = _trozos(tam)
    fuente = {"source": "FILE_UPLOAD", "video_size": tam, "chunk_size": chunk, "total_chunk_count": n}
    modo = os.environ.get("TIKTOK_MODO", "directo")
    cab = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}

    if modo == "borrador":
        r = requests.post(f"{API}/post/publish/inbox/video/init/", headers=cab, json={"source_info": fuente},
                          timeout=30)
    else:
        info = _info_creador(token)
        opciones = info.get("privacy_level_options", [])
        deseada = os.environ.get("TIKTOK_PRIVACIDAD", "PUBLIC_TO_EVERYONE")
        privacidad = deseada if deseada in opciones else ("SELF_ONLY" if "SELF_ONLY" in opciones else opciones[0])
        if privacidad != deseada:
            log.warning("Privacidad %s no disponible (opciones: %s). Se usa %s. "
                        "Si la app no está auditada, TikTok solo permite privado.", deseada, opciones, privacidad)
        r = requests.post(f"{API}/post/publish/video/init/", headers=cab, json={
            "post_info": {
                "title": caption[:2200],
                "privacy_level": privacidad,
                "disable_duet": False, "disable_stitch": False,
                "disable_comment": bool(info.get("comment_disabled", False)),
                "video_cover_timestamp_ms": portada_ms,
                "brand_content_toggle": False, "brand_organic_toggle": False,
                "is_aigc": True,  # voz y guion generados con IA: TikTok exige etiquetarlo
            },
            "source_info": fuente,
        }, timeout=30)
    d = _comprobar(r)
    _subir(d["upload_url"], ruta, tam, chunk, n)
    res = _estado(token, d["publish_id"])
    return {"publish_id": d["publish_id"], **res}
