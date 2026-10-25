"""Publicación PÚBLICA y automática en TikTok a través de Upload-Post (upload-post.com).

TikTok solo deja publicar directamente (sin pasar por borradores) a apps auditadas. Upload-Post tiene la suya
auditada: conectas tu cuenta de TikTok en su web una vez y su API publica por ti.

Secreto: UPLOADPOST_API_KEY. Perfiles (variables, con valores por defecto): UPLOADPOST_PERFIL (canal del tiempo)
y UPLOADPOST_PERFIL_ECONOMIA (Toro u Oso): son los nombres de perfil creados en Upload-Post.
Si no hay clave o algo falla, se usa el sistema anterior (borrador en la bandeja de TikTok).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)
API = "https://api.upload-post.com/api"


def disponible() -> bool:
    return bool(os.environ.get("UPLOADPOST_API_KEY", "").strip())


def perfil(canal: str = "tiempo") -> str:
    if canal == "historias":
        return os.environ.get("UPLOADPOST_PERFIL_HISTORIAS", "").strip() or "torouoso"
    if canal == "economia":
        return os.environ.get("UPLOADPOST_PERFIL_ECONOMIA", "").strip() or "torouoso"
    return os.environ.get("UPLOADPOST_PERFIL", "").strip() or "paraguasochanclas"


def _cabeceras():
    return {"Authorization": f"Apikey {os.environ['UPLOADPOST_API_KEY'].strip()}"}


def publicar_tiktok(video: Path, caption: str, canal: str = "tiempo", espera_max: int = 900,
                    programado=None, primer_comentario: str | None = None) -> dict:
    """programado: datetime con zona horaria para dejar la publicación programada en Upload-Post."""
    datos = {
        "user": perfil(canal), "platform[]": "tiktok", "title": caption[:2200], "tiktok_title": caption[:2200],
        "privacy_level": "PUBLIC_TO_EVERYONE", "post_mode": "DIRECT_POST", "is_aigc": "true",
        "is_ai_generated": "true", "cover_timestamp": "0", "async_upload": "true",
    }
    if primer_comentario:
        datos["first_comment"] = primer_comentario[:150]
    if programado is not None:
        datos["scheduled_date"] = programado.isoformat(timespec="seconds")
        datos.pop("async_upload")
    with open(video, "rb") as f:
        r = requests.post(f"{API}/upload", headers=_cabeceras(), data=datos,
                          files={"video": (video.name, f, "video/mp4")}, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"Upload-Post HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    if programado is not None:
        log.info("Upload-Post: programado para %s: %s", programado, str(j)[:300])
        if j.get("success") is False:
            raise RuntimeError(f"Upload-Post no aceptó la programación: {str(j)[:300]}")
        return {"via": "upload-post", "programado": programado.isoformat(), "job_id": j.get("job_id"), "respuesta": j}
    rid = j.get("request_id")
    log.info("Upload-Post: subida iniciada (%s)", rid or j)
    if not rid:  # respuesta síncrona
        return _comprobar(j)
    t0 = time.time()
    estado = {}
    while time.time() - t0 < espera_max:
        time.sleep(15)
        s = requests.get(f"{API}/uploadposts/status", headers=_cabeceras(), params={"request_id": rid}, timeout=30)
        if s.status_code >= 400:
            continue
        estado = s.json()
        st = str(estado.get("status") or estado.get("state") or "").lower()
        if st in ("completed", "complete", "success", "finished", "done", "published"):
            return _comprobar(estado)
        if st in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Upload-Post: TikTok rechazó la publicación: {str(estado)[:400]}")
    # Sin confirmación a tiempo: NO se reintenta (podría duplicar la publicación)
    log.warning("Upload-Post sin confirmación tras %d s (sigue en curso): %s", espera_max, str(estado)[:300])
    return {"via": "upload-post", "pendiente": True, "request_id": rid}


def _comprobar(j: dict) -> dict:
    resultados = j.get("results") or j.get("result") or {}
    tk = resultados.get("tiktok") if isinstance(resultados, dict) else None
    if isinstance(tk, dict) and tk.get("success") is False:
        raise RuntimeError(f"Upload-Post: TikTok falló: {tk.get('error') or tk}")
    log.info("Publicado en TikTok vía Upload-Post: %s", str(tk or j)[:300])
    return {"via": "upload-post", "respuesta": tk or j}
