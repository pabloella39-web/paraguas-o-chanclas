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


# El refresh_token se guarda CIFRADO en el repositorio (estado/tiktok_token.enc) con la clave del
# secreto TIKTOK_CIFRADO. Así se puede renovar cada día sin tocar los secretos de GitHub.
# Cada canal tiene su archivo (TIKTOK_ESTADO): el del tiempo y el económico son cuentas distintas.
ESTADO = Path(__file__).resolve().parent.parent / "estado" / os.environ.get("TIKTOK_ESTADO", "tiktok_token.enc")


def _openssl(args: list[str], datos: bytes) -> bytes:
    clave = os.environ.get("TIKTOK_CIFRADO")
    if not clave:
        raise ErrorTikTok("Falta el secreto TIKTOK_CIFRADO")
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-a", "-A",
                        *args, "-pass", "env:TIKTOK_CIFRADO"], input=datos, capture_output=True)
    if r.returncode != 0:
        raise ErrorTikTok(f"openssl: {r.stderr.decode()[:200]}")
    return r.stdout


def guardar_refresh_token(token: str):
    ESTADO.parent.mkdir(exist_ok=True)
    ESTADO.write_bytes(_openssl(["-salt"], token.encode()) + b"\n")
    log.info("refresh_token de TikTok guardado cifrado en %s", ESTADO.name)


def leer_refresh_token() -> str:
    if ESTADO.exists() and os.environ.get("TIKTOK_CIFRADO"):
        return _openssl(["-d"], ESTADO.read_bytes().strip()).decode().strip()
    if os.environ.get("TIKTOK_REFRESH_TOKEN"):
        return os.environ["TIKTOK_REFRESH_TOKEN"]
    raise ErrorTikTok("No hay refresh_token: ejecuta el workflow 'Autorizar TikTok'")


def hay_credenciales() -> list[str]:
    """Devuelve lo que falta para poder publicar (lista vacía = todo listo)."""
    faltan = [v for v in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET") if not os.environ.get(v)]
    if not os.environ.get("TIKTOK_REFRESH_TOKEN") and not (ESTADO.exists() and os.environ.get("TIKTOK_CIFRADO")):
        faltan.append("autorización de TikTok (workflow 'Autorizar TikTok')")
    return faltan


def _pedir_token(datos: dict) -> dict:
    r = requests.post(f"{API}/oauth/token/", data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"].strip(),
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"].strip(), **datos,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    j = r.json()
    if "access_token" not in j:
        raise ErrorTikTok(f"TikTok no devolvió token: {j.get('error')} {j.get('error_description')}")
    return j


def canjear_codigo(codigo: str, redirect_uri: str) -> dict:
    """Primer paso tras autorizar: código -> tokens. Guarda el refresh_token cifrado."""
    j = _pedir_token({"code": codigo, "grant_type": "authorization_code", "redirect_uri": redirect_uri})
    guardar_refresh_token(j["refresh_token"])
    return {"scope": j.get("scope"), "dias_validez": int(j.get("refresh_expires_in", 0)) // 86400}


def refrescar_token() -> str:
    """Obtiene un access_token nuevo (dura 24 h). Si TikTok rota el refresh_token, se guarda el nuevo."""
    actual = leer_refresh_token()
    j = _pedir_token({"grant_type": "refresh_token", "refresh_token": actual})
    nuevo = j.get("refresh_token")
    if nuevo and (nuevo != actual or not ESTADO.exists()) and os.environ.get("TIKTOK_CIFRADO"):
        guardar_refresh_token(nuevo)
    return j["access_token"]


def _info_creador(token: str) -> dict:
    r = requests.post(f"{API}/post/publish/creator_info/query/", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}, timeout=30)
    return _comprobar(r)


def _trozos(tam: int):
    """Hasta 64 MB se sube de una vez (TikTok lo exige por debajo de 5 MB y lo permite hasta 64 MB)."""
    if tam <= 64 * MB:
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
