"""Imágenes libres (Openverse, solo CC0 y dominio público), ambientes sonoros y música (ElevenLabs, guardados en
el repositorio para reutilizarlos y no gastar créditos cada día)."""
from __future__ import annotations

import hashlib
import io
import logging
import os
import random
import re
import subprocess
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .config import ALTO, ANCHO, ASSETS

log = logging.getLogger(__name__)
SR = 48000
UA = {"User-Agent": "LoQueCallanLasParedes/1.0 (canal de relatos; contacto vía GitHub)"}
ELEVEN = "https://api.elevenlabs.io/v1"

# ---------------------------------------------------------------- imágenes
TINTES = {"ficcion": (0.80, 0.95, 1.10), "leyenda": (1.10, 0.95, 0.78), "real": (1.04, 1.0, 0.92)}
SEPIA = (1.12, 0.98, 0.78)   # historia: tono de foto antigua
HISTORICOS = ("guerra_mundial", "espana", "asia", "siglo_xx", "antigua", "pueblos")


LIBRES = ("cc0", "public domain", "pd", "no restrictions", "copyrighted free use")


def buscar_imagenes(consulta: str, n: int = 3) -> list[dict]:
    """Wikimedia Commons: solo dominio público y CC0 (no hace falta atribución)."""
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 30,
            "gsrsearch": f"filetype:bitmap {consulta}", "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1400})
        r.raise_for_status()
        paginas = (r.json().get("query") or {}).get("pages", {}).values()
    except Exception as e:  # noqa: BLE001
        log.warning("Wikimedia '%s': %s", consulta, e)
        return []
    res = []
    for pg in paginas:
        ii = (pg.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata") or {}
        lic = str((meta.get("LicenseShortName") or {}).get("value", "")).lower()
        if not any(lic.startswith(l) or l in lic for l in LIBRES) or "by" in lic.replace("by-sa", "by"):
            continue
        if ii.get("mime") != "image/jpeg" or (ii.get("width") or 0) < 800:  # PNG suele ser carteles y gráficos
            continue
        if re.search(r"poster|logo|map|mapa|diagram|chart|cover|flag|bandera|coat of arms|escudo|book|page|text|"
                     r"stamp|sello|card|portrait|retrato|ad\b|advert|magazine|puck|cartoon|caricatur|comic|dpla", pg.get("title", ""), re.I):
            continue
        res.append({"id": pg.get("pageid"), "title": pg.get("title", ""), "license": lic, "url": ii.get("thumburl"),
                    "thumbnail": ii.get("url"), "width": ii.get("width"), "height": ii.get("height"),
                    "orden": pg.get("index", 99)})
    res.sort(key=lambda x: x["orden"])
    return res[: n * 3]


def descargar(info: dict) -> Image.Image | None:
    for url in (info.get("url"), info.get("thumbnail")):
        if not url:
            continue
        try:
            r = requests.get(url, headers=UA, timeout=40)
            if r.status_code == 200 and len(r.content) > 20_000:
                im = Image.open(io.BytesIO(r.content))
                im = ImageOps.exif_transpose(im).convert("RGB")
                if min(im.size) >= 500:
                    return im
        except Exception:  # noqa: BLE001
            continue
    return None


def tratar(im: Image.Image, tipo: str) -> Image.Image:
    """Recorta a vertical (con margen para el movimiento) y le da el aspecto oscuro y frío del canal."""
    W, H = int(ANCHO * 1.18), int(ALTO * 1.18)
    im = ImageOps.fit(im, (W, H), Image.LANCZOS)
    if tipo in HISTORICOS:  # foto de archivo: sepia suave, contraste y algo de oscuridad para leer los textos
        im = ImageEnhance.Color(im).enhance(0.15)
        im = ImageEnhance.Contrast(im).enhance(1.18)
        a = np.asarray(im).astype(np.float32) / 255
        a = a ** 1.15 * 0.80 * np.array(SEPIA)
        return Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    im = ImageEnhance.Color(im).enhance(0.35)
    im = ImageEnhance.Contrast(im).enhance(1.25)
    a = np.asarray(im).astype(np.float32) / 255
    a = a ** 1.35 * 0.78                                 # más oscuro
    a *= np.array(TINTES.get(tipo, TINTES["ficcion"]))
    return Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))


