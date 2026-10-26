"""Voz de ElevenLabs: el guion completo en UNA sola toma, con marcas de tiempo por carácter.

- Las marcas permiten cambiar de bloque en pantalla a tiempo y resaltar cada palabra en los subtítulos.
- Los números se pasan a palabras antes de enviarlos ("21 grados" → "veintiún grados") para que la
  pronunciación sea siempre correcta; en pantalla se siguen viendo en cifras.
- Para no gastar créditos de más, la longitud del guion se calcula ANTES de sintetizar (con el ritmo medido en
  días anteriores) y el ajuste fino de duración se hace con atempo, sin volver a llamar a la API.

Variables: ELEVENLABS_API_KEY (secreto), ELEVEN_VOZ_MASCULINA y ELEVEN_VOZ_FEMENINA (ids de voz),
ELEVEN_MODEL (por defecto eleven_v4, el más natural; el plan Starter incluye 75.000 caracteres/mes de v4).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path

import requests

from . import voz
from .config import RAIZ

log = logging.getLogger(__name__)
API = "https://api.elevenlabs.io/v1"
RITMO = RAIZ / "estado" / "eleven_ritmo.json"
CPS_INICIAL = 14.5   # caracteres por segundo hablados (se corrige solo con cada vídeo)


# Voces elegidas en la biblioteca de ElevenLabs (español de España), añadidas a "My Voices" de la cuenta
VOZ_MASCULINA = "Pc51tQpUBlUP7gybDfkb"   # Enrique Soler
VOZ_FEMENINA = "BXtvkfRgOYGPQKVRgufE"    # Maite Jiménez (Anabel tenía eco en la grabación: 19 % de cola frente a 5 %)


def modelo() -> str:
    return os.environ.get("ELEVEN_MODEL") or "eleven_v4"


def voz_id(tipo: str) -> str | None:
    fem = os.environ.get("ELEVEN_VOZ_FEMENINA", "").strip()
    if fem in ("7sPWPWuzGi4J8JnaQcQw",):  # Anabel: descartada por el eco de su grabación
        fem = ""
    ids = {"masculina": os.environ.get("ELEVEN_VOZ_MASCULINA", "").strip() or VOZ_MASCULINA,
           "femenina": fem or VOZ_FEMENINA}
    return ids.get(tipo) or ids["femenina"] or ids["masculina"] or None


def disponible(tipo: str) -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY", "").strip() and voz_id(tipo))


# ---------------------------------------------------------------- números a palabras
_U = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
      "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
      "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho",
      "veintinueve"]
_D = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
_C = {1: "ciento", 2: "doscientos", 3: "trescientos", 4: "cuatrocientos", 5: "quinientos", 6: "seiscientos",
      7: "setecientos", 8: "ochocientos", 9: "novecientos"}
MASCULINOS = re.compile(r"^(grado|kil[oó]metro|litro|mil[ií]metro|d[ií]a|a[ñn]o|punto|metro|cent[ií]metro)", re.I)


def _cientos(n: int) -> str:
    if n < 30:
        return _U[n]
    if n < 100:
        d, u = divmod(n, 10)
        return _D[d] + ("" if u == 0 else " y " + _U[u])
    if n == 100:
        return "cien"
    c, r = divmod(n, 100)
    return _C[c] + ("" if r == 0 else " " + _cientos(r))


def numero(n: int) -> str:
    if n < 0:
        return "menos " + numero(-n)
    if n < 1000:
        return _cientos(n)
    if n < 1_000_000:
        m, r = divmod(n, 1000)
        miles = "mil" if m == 1 else _apocope(_cientos(m)) + " mil"
        return miles + ("" if r == 0 else " " + _cientos(r))
    return str(n)


def _apocope(txt: str) -> str:
    """'uno' → 'un' delante de un sustantivo masculino ('veintiún grados', 'treinta y un grados')."""
    if txt.endswith("veintiuno"):
        return txt[:-len("veintiuno")] + "veintiún"
    if txt.endswith("uno"):
        return txt[:-3] + "un"
    return txt


def hablar_token(token: str, siguiente: str = "") -> str:
    m = re.match(r"^([¿¡(\"«]*)(-?\d[\d.,]*\d|-?\d)([%º°]?)([.,;:!?)\"»]*)$", token)
    if not m:
        return token
    pre, num, simb, post = m.groups()
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", num):          # 1.200 → miles
        texto = numero(int(num.replace(".", "")))
    elif "," in num:                                      # 2,5 → dos coma cinco
        ent, dec = num.split(",", 1)
        texto = numero(int(ent)) + " coma " + " ".join(_U[int(c)] for c in dec) if len(dec) > 1 and dec.startswith("0") \
            else numero(int(ent)) + " coma " + numero(int(dec))
    else:
        texto = numero(int(num.replace(".", "")))
    if simb == "%":
        texto += " por ciento"
    elif simb in ("º", "°"):
        texto = _apocope(texto) + " grados"
    elif MASCULINOS.match(siguiente or ""):
        texto = _apocope(texto)
    return pre + texto + post


# ---------------------------------------------------------------- síntesis
def _texto_hablado(bloques: list[str]):
    """Devuelve el texto para la API y, por cada palabra original, (bloque, palabra, inicio, fin) en ese texto."""
    piezas, tokens, pos = [], [], 0
    for b, texto in enumerate(bloques):
        palabras = texto.split()
        for k, w in enumerate(palabras):
            sig = palabras[k + 1] if k + 1 < len(palabras) else ""
            h = hablar_token(w, re.sub(r"^\W+", "", sig))
            if piezas:
                piezas.append(" ")
                pos += 1
            tokens.append((b, w, pos, pos + len(h)))
            piezas.append(h)
            pos += len(h)
    return "".join(piezas), tokens


def longitud_hablada(bloques: list[str]) -> int:
    return len(_texto_hablado(bloques)[0])


def ritmo(voz_id_: str) -> float:
    try:
        return float(json.loads(RITMO.read_text())[voz_id_])
    except Exception:  # noqa: BLE001
        return CPS_INICIAL


def _guardar_ritmo(voz_id_: str, cps: float):
    try:
        datos = json.loads(RITMO.read_text()) if RITMO.exists() else {}
    except Exception:  # noqa: BLE001
        datos = {}
    previo = datos.get(voz_id_, cps)
    datos[voz_id_] = round(0.6 * cps + 0.4 * previo, 3)
    RITMO.parent.mkdir(exist_ok=True)
    RITMO.write_text(json.dumps(datos, indent=1))


def sintetizar(bloques: list[str], tipo: str, trabajo: Path, etiqueta: str):
    """Una llamada a la API. Devuelve (wav, duración, [(ini, fin)] por bloque, [[(t0, t1, palabra)] por bloque])."""
    vid = voz_id(tipo)
    texto, tokens = _texto_hablado(bloques)
    cuerpo = {"text": texto, "model_id": modelo(),
              "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25,
                                 "use_speaker_boost": True, "speed": 1.05}}
    if "multilingual_v2" not in modelo():
        cuerpo["language_code"] = "es"
    r = requests.post(f"{API}/text-to-speech/{vid}/with-timestamps", params={"output_format": "mp3_44100_128"},
                      headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"].strip(),
                               "Content-Type": "application/json"}, json=cuerpo, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}")
    j = r.json()
    mp3 = trabajo / f"eleven_{etiqueta}.mp3"
    mp3.write_bytes(base64.b64decode(j["audio_base64"]))
    wav = mp3.with_suffix(".wav")
    voz._ffmpeg("-i", str(mp3), "-ar", str(voz.SR), "-ac", "1", str(wav))
    dur = voz.duracion(wav)
    al = j.get("alignment") or j.get("normalized_alignment") or {}
    ini_c, fin_c = al.get("character_start_times_seconds", []), al.get("character_end_times_seconds", [])
    log.info("ElevenLabs (%s, %s): %d caracteres, %.1f s", vid, modelo(), len(texto), dur)
    _guardar_ritmo(vid, len(texto) / max(dur, 1))

    palabras = [[] for _ in bloques]
    if len(ini_c) >= len(texto) - 2:
        for b, w, a, z in tokens:
            a2, z2 = min(a, len(ini_c) - 1), min(max(z - 1, a), len(fin_c) - 1)
            palabras[b].append((ini_c[a2], fin_c[z2], w))
    else:  # sin marcas fiables: reparto proporcional al texto
        log.warning("ElevenLabs sin marcas de tiempo completas (%d de %d)", len(ini_c), len(texto))
        for b, w, a, z in tokens:
            palabras[b].append((dur * a / len(texto), dur * z / len(texto), w))
    limites = [(p[0][0], p[-1][1]) if p else (0.0, 0.0) for p in palabras]
    for k in range(len(limites) - 1):  # cada bloque dura hasta que empieza el siguiente
        limites[k] = (limites[k][0], max(limites[k][1], limites[k + 1][0] - 0.05))
    return wav, dur, limites, palabras
