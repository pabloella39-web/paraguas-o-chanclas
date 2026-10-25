"""Música de fondo original generada por código (sin derechos de autor).

Si existe assets/musica.mp3 (o .wav) se usa ese archivo en su lugar: pon ahí una pista libre de derechos.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .config import ASSETS
from .voz import SR, leer_wav

BPM = 100
# Progresión alegre y suave: C - Am - F - G (frecuencias en Hz)
ACORDES = [
    [261.63, 329.63, 392.00, 493.88],
    [220.00, 261.63, 329.63, 392.00],
    [174.61, 220.00, 261.63, 329.63],
    [196.00, 246.94, 293.66, 392.00],
]
BAJOS = [65.41, 55.00, 87.31, 98.00]


def _nota(f, dur, ataque=0.01, caida=3.0, armonicos=(1, 0.35, 0.15)):
    t = np.arange(int(dur * SR)) / SR
    onda = sum(a * np.sin(2 * np.pi * f * (i + 1) * t) for i, a in enumerate(armonicos))
    env = np.minimum(1, t / ataque) * np.exp(-caida * t)
    return onda * env


# Música de cada estación generada con ElevenLabs Music (uso comercial incluido en el plan Starter).
# Se guarda en assets/musica/<estación>/ y se va rotando; si hay menos de PISTAS_POR_ESTACION, cada día se compone
# una nueva (≈75 s de los 40 min de música al mes del plan), así la biblioteca crece sola al cambiar de estación.
PISTAS_POR_ESTACION = 5
PROMPTS = {
    "otono": "Warm, cozy autumn instrumental for a light-hearted daily weather show: soft acoustic guitar, "
             "gentle piano, light percussion, upbeat but relaxed, 100 bpm, no vocals, seamless background loop",
    "invierno": "Bright cozy winter instrumental for a cheerful daily weather show: glockenspiel, pizzicato strings, "
                "soft piano, light sleigh-bell shaker, upbeat, 100 bpm, no vocals, background loop",
    "primavera": "Fresh spring instrumental for a cheerful daily weather show: ukulele, whistling-style synth, light "
                 "claps, marimba, happy and bouncy, 105 bpm, no vocals, background loop",
    "verano": "Sunny summer instrumental for a fun daily weather show: tropical house, steel drums, light guitar, "
              "relaxed beach vibe, 102 bpm, no vocals, background loop",
}


def _biblioteca(hoy) -> np.ndarray | None:
    import logging
    import os

    import requests

    from .estacion import estacion
    log = logging.getLogger(__name__)
    est = estacion(hoy)
    carpeta = ASSETS / "musica" / est
    carpeta.mkdir(parents=True, exist_ok=True)
    pistas = sorted(carpeta.glob("*.mp3"))
    clave = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if len(pistas) < PISTAS_POR_ESTACION and clave:
        try:
            r = requests.post("https://api.elevenlabs.io/v1/music", params={"output_format": "mp3_44100_128"},
                              headers={"xi-api-key": clave, "Content-Type": "application/json"},
                              json={"prompt": PROMPTS[est], "music_length_ms": 75000, "force_instrumental": True},
                              timeout=300)
            if r.status_code == 200 and len(r.content) > 50_000:
                nueva = carpeta / f"{est}_{hoy.isoformat()}.mp3"
                nueva.write_bytes(r.content)
                log.info("Nueva pista de música de %s compuesta con ElevenLabs (%s)", est, nueva.name)
                pistas = sorted(carpeta.glob("*.mp3"))
            else:
                log.warning("ElevenLabs Music HTTP %s: %s", r.status_code, r.text[:200])
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo componer música: %s", e)
    if not pistas:
        return None
    pista = pistas[hoy.toordinal() % len(pistas)]
    tmp = Path(f"/tmp/musica_{pista.stem}.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(pista), "-ar", str(SR), "-ac", "1",
                    "-af", "loudnorm=I=-20:TP=-2", str(tmp)], check=True)
    log.info("Música: %s", pista.name)
    return leer_wav(tmp) * 0.9


def generar(segundos: float, hoy=None) -> np.ndarray:
    """hoy: si se pasa (canal del tiempo), se usa la biblioteca de música de la estación."""
    if hoy is not None:
        musica = _biblioteca(hoy)
        if musica is not None:
            return musica
    propia = next((p for p in (ASSETS / "musica.mp3", ASSETS / "musica.wav") if p.exists()), None)
    if propia:
        tmp = Path("/tmp/musica_propia.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(propia), "-ar", str(SR), "-ac", "1", str(tmp)],
                       check=True)
        return leer_wav(tmp) * 0.8

    n = int(segundos * SR)
    out = np.zeros(n + SR * 4, dtype=np.float32)
    beat = 60 / BPM
    compas = beat * 4
    t, i = 0.0, 0
    while t < segundos:
        acorde = ACORDES[i % 4]
        k = int(t * SR)
        # Colchón (pad)
        pad = sum(_nota(f, compas + 1, ataque=0.4, caida=0.5, armonicos=(1, 0.2)) for f in acorde) * 0.10
        out[k:k + len(pad)] += pad[: len(out) - k]
        # Bajo en cada pulso 1 y 3
        for b in (0, 2):
            nb = _nota(BAJOS[i % 4], beat * 1.5, caida=2.5, armonicos=(1, 0.5)) * 0.35
            kb = k + int(b * beat * SR)
            out[kb:kb + len(nb)] += nb[: len(out) - kb]
        # Arpegio en corcheas
        for j in range(8):
            f = acorde[[0, 2, 1, 3, 2, 1, 3, 2][j]] * 2
            na = _nota(f, beat, caida=6, armonicos=(1, 0.25)) * 0.07
            ka = k + int(j * beat / 2 * SR)
            out[ka:ka + len(na)] += na[: len(out) - ka]
        # Percusión suave: "shaker" con ruido filtrado en contratiempos
        rng = np.random.default_rng(i)
        for j in range(4):
            ruido = rng.standard_normal(int(0.05 * SR)) * np.exp(-np.linspace(0, 8, int(0.05 * SR))) * 0.04
            ks = k + int((j + 0.5) * beat * SR)
            out[ks:ks + len(ruido)] += ruido[: len(out) - ks]
        t += compas
        i += 1
    out = out[:n]
    return out / (np.max(np.abs(out)) + 1e-9) * 0.9