def imagenes_para(escenas: list[str], tipo: str, usadas: set) -> list[Image.Image | None]:
    """Una imagen por escena, en el mismo orden (None si no se encontró ninguna)."""
    out = []
    for esc in escenas:
        candidatos = buscar_imagenes(esc)
        if not candidatos and len(esc.split()) > 1:  # segundo intento, más general ("dark mill interior" → "mill interior")
            candidatos = buscar_imagenes(" ".join(esc.split()[-2:])) or buscar_imagenes(esc.split()[-1])
        elegida = None
        for info in candidatos:
            if info.get("id") in usadas:
                continue
            im = descargar(info)
            if im is not None:
                usadas.add(info.get("id"))
                elegida = tratar(im, tipo)
                log.info("Imagen '%s': %s (%s)", esc, info.get("title", "")[:50], info.get("license"))
                break
        if elegida is None:
            log.info("Sin imagen para '%s'", esc)
        out.append(elegida)
    return out


def fondo_procedural(semilla: int, tipo: str) -> Image.Image:
    """Respaldo sin red: niebla oscura con textura."""
    rnd = np.random.default_rng(semilla)
    W, H = int(ANCHO * 1.18), int(ALTO * 1.18)
    base = rnd.random((H // 16, W // 16)).astype(np.float32)
    im = Image.fromarray((base * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(30))
    a = np.asarray(im).astype(np.float32) / 255 * 0.32
    rgb = np.stack([a, a, a], -1) * np.array(SEPIA if tipo in HISTORICOS else TINTES.get(tipo, TINTES["ficcion"]))
    return Image.fromarray(np.clip(rgb * 255, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- sonido
def _a_wav(src: Path, dst: Path, norm="-24"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", str(SR), "-ac", "1",
                    "-af", f"loudnorm=I={norm}:TP=-2", str(dst)], check=True)
    import wave
    with wave.open(str(dst)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


AMBIENTES = {
    "lluvia": "steady heavy rain on a window at night, distant thunder rumble, dark ambience, no music",
    "tormenta": "violent thunderstorm at night, close thunder cracks, wind and rain, horror ambience",
    "viento": "howling cold wind around an old house at night, eerie whistling, horror ambience",
    "bosque_noche": "dark forest at night, crickets, distant owl, twigs snapping, unsettling ambience",
    "casa_crujidos": "old empty house at night, creaking wooden floor, faint knocks inside walls, clock ticking",
    "sotano_goteo": "damp basement, slow water drips echoing, low hum, distant metallic creak",
    "ciudad_noche": "empty city street at night, distant traffic, buzzing street lamp, faraway siren",
    "carretera_noche": "lonely road at night, car engine idling, wind, distant dog barking",
    "mar_noche": "dark sea at night, waves crashing on rocks, wind, creaking boat ropes",
    "pueblo_silencio": "silent village at night, faint wind, distant church bell, dog howling far away",
    "hospital": "abandoned hospital corridor, flickering fluorescent buzz, distant footsteps echo",
    "iglesia": "empty old church at night, deep reverb, faint whispers, candle crackle, wind",
    "guerra": "distant war ambience, artillery explosions far away, rumbling, occasional gunfire, wind, no music",
    "multitud": "anxious crowd murmuring in a historic city square, distant shouts, footsteps, bells, no music",
    "ciudad_antigua": "old town street early 20th century, horse carriage on cobblestones, distant church bells, "
                      "vendors, no music",
}
GOLPE = "deep cinematic horror impact boom with reverb tail, dark and sudden"


def _eleven_sonido(prompt: str, destino: Path, segundos: float) -> bool:
    clave = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not clave:
        return False
    try:
        r = requests.post(f"{ELEVEN}/sound-generation", headers={"xi-api-key": clave},
                          json={"text": prompt, "duration_seconds": segundos, "prompt_influence": 0.55}, timeout=180)
        if r.status_code == 200 and len(r.content) > 10_000:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(r.content)
            log.info("Sonido nuevo con ElevenLabs: %s", destino.name)
            return True
        log.warning("ElevenLabs sonido HTTP %s: %s", r.status_code, r.text[:200])
    except Exception as e:  # noqa: BLE001
        log.warning("ElevenLabs sonido: %s", e)
    return False


def ambiente(nombre: str, segundos: float) -> np.ndarray:
    ruta = ASSETS / "sonidos" / f"{nombre}.mp3"
    if not ruta.exists():
        _eleven_sonido(AMBIENTES.get(nombre, AMBIENTES["viento"]), ruta, 22)
    n = int(segundos * SR)
    if not ruta.exists():  # ruido de viento sintético
        ruido = np.random.default_rng(1).standard_normal(n).astype(np.float32)
        k = 400
        return np.convolve(ruido, np.ones(k) / k, mode="same") * 0.6
    d = _a_wav(ruta, Path(f"/tmp/amb_{nombre}.wav"))
    f = min(int(1.5 * SR), len(d) // 3)
    out = d.copy()
    while len(out) < n:  # bucle con fundido cruzado
        cruce = out[-f:] * np.linspace(1, 0, f) + d[:f] * np.linspace(0, 1, f)
        out = np.concatenate([out[:-f], cruce, d[f:]])
    return out[:n]


def golpe() -> np.ndarray | None:
    ruta = ASSETS / "sonidos" / "golpe.mp3"
    if not ruta.exists():
        _eleven_sonido(GOLPE, ruta, 4)
    return _a_wav(ruta, Path("/tmp/golpe.wav"), "-16") if ruta.exists() else None


MUSICA = ["Dark ambient horror drone for a true crime and horror story narration: low cello, deep sub bass pulse, "
          "distant piano notes, slow and tense, 60 bpm, no vocals, seamless background loop",
          "Mysterious suspense underscore for a crime story podcast: ticking clock pulse, muted strings, dark synth "
          "pads, subtle heartbeat, tense, no vocals, background loop",
          "Eerie haunted atmosphere for ghost story narration: music box melody detuned, whispering pads, reversed "
          "piano, cold and unsettling, no vocals, background loop",
          "Cinematic dread for a scary story: slow rising strings, deep drones, sparse percussion hits, dark and "
          "ominous, no vocals, background loop"]


def musica(segundos: float, semilla: int) -> np.ndarray | None:
    carpeta = ASSETS / "musica"
    carpeta.mkdir(parents=True, exist_ok=True)
    pistas = sorted(carpeta.glob("*.mp3"))
    clave = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if len(pistas) < len(MUSICA) and clave:
        try:
            r = requests.post(f"{ELEVEN}/music", params={"output_format": "mp3_44100_128"},
                              headers={"xi-api-key": clave, "Content-Type": "application/json"},
                              json={"prompt": MUSICA[len(pistas)], "music_length_ms": 90000, "force_instrumental": True},
                              timeout=300)
            if r.status_code == 200 and len(r.content) > 50_000:
                (carpeta / f"tension_{len(pistas) + 1}.mp3").write_bytes(r.content)
                pistas = sorted(carpeta.glob("*.mp3"))
            else:
                log.warning("ElevenLabs Music HTTP %s: %s", r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            log.warning("Música: %s", e)
    if not pistas:
        return None
    p = pistas[semilla % len(pistas)]
    d = _a_wav(p, Path(f"/tmp/mus_{p.stem}.wav"))
    return np.resize(d, int(segundos * SR))


def clave_estable(*partes) -> int:
    return int(hashlib.md5("|".join(map(str, partes)).encode()).hexdigest()[:8], 16)


if __name__ == "__main__":  # prueba: python -m historias.medios "abandoned house" "dark forest"
    import sys
    logging.basicConfig(level=logging.INFO)
    salida = Path("muestras_imagenes")
    salida.mkdir(exist_ok=True)
    ims = [i for i in imagenes_para(sys.argv[1:], "guerra_mundial", set()) if i is not None]
    for k, im in enumerate(ims):
        im.resize((540, 960)).save(salida / f"{k:02d}.jpg", quality=80)
    print(f"{len(ims)} de {len(sys.argv) - 1} imágenes")

__all__ = ["imagenes_para", "fondo_procedural", "ambiente", "golpe", "musica", "SR", "clave_estable", "random"]
