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


# Primer comentario del canal en cada vídeo del tiempo: arranca la conversación y pide lo que luego contestamos
# Cambia cada día; todos piden el pueblo o la ciudad (así el sistema sabe que en ese vídeo hay que contestar)
COMENTARIOS_PUEBLO = [
    "📍 Escribe tu pueblo y te digo si mañana toca paraguas o chanclas 👇",
    "¿Desde qué pueblo nos ves? Te contesto con tu previsión de mañana 🌦️👇",
    "☔ o 🩴 Dime tu ciudad y te digo cuál te toca mañana",
    "¿Acerté en tu pueblo? Cuéntame cómo está el cielo por ahí y te doy la previsión de mañana 👀",
    "Reto: dime el pueblo más pequeño que conozcas y te digo qué tiempo hará mañana allí 😏📍",
    "¿Qué tal por tu ciudad? Escríbela y te digo si mañana sales con paraguas o con chanclas 👇",
    "📍 Tu pueblo + 👇 = tu previsión de mañana. ¡Prueba!",
    "¿Llueve, hace sol o ni fu ni fa por tu pueblo? Dímelo y te cuento lo de mañana 🌤️",
    "Gente de los pueblos: ¡vuestro momento! Escribid vuestro pueblo y os digo el tiempo de mañana 🙌",
    "¿Paraguas o chanclas mañana en tu ciudad? Escríbela y salimos de dudas 👇",
]


def comentario_pueblo(d=None) -> str:
    from datetime import date as _d
    return COMENTARIOS_PUEBLO[(d or _d.today()).toordinal() % len(COMENTARIOS_PUEBLO)]


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


def perfil_instagram() -> str:
    """El Instagram del canal del tiempo quedó conectado en el perfil «default» de Upload-Post."""
    return os.environ.get("UPLOADPOST_PERFIL_INSTAGRAM", "").strip() or "default"


def _portada_jpg(video: Path) -> Path | None:
    """El primer fotograma (la portada con la fecha) como JPEG, para la portada del Reel."""
    import subprocess
    out = video.with_suffix(".portada.jpg")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0", "-i", str(video), "-frames:v", "1",
                        "-q:v", "3", str(out)], check=True, timeout=60)
        return out if out.exists() and out.stat().st_size < 8_000_000 else None
    except Exception as e:  # noqa: BLE001
        log.warning("Sin portada para Instagram: %s", e)
        return None


GENERICOS_IG = ["#eltiempo", "#previsiondeltiempo", "#tiempoespaña", "#meteorologia"]
GENERICOS_TK = {"#eltiempo", "#tiempomañana", "#paraguasochanclas", "#lluvia", "#aviso", "#aemet", "#fyp",
                "#parati", "#tiempo", "#finde", "#findesemana", "#frio", "#calor"}


def caption_instagram(caption: str) -> str:
    """El texto de TikTok adaptado a Instagram: mismo gancho y resumen (Instagram busca por esas palabras), una
    línea con palabras de búsqueda y 5 hashtags en vez de la lista de TikTok."""
    import re
    lineas = caption.rstrip().splitlines()
    tags = []
    while lineas and (lineas[-1].strip().startswith("#") or not lineas[-1].strip()):
        tags = re.findall(r"#\w+", lineas.pop()) + tags
    locales = [t for t in tags if t.lower() not in GENERICOS_TK][:1]
    aviso = any(t.lower() in ("#aviso", "#aemet") for t in tags)
    nuevos = (["#avisoaemet"] if aviso else []) + GENERICOS_IG[:3] + locales + GENERICOS_IG[3:]
    cuerpo = "\n".join(lineas).rstrip()
    clave = "Previsión del tiempo en España con datos de AEMET · Sigue la cuenta para el parte de cada día"
    return f"{cuerpo}\n\n{clave}\n\n{' '.join(dict.fromkeys(nuevos[:5]))}"[:2200]


