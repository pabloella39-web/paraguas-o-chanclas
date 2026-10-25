"""Narración con ElevenLabs (una toma por parte, con marcas de tiempo por palabra para los subtítulos)."""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from pathlib import Path

import requests

from .config import ASSETS
from .medios import SR

log = logging.getLogger(__name__)
API = "https://api.elevenlabs.io/v1"
RITMO = ASSETS / "ritmo.json"


def ritmo(voz: str) -> float:
    """Palabras por segundo medidas en días anteriores con esta voz."""
    try:
        return float(json.loads(RITMO.read_text())[voz])
    except Exception:  # noqa: BLE001
        return 2.3


def _guardar_ritmo(voz: str, pps: float):
    try:
        d = json.loads(RITMO.read_text()) if RITMO.exists() else {}
    except Exception:  # noqa: BLE001
        d = {}
    d[voz] = round(0.6 * pps + 0.4 * d.get(voz, pps), 3)
    RITMO.parent.mkdir(parents=True, exist_ok=True)
    RITMO.write_text(json.dumps(d, indent=1))


def duracion(ruta: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(ruta)], capture_output=True, text=True, check=True).stdout.strip())


def creditos_restantes() -> int | None:
    try:
        r = requests.get(f"{API}/user/subscription", headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"].strip()},
                         timeout=30)
        j = r.json()
        return int(j["character_limit"]) - int(j["character_count"])
    except Exception:  # noqa: BLE001
        return None


def narrar(texto: str, voz: str, destino: Path):
    """Devuelve (wav, duración, [(t0, t1, palabra)])."""
    r = requests.post(f"{API}/text-to-speech/{voz}/with-timestamps", params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"].strip(), "Content-Type": "application/json"},
                      json={"text": texto, "model_id": os.environ.get("ELEVEN_MODEL") or "eleven_v4",
                            "language_code": "es",
                            "voice_settings": {"stability": 0.38, "similarity_boost": 0.8, "style": 0.45,
                                               "use_speaker_boost": True, "speed": 0.97}}, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    mp3 = destino.with_suffix(".mp3")
    mp3.write_bytes(base64.b64decode(j["audio_base64"]))
    wav = destino.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", str(SR), "-ac", "1",
                    "-af", "loudnorm=I=-16:TP=-1.5", str(wav)], check=True)
    dur = duracion(wav)
    al = j.get("alignment") or {}
    chars, ini, fin = al.get("characters", []), al.get("character_start_times_seconds", []), \
        al.get("character_end_times_seconds", [])
    palabras, actual, t0 = [], "", None
    for c, a, b in zip(chars, ini, fin):
        if c.isspace():
            if actual:
                palabras.append((t0, b, actual))
            actual, t0 = "", None
        else:
            if not actual:
                t0 = a
            actual += c
            ultimo = b
    if actual:
        palabras.append((t0, ultimo, actual))
    if not palabras:  # sin marcas: reparto proporcional
        ws = texto.split()
        palabras = [(dur * i / len(ws), dur * (i + 1) / len(ws), w) for i, w in enumerate(ws)]
    _guardar_ritmo(voz, len(texto.split()) / max(dur, 1))
    log.info("Narración: %d palabras, %.1f s (%.2f pal/s)", len(texto.split()), dur, len(texto.split()) / dur)
    return wav, dur, palabras


def narrar_gratis(texto: str, destino: Path):
    """Respaldo sin créditos: voz neuronal gratuita (edge-tts)."""
    import asyncio

    import edge_tts
    mp3 = destino.with_suffix(".mp3")
    asyncio.run(edge_tts.Communicate(texto, "es-ES-AlvaroNeural", rate="-6%", pitch="-6Hz").save(str(mp3)))
    wav = destino.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", str(SR), "-ac", "1",
                    "-af", "loudnorm=I=-16:TP=-1.5", str(wav)], check=True)
    dur = duracion(wav)
    ws = texto.split()
    pesos = [0]
    for w in ws:
        pesos.append(pesos[-1] + len(w) + 1)
    return wav, dur, [(dur * pesos[i] / pesos[-1], dur * pesos[i + 1] / pesos[-1], w) for i, w in enumerate(ws)]
