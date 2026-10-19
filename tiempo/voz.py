"""Locución (voz IA en español) y pista de audio final."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import subprocess
import wave
from pathlib import Path

import numpy as np
import requests

from .config import VELOCIDAD_EDGE, VOZ_EDGE

log = logging.getLogger(__name__)
SR = 48000


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def duracion(ruta: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


_VOZ = {"edge": None, "google": "MALE"}


def elegir_voz(datos: dict):
    """Fija la voz para todas las síntesis de esta ejecución."""
    _VOZ.update({"edge": datos["edge"], "google": datos["google"]})


def velocidad_base() -> int:
    """Velocidad de la voz en % sobre la normal (p. ej. 15 = un 15 % más rápida)."""
    return int(str(os.environ.get("VELOCIDAD_EDGE", VELOCIDAD_EDGE)).replace("%", "").replace("+", ""))


def _edge(texto: str, ruta: Path, velocidad: int):
    import edge_tts  # se instala en GitHub Actions (requirements.txt)

    async def _run():
        await edge_tts.Communicate(texto, os.environ.get("VOZ_EDGE") or _VOZ["edge"] or VOZ_EDGE,
                                   rate=f"{velocidad:+d}%").save(str(ruta))
    asyncio.run(_run())


def _google_tts(texto: str, ruta: Path, velocidad: int):
    clave = os.environ.get("GOOGLE_TTS_API_KEY") or os.environ.get("GOOGLE_WEATHER_API_KEY")
    if not clave:
        raise RuntimeError("Sin clave para Google TTS")
    voz = {"languageCode": "es-ES", "ssmlGender": _VOZ["google"]}
    if os.environ.get("GOOGLE_TTS_VOICE"):
        voz["name"] = os.environ["GOOGLE_TTS_VOICE"]
    r = requests.post(f"https://texttospeech.googleapis.com/v1/text:synthesize?key={clave}", json={
        "input": {"text": texto}, "voice": voz,
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": round(1 + velocidad / 100, 2)}}, timeout=60)
    r.raise_for_status()
    ruta.write_bytes(base64.b64decode(r.json()["audioContent"]))


def sintetizar(texto: str, ruta_mp3: Path, demo: bool = False, velocidad: int | None = None) -> Path:
    """Devuelve un WAV mono 48 kHz con la locución del bloque."""
    wav = ruta_mp3.with_suffix(".wav")
    if demo:
        # Sin voz: silencio con la duración estimada (≈2,75 palabras/segundo)
        v = velocidad if velocidad is not None else velocidad_base()
        seg = max(1.5, len(texto.split()) / (2.6 * (1 + v / 100)))
        _ffmpeg("-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=mono", "-t", f"{seg:.2f}", str(wav))
        return wav
    velocidad = velocidad if velocidad is not None else velocidad_base()
    errores = []
    for motor in (_edge, _google_tts):
        try:
            motor(texto, ruta_mp3, velocidad)
            if ruta_mp3.exists() and ruta_mp3.stat().st_size > 1000:
                break
        except Exception as e:  # noqa: BLE001
            errores.append(f"{motor.__name__}: {e}")
            log.warning("TTS %s falló: %s", motor.__name__, e)
    else:
        raise RuntimeError(f"Ningún motor de voz funcionó: {errores}")
    # Recorta solo el silencio sobrante de los extremos, dejando 60 ms para no comerse el arranque
    # de las palabras (recortar más fuerte hacía que la voz sonara "trabada")
    recorte = "silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.06"
    _ffmpeg("-i", str(ruta_mp3), "-af", f"{recorte},areverse,{recorte},areverse",
             "-ar", str(SR), "-ac", "1", str(wav))
    return wav


def acelerar(wav: Path, factor: float) -> Path:
    if abs(factor - 1) < 0.005:
        return wav
    out = wav.with_name(wav.stem + "_t.wav")
    _ffmpeg("-i", str(wav), "-af", f"atempo={factor:.4f}", "-ar", str(SR), "-ac", "1", str(out))
    return out


def leer_wav(ruta: Path) -> np.ndarray:
    with wave.open(str(ruta)) as w:
        datos = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if w.getnchannels() == 2:
            datos = datos.reshape(-1, 2).mean(axis=1)
    return datos


def escribir_wav(ruta: Path, datos: np.ndarray):
    datos = np.clip(datos, -1, 1)
    with wave.open(str(ruta), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((datos * 32767).astype(np.int16).tobytes())


def montar_pista(trozos: list[tuple[Path, float]], total: float, musica: np.ndarray | None, salida: Path):
    """trozos = [(wav, inicio_seg)]. Mezcla la voz con la música de fondo (con 'ducking')."""
    n = int(total * SR)
    voz = np.zeros(n, dtype=np.float32)
    for ruta, t0 in trozos:
        d = leer_wav(ruta)
        i = int(t0 * SR)
        fin = min(n, i + len(d))
        voz[i:fin] += d[: fin - i]
    if musica is not None:
        m = np.resize(musica, n).astype(np.float32)
        # Ducking: baja la música cuando hay voz
        env = np.abs(voz)
        k = int(0.25 * SR)
        env = np.convolve(env, np.ones(k) / k, mode="same")
        gan = np.where(env > 0.01, 0.10, 0.22)
        gan = np.convolve(gan, np.ones(k) / k, mode="same")
        fade = np.ones(n)
        fi, fo = int(0.6 * SR), int(1.5 * SR)
        fade[:fi] = np.linspace(0, 1, fi)
        fade[-fo:] = np.linspace(1, 0, fo)
        mezcla = voz + m * gan * fade
    else:
        mezcla = voz
    escribir_wav(salida, mezcla)