def publicar_instagram(video: Path, caption: str, espera_max: int = 900) -> dict:
    """Publica el vídeo como Reel (también en el feed) en el Instagram del canal."""
    datos = {"user": perfil_instagram(), "platform[]": "instagram", "title": caption_instagram(caption),
             "media_type": "REELS", "share_to_feed": "true", "async_upload": "true"}
    portada = _portada_jpg(video)
    with open(video, "rb") as f:
        files = {"video": (video.name, f, "video/mp4")}
        if portada:
            files["cover_image"] = (portada.name, open(portada, "rb"), "image/jpeg")
        r = requests.post(f"{API}/upload", headers=_cabeceras(), data=datos, files=files, timeout=600)
    if r.status_code >= 400:
        raise RuntimeError(f"Upload-Post (Instagram) HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    rid = j.get("request_id")
    log.info("Instagram: subida iniciada (%s)", rid or str(j)[:200])
    if not rid:
        return {"via": "upload-post", "respuesta": j}
    t0 = time.time()
    estado = {}
    while time.time() - t0 < espera_max:
        time.sleep(15)
        s_ = requests.get(f"{API}/uploadposts/status", headers=_cabeceras(), params={"request_id": rid}, timeout=30)
        if s_.status_code >= 400:
            continue
        estado = s_.json()
        st = str(estado.get("status") or estado.get("state") or "").lower()
        if st in ("completed", "complete", "success", "finished", "done", "published"):
            res = estado.get("results")
            ig = res.get("instagram") if isinstance(res, dict) else \
                next((x for x in res or [] if isinstance(x, dict) and x.get("platform") == "instagram"), None)
            if isinstance(ig, dict) and ig.get("success") is False:
                raise RuntimeError(f"Instagram falló: {ig.get('error') or ig}")
            log.info("Publicado en Instagram: %s", str(ig or estado)[:300])
            return {"via": "upload-post", "respuesta": ig or estado}
        if st in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Instagram rechazó la publicación: {str(estado)[:400]}")
    log.warning("Instagram sin confirmación tras %d s: %s", espera_max, str(estado)[:300])
    return {"via": "upload-post", "pendiente": True, "request_id": rid}


def redes_conectadas() -> dict:
    """{perfil: {red: usuario}} según Upload-Post."""
    r = requests.get(f"{API}/uploadposts/users", headers=_cabeceras(), timeout=40)
    r.raise_for_status()
    return {p["username"]: {k: (v.get("handle") if isinstance(v, dict) else v)
                            for k, v in (p.get("social_accounts") or {}).items() if v}
            for p in r.json().get("profiles", [])}


def comprobar_instagram():
    """Falla si el Instagram del canal ya no está conectado (sesión caducada, permisos retirados...)."""
    redes = redes_conectadas()
    if not (redes.get(perfil_instagram()) or {}).get("instagram"):
        raise RuntimeError(f"Instagram no está conectado en el perfil «{perfil_instagram()}» de Upload-Post "
                           f"(conectadas: {redes})")


def _avisar(motivo: str):
    """Deja constancia para que el workflow termine en rojo (y llegue el correo de GitHub)."""
    from .config import RAIZ
    try:
        (RAIZ / "aviso_instagram.txt").write_text(motivo[:500], encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def instagram_seguro(meta: dict, intentos: int = 3):
    """Publica en Instagram sin que un fallo afecte a TikTok ni a YouTube: comprueba antes la conexión, reintenta si
    Instagram rechaza la subida (un rechazo no publica nada, así que no hay duplicados) y, si al final no sale,
    avisa (el workflow acaba en rojo y llega el correo)."""
    if os.environ.get("SIN_INSTAGRAM") or not disponible():
        return
    try:
        comprobar_instagram()
    except Exception as e:  # noqa: BLE001
        log.error("Instagram: %s", e)
        meta["instagram"] = {"error": str(e)[:300]}
        _avisar(f"No se publicó en Instagram: {e}")
        return
    for i in range(1, intentos + 1):
        try:
            meta["instagram"] = publicar_instagram(Path(meta["video"]), meta["caption"])
            if meta["instagram"].get("pendiente"):
                _avisar("Instagram no confirmó la publicación a tiempo: revisa si salió el Reel "
                        f"(request_id {meta['instagram'].get('request_id')})")
            return
        except Exception as e:  # noqa: BLE001
            log.error("Instagram falló (intento %d/%d): %s", i, intentos, e)
            meta["instagram"] = {"error": str(e)[:300]}
            if i < intentos:
                time.sleep(90 * i)
    _avisar(f"No se publicó en Instagram tras {intentos} intentos: {meta['instagram'].get('error')}")


def _comprobar(j: dict) -> dict:
    resultados = j.get("results") or j.get("result") or {}
    tk = resultados.get("tiktok") if isinstance(resultados, dict) else None
    if isinstance(tk, dict) and tk.get("success") is False:
        raise RuntimeError(f"Upload-Post: TikTok falló: {tk.get('error') or tk}")
    log.info("Publicado en TikTok vía Upload-Post: %s", str(tk or j)[:300])
    return {"via": "upload-post", "respuesta": tk or j}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["comprobar"]:
        try:
            comprobar_instagram()
            print("Instagram conectado:", redes_conectadas().get(perfil_instagram()))
        except Exception as e:  # noqa: BLE001
            print(f"::error::{e}")
            _avisar(str(e))
