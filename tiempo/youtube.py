"""Subida automática a YouTube Shorts (YouTube Data API v3).

Secretos: YT_CLIENT_ID y YT_CLIENT_SECRET (cliente OAuth de Google Cloud) y TIKTOK_CIFRADO (se reutiliza para
cifrar el token). La autorización se hace una vez con el workflow "Autorizar YouTube" y el refresh_token se
guarda cifrado en estado/youtube_token.enc.

Los vídeos verticales de menos de 3 minutos se publican automáticamente como Shorts.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from pathlib import Path

import requests

from .config import RAIZ
from .tiktok import _openssl

log = logging.getLogger(__name__)
ESTADO = RAIZ / "estado" / "youtube_token.enc"
ESTADOS = {"tiempo": ESTADO, "historias": RAIZ / "estado" / "youtube_token_historias.enc"}
REDIRECT_URI = "https://pabloella39-web.github.io/paraguas-o-chanclas/callback.html"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _cliente() -> tuple[str, str]:
    return os.environ.get("YT_CLIENT_ID", "").strip(), os.environ.get("YT_CLIENT_SECRET", "").strip()


def hay_credenciales(canal: str = "tiempo") -> bool:
    cid, sec = _cliente()
    return bool(cid and sec and ESTADOS[canal].exists() and os.environ.get("TIKTOK_CIFRADO"))


def url_autorizacion(client_id: str) -> str:
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": REDIRECT_URI, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": "youtube"})


def canjear_codigo(codigo: str, canal: str = "tiempo") -> dict:
    cid, sec = _cliente()
    r = requests.post(TOKEN_URL, data={"code": codigo, "client_id": cid, "client_secret": sec,
                                       "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"}, timeout=30)
    j = r.json()
    if "refresh_token" not in j:
        raise RuntimeError(f"Google no devolvió refresh_token: {j.get('error')} {j.get('error_description')}")
    ESTADOS[canal].parent.mkdir(exist_ok=True)
    ESTADOS[canal].write_bytes(_openssl(["-salt"], j["refresh_token"].encode()) + b"\n")
    return {"scope": j.get("scope")}


def _access_token(canal: str = "tiempo") -> str:
    cid, sec = _cliente()
    refresh = _openssl(["-d"], ESTADOS[canal].read_bytes().strip()).decode().strip()
    r = requests.post(TOKEN_URL, data={"client_id": cid, "client_secret": sec, "refresh_token": refresh,
                                       "grant_type": "refresh_token"}, timeout=30)
    j = r.json()
    if "access_token" not in j:
        raise RuntimeError(f"No se pudo renovar el acceso a YouTube: {j.get('error')} {j.get('error_description')}")
    return j["access_token"]


def subir(video: Path, titulo: str, descripcion: str, etiquetas: list[str], canal: str = "tiempo",
          publicar_en=None, categoria: str = "22") -> dict:
    """publicar_en: datetime con zona horaria → se sube privado y YouTube lo publica a esa hora."""
    token = _access_token(canal)
    meta = {
        "snippet": {"title": titulo[:100], "description": descripcion[:4900], "tags": etiquetas[:15],
                    "categoryId": categoria, "defaultLanguage": "es", "defaultAudioLanguage": "es"},
        "status": {"privacyStatus": os.environ.get("YT_PRIVACIDAD", "public"), "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True, "embeddable": True},
    }
    if publicar_en is not None:
        meta["status"]["privacyStatus"] = "private"
        meta["status"]["publishAt"] = publicar_en.astimezone(__import__("datetime").timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    tam = video.stat().st_size
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos",
                      params={"uploadType": "resumable", "part": "snippet,status"},
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(tam)},
                      data=json.dumps(meta), timeout=60)
    if r.status_code != 200 or "Location" not in r.headers:
        raise RuntimeError(f"YouTube (inicio de subida) HTTP {r.status_code}: {r.text[:300]}")
    with open(video, "rb") as f:
        r2 = requests.put(r.headers["Location"], data=f, headers={"Content-Type": "video/mp4",
                                                                  "Content-Length": str(tam)}, timeout=600)
    if r2.status_code not in (200, 201):
        raise RuntimeError(f"YouTube (subida) HTTP {r2.status_code}: {r2.text[:300]}")
    j2 = r2.json()
    vid = j2["id"]
    canal_yt = (j2.get("snippet") or {}).get("channelTitle")
    log.info("Subido a YouTube Shorts (%s): https://youtube.com/shorts/%s", canal_yt, vid)
    return {"id": vid, "url": f"https://youtube.com/shorts/{vid}", "canal": canal_yt}


def subir_con_reintentos(video: Path, titulo: str, descripcion: str, etiquetas: list[str], intentos: int = 3,
                         **kw):
    for i in range(1, intentos + 1):
        try:
            return subir(video, titulo, descripcion, etiquetas, **kw)
        except Exception as e:  # noqa: BLE001
            if i == intentos:
                raise
            log.warning("YouTube falló (intento %d/%d): %s", i, intentos, e)
            time.sleep(60 * i)


def textos(caption: str, titular: str | None, fecha_txt: str, tipo: str = "hoy") -> tuple[str, str, list[str]]:
    """Título (pensado para el buscador de YouTube: lo que la gente escribe), descripción y etiquetas."""
    gancho = caption.split("\n", 1)[0].strip() or "¿Paraguas o chanclas?"   # frase gancho (mayúsculas normales)
    busqueda = {"manana": f"El tiempo para mañana, {fecha_txt}, en España",
                "hoy": f"El tiempo hoy, {fecha_txt}, en España",
                "semana": f"El tiempo de la semana en España ({fecha_txt})",
                "finde": f"El tiempo del fin de semana en España ({fecha_txt})",
                "aviso": f"Aviso de AEMET: {fecha_txt}"}.get(tipo, f"El tiempo en España, {fecha_txt}")
    titulo = f"{busqueda} | {gancho}"
    if len(titulo) > 100:
        titulo = busqueda[:100]
    hashtags = [w.lstrip("#") for w in caption.split() if w.startswith("#")]
    descripcion = (caption + "\n\nPrevisión diaria del tiempo en España con datos de AEMET y Open-Meteo "
                   "(CC BY 4.0). Voz generada con IA.\nSuscríbete para tener el tiempo de cada día ☂️🩴")
    etiquetas = ["el tiempo", "tiempo España", "previsión del tiempo", "AEMET", "meteorología", "shorts"] + hashtags
    return titulo, descripcion, etiquetas
