"""Locución de una sola toma: el guion entero se lee de un tirón para que suene seguido y natural.

Antes cada bloque se sintetizaba por separado y se pegaban con pausas, lo que daba un tono de "recital".
Ahora se pide a la voz el texto completo y se usan las marcas de frase que devuelve edge-tts para saber
cuándo empieza cada bloque (y así cambiar la pantalla a tiempo). Si falla, se usa el método por bloques.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import unicodedata
from pathlib import Path

from tiempo import voz

log = logging.getLogger(__name__)
TONO = os.environ.get("TONO_VOZ", "+2Hz")   # un pelín más agudo = suena más vivo


def _norm(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", t)


async def _sintetizar(texto: str, voz_edge: str, velocidad: int, ruta: Path):
    import edge_tts
    kw = {"rate": f"{velocidad:+d}%", "pitch": TONO}
    try:
        com = edge_tts.Communicate(texto, voz_edge, boundary="SentenceBoundary", **kw)
    except TypeError:  # versiones antiguas de edge-tts
        com = edge_tts.Communicate(texto, voz_edge, **kw)
    marcas = []
    with open(ruta, "wb") as f:
        async for trozo in com.stream():
            if trozo["type"] == "audio":
                f.write(trozo["data"])
            elif trozo["type"] in ("SentenceBoundary", "WordBoundary"):
                marcas.append((trozo["offset"] / 1e7, (trozo["offset"] + trozo["duration"]) / 1e7, trozo["text"]))
    return marcas


def _limites(textos: list[str], marcas, total: float):
    """Inicio y fin (s) de cada bloque dentro de la toma completa."""
    completo = _norm(" ".join(textos))
    cortes, pos = [], 0
    for t in textos:
        pos += len(_norm(t))
        cortes.append(pos)
    inicios, fines = [None] * len(textos), [None] * len(textos)
    cursor = 0
    for t0, t1, txt in marcas:
        n = _norm(txt)
        if not n:
            continue
        i = completo.find(n, cursor)
        if i < 0:
            continue
        cursor = i + len(n)
        bloque = next(k for k, c in enumerate(cortes) if i < c or k == len(cortes) - 1)
        if inicios[bloque] is None:
            inicios[bloque] = t0
        fines[bloque] = t1
    if any(x is None for x in inicios):
        # Sin marcas útiles: reparto proporcional a la longitud del texto
        log.info("Sin marcas de frase completas; reparto proporcional")
        lon = [len(_norm(t)) for t in textos]
        acc, inicios, fines = 0.0, [], []
        for L in lon:
            inicios.append(total * acc / sum(lon))
            acc += L
            fines.append(total * acc / sum(lon))
    for k in range(len(textos) - 1):  # cada bloque dura hasta que empieza el siguiente
        fines[k] = max(fines[k], inicios[k + 1] - 0.05)
    return list(zip(inicios, fines))


def toma_completa(guion: dict, bloques: list[str], voz_edge: str, velocidad: int, trabajo: Path, etiqueta: str):
    """Devuelve (wav, duración, [(inicio, fin)] por bloque)."""
    textos = [guion["segmentos"][s].strip() for s in bloques]
    mp3 = trabajo / f"toma_{etiqueta}.mp3"
    marcas = asyncio.run(_sintetizar(" ".join(textos), voz_edge, velocidad, mp3))
    if not mp3.exists() or mp3.stat().st_size < 1000:
        raise RuntimeError("edge-tts no devolvió audio")
    wav = mp3.with_suffix(".wav")
    voz._ffmpeg("-i", str(mp3), "-ar", str(voz.SR), "-ac", "1", str(wav))
    dur = voz.duracion(wav)
    return wav, dur, _limites(textos, marcas, dur)
