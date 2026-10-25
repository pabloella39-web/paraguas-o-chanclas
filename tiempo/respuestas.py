"""Respuestas en vídeo a los comentarios que preguntan por el tiempo de un sitio.

Cada hora (8:00-22:00): lee los comentarios de los últimos vídeos de TikTok (vía Upload-Post), detecta con Claude
los que preguntan por un lugar ("¿y en Cuenca?", "¿qué tiempo hará mañana en Jaca?"), busca la previsión de ese
sitio (Open-Meteo), hace un vídeo de ~15 s "Respondiendo a @usuario", lo publica y contesta al comentario.

La API de TikTok no permite adjuntar la pegatina nativa de "responder con vídeo"; el vídeo la reproduce con un
bocadillo igual y menciona a la persona en la descripción (le llega la notificación).

Uso: python -m tiempo.respuestas [--publicar] [--demo]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

from . import eleven, mapa, musica, uploadpost, voz
from .config import ALTO, ANCHO, ATRIBUCION_OPENMETEO, CUENTA_TIKTOK, FPS, RAIZ, VOCES, voz_del_dia
from .estacion import estacion
from .guion import fecha_larga
from .horario import ahora
from .mapa import color_temp, fuente, icono

log = logging.getLogger("tiempo.respuestas")
ESTADO = RAIZ / "estado" / "respuestas.json"
API = uploadpost.API
MAX_EJECUCION = int(os.environ.get("RESPUESTAS_POR_HORA", "3"))
MAX_DIA = int(os.environ.get("RESPUESTAS_POR_DIA", "6"))
MAX_ELEVEN_DIA = int(os.environ.get("RESPUESTAS_ELEVEN_DIA", "6"))  # misma voz que el parte; si se acaban los créditos, voz gratuita
ACENTO = (255, 196, 45)
MIA = CUENTA_TIKTOK.lstrip("@").lower()


# ================================================================ estado
def _cargar() -> dict:
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"vistos": [], "hechas": []}


def _guardar(e: dict):
    e["vistos"] = e["vistos"][-3000:]
    e["hechas"] = e["hechas"][-300:]
    ESTADO.parent.mkdir(exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


# ================================================================ comentarios (Upload-Post)
def _get(ruta: str, **params):
    r = requests.get(f"{API}/{ruta}", headers=uploadpost._cabeceras(), params=params, timeout=40)
    if r.status_code >= 400:
        raise RuntimeError(f"Upload-Post {ruta} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _ids_en(obj) -> list[str]:
    """Busca ids de vídeo de TikTok en una respuesta de forma tolerante (los nombres de campo varían)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (str, int)) and re.fullmatch(r"\d{15,22}", str(v)) and \
                    any(p in k.lower() for p in ("id", "post")):
                out.append(str(v))
            elif isinstance(v, str):
                out += re.findall(r"/video/(\d{15,22})", v)
            else:
                out += _ids_en(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _ids_en(v)
    return list(dict.fromkeys(out))


def videos_recientes(n: int = 8) -> list[str]:
    perfil = uploadpost.perfil("tiempo")
    ids = []
    try:
        j = _get("uploadposts/media", platform="tiktok", user=perfil, limit=n)
        items = j.get("media") or j.get("data") or j.get("items") or j
        ids = _ids_en(items)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo listar los vídeos (media): %s", e)
    if not ids:
        try:
            ids = _ids_en(_get("uploadposts/history", platform="tiktok", profile_username=perfil))
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo listar el historial: %s", e)
    return ids[:n]


def comentarios_nuevos(estado: dict) -> list[dict]:
    vistos = set(estado["vistos"])
    nuevos = []
    for vid in videos_recientes():
        try:
            j = _get("uploadposts/comments", platform="tiktok", user=uploadpost.perfil("tiempo"), post_id=vid,
                     limit=50)
        except Exception as e:  # noqa: BLE001
            log.warning("Comentarios de %s: %s", vid, e)
            continue
        for c in j.get("comments", []):
            cid = str(c.get("id") or c.get("comment_id") or "")
            u = c.get("user") or {}
            nombre = (u.get("username") or u.get("display_name") or c.get("username") or "").lstrip("@")
            texto = (c.get("text") or c.get("message") or "").strip()
            if not cid or cid in vistos or not texto or nombre.lower() == MIA:
                continue
            nuevos.append({"id": cid, "video": vid, "usuario": nombre, "texto": texto[:300]})
    log.info("Comentarios nuevos: %d", len(nuevos))
    return nuevos


def responder_texto(com: dict, mensaje: str):
    r = requests.post(f"{API}/uploadposts/comments/create", headers=uploadpost._cabeceras(), json={
        "platform": "tiktok", "user": uploadpost.perfil("tiempo"), "post_id": com["video"],
        "comment_id": com["id"], "message": mensaje[:150]}, timeout=40)
    if r.status_code >= 400:
        log.warning("No se pudo contestar al comentario %s: %s", com["id"], r.text[:200])


# ================================================================ detección (Claude)
PROMPT_DETECTAR = """Estos son comentarios de TikTok en un canal del tiempo en España ("Paraguas o Chanclas").
Detecta SOLO los que preguntan (o piden) el tiempo de un lugar concreto: ciudad, pueblo, isla, comarca, playa, sierra...
(ej. "¿y en Cuenca?", "haz Jaca", "qué tiempo hará mañana en Zahara", "y en mi pueblo, Tomelloso"). Ignora el resto
(saludos, opiniones, insultos, sitios que no existen, bromas).
MUY IMPORTANTE: en el canal se pregunta a menudo "¿desde qué ciudad nos ves?", así que un comentario que SOLO dice un
sitio ("Málaga", "Desde Vigo", "matalascaña, Huelva", "te veo desde Jaén") NO es una pregunta: ignóralo. Solo cuenta si
hay intención clara de saber el tiempo de ese sitio (interrogación, "y en...", "haz...", "qué tiempo", "lloverá en...").
Para cada uno devuelve: id, lugar (nombre limpio y bien escrito), provincia o región si se deduce (o ""), pais
(código ISO de 2 letras; "ES" si no se dice otra cosa) y dia: "hoy", "mañana" o "" (si no lo dice).

Comentarios:
{comentarios}

Responde SOLO con JSON: {{"preguntas": [{{"id": "...", "lugar": "...", "provincia": "...", "pais": "ES", "dia": ""}}]}}"""


def detectar(coms: list[dict]) -> list[dict]:
    if not coms:
        return []
    from .especiales import _claude_json
    txt = "\n".join(json.dumps({"id": c["id"], "texto": c["texto"]}, ensure_ascii=False) for c in coms)
    try:
        res = _claude_json(PROMPT_DETECTAR.format(comentarios=txt)).get("preguntas", [])
    except Exception as e:  # noqa: BLE001
        log.warning("Claude no pudo clasificar (%s): detector sencillo", e)
        res = []
        for c in coms:
            m = re.search(r"(?:tiempo|y|qu[eé] tal|hace?)\s+(?:hoy|mañana)?\s*en\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñü\- ]{2,30})",
                          c["texto"])
            if m and "?" in c["texto"]:
                res.append({"id": c["id"], "lugar": m.group(1).strip(" ?!."), "provincia": "", "pais": "ES",
                            "dia": "mañana" if "mañana" in c["texto"].lower() else ""})
    por_id = {c["id"]: c for c in coms}
    return [{**por_id[p["id"]], **p} for p in res if p.get("id") in por_id and p.get("lugar")]


# ================================================================ previsión (Open-Meteo)
WMO = {0: "sol", 1: "sol", 2: "sol_nubes", 3: "nubes", 45: "niebla", 48: "niebla", 51: "lluvia", 53: "lluvia",
       55: "lluvia", 56: "lluvia", 57: "lluvia", 61: "lluvia", 63: "lluvia", 65: "lluvia", 66: "lluvia", 67: "lluvia",
       71: "nieve", 73: "nieve", 75: "nieve", 77: "nieve", 80: "chubascos", 81: "chubascos", 82: "chubascos",
       85: "nieve", 86: "nieve", 95: "tormenta", 96: "tormenta", 99: "tormenta"}


def geocodificar(lugar: str, provincia: str = "", pais: str = "ES") -> dict | None:
    r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": lugar, "count": 10, "language": "es", "format": "json"}, timeout=30)
    res = r.json().get("results") or []
    if not res:
        return None
    pais = (pais or "ES").upper()
    prov = _norm(provincia)

    def puntos(x):
        p = 0
        if x.get("country_code") == pais:
            p += 100
        if prov and prov in _norm(" ".join(str(x.get(k, "")) for k in ("admin1", "admin2", "admin3"))):
            p += 50
        if _norm(x.get("name", "")) == _norm(lugar):
            p += 20
        return p + math.log10((x.get("population") or 0) + 1)

    x = max(res, key=puntos)
    return {"nombre": x["name"], "lat": x["latitude"], "lon": x["longitude"], "pais": x.get("country_code"),
            "zona": x.get("admin2") or x.get("admin1") or x.get("country") or ""}


def prevision(sitio: dict, dia: date) -> dict:
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": sitio["lat"], "longitude": sitio["lon"], "timezone": "Europe/Madrid",
        "start_date": dia.isoformat(), "end_date": dia.isoformat(), "wind_speed_unit": "kmh",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,"
                 "weather_code,wind_gusts_10m_max",
        "hourly": "temperature_2m,precipitation_probability,weather_code"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    d, h = j["daily"], j["hourly"]

    def franja(hora):
        return {"temp": round(h["temperature_2m"][hora]), "lluvia": int(h["precipitation_probability"][hora] or 0),
                "icono": WMO.get(int(h["weather_code"][hora]), "nubes")}

    return {"tmax": round(d["temperature_2m_max"][0]), "tmin": round(d["temperature_2m_min"][0]),
            "lluvia": int(d["precipitation_probability_max"][0] or 0), "mm": d["precipitation_sum"][0] or 0,
            "racha": round(d["wind_gusts_10m_max"][0] or 0), "icono": WMO.get(int(d["weather_code"][0]), "nubes"),
            "franjas": {"MAÑANA": franja(9), "TARDE": franja(16), "NOCHE": franja(21)}}


def veredicto(p: dict) -> str:
    if p["lluvia"] >= 50 or p["mm"] >= 1 or p["icono"] in ("lluvia", "tormenta", "chubascos"):
        return "PARAGUAS"
    if p["icono"] == "nieve":
        return "BOTAS Y BUFANDA"
    if p["tmax"] >= 22:
        return "CHANCLAS"
    return "NI UNO NI OTRO: CHAQUETA"


# ================================================================ guion
PROMPT_GUION = """Eres la voz de "Paraguas o Chanclas", canal de TikTok del tiempo en España, con humor ligero (sin
palabrotas ni política). Respondes en vídeo a @{usuario}, que ha preguntado: "{pregunta}".
Previsión para {lugar} ({zona}), {cuando}: {datos}. Veredicto: {veredicto}.
Escribe la locución: entre 30 y 38 palabras (unos 13 segundos). Empieza nombrando el sitio de forma natural (no leas
el nombre de usuario), da máxima y mínima, si llueve y cuándo (mañana/tarde/noche) y termina con el veredicto
(paraguas o chanclas) con gracia. Números en cifras seguidos de "grados" o "por ciento", sin símbolos ni emojis.
Responde SOLO con JSON: {{"texto": "..."}}"""


def escribir(g: dict) -> str:
    p, s = g["prev"], g["sitio"]
    cuando = "hoy" if g["dia"] == ahora().date() else "mañana"
    try:
        from .especiales import _claude_json
        t = _claude_json(PROMPT_GUION.format(
            usuario=g["usuarios"][0], pregunta=g["textos"][0], lugar=s["nombre"], zona=s["zona"], cuando=cuando,
            datos=json.dumps(p, ensure_ascii=False), veredicto=g["veredicto"]))["texto"].strip()
        if 18 <= len(t.split()) <= 48:
            return t
    except Exception as e:  # noqa: BLE001
        log.warning("Guion de respuesta con plantilla (%s)", e)
    llueve = [k.lower() for k, f in p["franjas"].items() if f["lluvia"] >= 40]
    lluvia = (f"Ojo, que puede llover por la {' y la '.join(llueve)}." if llueve
              else "Y de lluvia, nada de nada.")
    final = {"PARAGUAS": "Así que paraguas, sin discusión.", "CHANCLAS": "Así que chanclas, y a disfrutar.",
             "BOTAS Y BUFANDA": "Así que botas y bufanda."}.get(g["veredicto"], "Ni paraguas ni chanclas: chaqueta.")
    return (f"{cuando.capitalize()} en {s['nombre']}, máxima de {p['tmax']} grados y mínima de {p['tmin']}. "
            f"{lluvia} {final}")


# ================================================================ vídeo
class Respuesta:
    def __init__(self, g: dict, palabras: list, total: float):
        self.g, self.total = g, total
        self.palabras = palabras  # [(t0, t1, palabra)]
        self.est = estacion(g["dia"])
        from .video import Particulas
        self.part = Particulas(self.est, semilla=len(g["sitio"]["nombre"]))
        self.base = self._base()
        self.ic = icono(g["prev"]["icono"], 330)

    def _base(self) -> Image.Image:
        alfa = np.linspace(0, 1, ALTO)[:, None]
        grad = (np.array(mapa.MAR_ARRIBA) * (1 - alfa) + np.array(mapa.MAR_ABAJO) * alfa).astype(np.uint8)
        self.fondo = Image.fromarray(np.repeat(grad[:, None, :], ANCHO, axis=1).reshape(ALTO, ANCHO, 3)).convert("RGBA")
        img = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))  # capa de contenido (encima de las hojas)
        d = ImageDraw.Draw(img)
        g, s = self.g, self.g["sitio"]
        # Bocadillo de "responder a comentario", como el de TikTok
        f1, f2 = fuente("SemiBold", 30), fuente("Bold", 40)
        lineas = _partir(_sin_emojis(g["textos"][0]), f2, 760)[:2]
        alto = 70 + 52 * len(lineas)
        d.rounded_rectangle([60, 150, 900, 150 + alto + 20], radius=28, fill=(255, 255, 255))
        d.polygon([(110, 150 + alto + 18), (150, 150 + alto + 18), (104, 150 + alto + 58)], fill=(255, 255, 255))
        d.text((92, 172), f"Respuesta a @{g['usuarios'][0]}", font=f1, fill=(120, 120, 128))
        for k, ln in enumerate(lineas):
            d.text((92, 214 + 52 * k), ln, font=f2, fill=(20, 20, 24))
        # Lugar y día
        y = 150 + alto + 110
        fn = fuente("Black", 118)
        while fn.getlength(s["nombre"].upper()) > 880 and fn.size > 50:
            fn = fuente("Black", fn.size - 6)
        d.text((ANCHO // 2, y), s["nombre"].upper(), font=fn, fill=(255, 255, 255), anchor="ma")
        cuando = ("HOY" if g["dia"] == ahora().date() else "MAÑANA") + " · " + fecha_larga(g["dia"]).upper()
        fz = fuente("Bold", 36)
        d.text((ANCHO // 2, y + fn.size + 22), f"{s['zona'].upper()}  ·  {cuando}" if s["zona"] else cuando,
               font=fz, fill=ACENTO, anchor="ma")
        self.y_icono = y + fn.size + 90
        # Franjas: mañana / tarde / noche
        yf = self.y_icono + 400
        for k, (nom, fr) in enumerate(g["prev"]["franjas"].items()):
            x0 = 70 + k * 320
            d.rounded_rectangle([x0, yf, x0 + 290, yf + 250], radius=26, fill=(8, 20, 45, 255),
                                outline=(255, 255, 255, 60), width=2)
            d.text((x0 + 145, yf + 22), nom, font=fuente("Bold", 30), fill=(200, 210, 230), anchor="ma")
            ic = icono(fr["icono"], 100)
            img.alpha_composite(ic, (x0 + 95, yf + 62))
            d.text((x0 + 145, yf + 160), f"{fr['temp']}°", font=fuente("Black", 46), fill=color_temp(fr["temp"]),
                   anchor="ma")
            d.text((x0 + 145, yf + 228), f"lluvia {fr['lluvia']} %", font=fuente("SemiBold", 25),
                   fill=mapa.AZUL_MIN, anchor="mm")
        self.y_veredicto = yf + 290
        d.text((ANCHO // 2, ALTO - 60), f"{CUENTA_TIKTOK}  ·  {ATRIBUCION_OPENMETEO}", font=fuente("SemiBold", 22),
               fill=(190, 200, 220), anchor="mm")
        return img

    def fotograma(self, t: float) -> Image.Image:
        img = self.fondo.copy()
        self.part.dibujar(img, t)
        img.alpha_composite(self.base)
        d = ImageDraw.Draw(img)
        p = self.g["prev"]
        # Icono grande con rebote de entrada + temperaturas
        e = _ease(min(1, max(0, (t - 0.15) / 0.6)))
        if e > 0:
            tam = max(1, int(330 * e))
            ic = self.ic.resize((tam, tam))
            img.alpha_composite(ic, (290 - tam // 2, self.y_icono + 165 - tam // 2))
            ft = fuente("Black", 150)
            d.text((640, self.y_icono + 70), f"{p['tmax']}°", font=ft, fill=color_temp(p["tmax"]), anchor="la")
            d.text((660, self.y_icono + 245), f"mín {p['tmin']}°", font=fuente("Bold", 46), fill=mapa.AZUL_MIN)
        # Veredicto al final
        tv = self.total * 0.62
        if t >= tv:
            k = _ease(min(1, (t - tv) / 0.5))
            txt = self.g["veredicto"]
            f = fuente("Black", 64)
            while f.getlength(txt) > 820 and f.size > 34:
                f = fuente("Black", f.size - 4)
            w = f.getlength(txt) + 90
            cx, cy = ANCHO // 2, self.y_veredicto + 60
            caja = Image.new("RGBA", (int(w), 120), (0, 0, 0, 0))
            dc = ImageDraw.Draw(caja)
            dc.rounded_rectangle([0, 0, w - 1, 119], radius=60, fill=ACENTO + (255,))
            dc.text((w / 2, 60), txt, font=f, fill=(15, 20, 35), anchor="mm")
            caja = caja.resize((max(1, int(w * k)), max(1, int(120 * k))))
            img.alpha_composite(caja, (cx - caja.width // 2, cy - caja.height // 2))
        # Subtítulo: la frase que se está diciendo
        actual = [w for w in self.palabras if w[0] - 0.05 <= t]
        if actual:
            idx = len(actual) - 1
            ini = idx - idx % 5
            trozo = self.palabras[ini:ini + 5]
            txt = " ".join(w[2] for w in trozo)
            f = fuente("Black", 54)
            while f.getlength(txt) > 900 and f.size > 34:
                f = fuente("Black", f.size - 4)
            y = self.y_veredicto + 175
            x = (ANCHO - f.getlength(txt)) / 2
            d.rounded_rectangle([x - 26, y - 14, x + f.getlength(txt) + 26, y + f.size + 22], radius=22,
                                fill=(0, 0, 0, 170))
            for k2, w in enumerate(trozo):
                pal = w[2] + " "
                d.text((x, y), pal, font=f, fill=ACENTO if ini + k2 == idx else (255, 255, 255))
                x += f.getlength(pal)
        return img.convert("RGB")


def _sin_emojis(txt: str) -> str:
    """La tipografía no tiene emojis (saldrían cuadraditos)."""
    limpio = "".join(c for c in txt if ord(c) < 0x2190 or 0xC0 <= ord(c) <= 0x24F)
    return re.sub(r"\s+", " ", limpio).strip() or "¿Qué tiempo hará?"


def _ease(t):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2 if t > 0 else 0


def _partir(txt, f, ancho):
    lineas, actual = [], ""
    for w in txt.split():
        prueba = (actual + " " + w).strip()
        if f.getlength(prueba) > ancho and actual:
            lineas.append(actual)
            actual = w
        else:
            actual = prueba
    if actual:
        lineas.append(actual)
    if len(lineas) > 2:
        lineas = lineas[:2]
        lineas[1] = lineas[1][:max(0, len(lineas[1]) - 2)] + "…"
    return lineas


def locutar(texto: str, trabajo: Path, usar_eleven: bool, demo: bool):
    tipo = voz_del_dia(ahora().date())
    if usar_eleven and not demo and eleven.disponible(tipo):
        try:
            wav, dur, _, pal = eleven.sintetizar([texto], tipo, trabajo, "resp")
            return wav, dur, pal[0], "elevenlabs"
        except Exception as e:  # noqa: BLE001
            log.warning("ElevenLabs falló (%s): voz gratuita", e)
    voz.elegir_voz(VOCES[tipo])
    wav = voz.sintetizar(texto, trabajo / "resp.mp3", demo, 12)
    dur = voz.duracion(wav)
    ws = texto.split()
    pesos = np.cumsum([0] + [len(w) + 1 for w in ws])
    pal = [(dur * pesos[i] / pesos[-1], dur * pesos[i + 1] / pesos[-1], w) for i, w in enumerate(ws)]
    return wav, dur, pal, "edge-tts"


def hacer_video(g: dict, salida: Path, usar_eleven: bool, demo: bool = False) -> dict:
    from .video import renderizar
    trabajo = Path(tempfile.mkdtemp())
    texto = escribir(g)
    wav, dur, pal, motor = locutar(texto, trabajo, usar_eleven, demo)
    inicio = 0.35
    total = round(max(10.0, inicio + dur + 1.4), 2)
    pal = [(a + inicio, b + inicio, w) for a, b, w in pal]
    audio = trabajo / "pista.wav"
    voz.montar_pista([(wav, inicio)], total, musica.generar(total, g["dia"]), audio)
    salida.mkdir(parents=True, exist_ok=True)
    video = salida / f"respuesta_{_norm(g['sitio']['nombre']).replace(' ', '_')}_{g['dia']}.mp4"
    renderizar(Respuesta(g, pal, total), audio, video, total)
    log.info("Respuesta lista: %s (%.1f s, %s): %s", video.name, total, motor, texto)
    return {"video": video, "texto": texto, "motor": motor, "duracion": total}


def caption(g: dict) -> str:
    s, p = g["sitio"], g["prev"]
    cuando = "hoy" if g["dia"] == ahora().date() else "mañana"
    menciones = " ".join(f"@{u}" for u in g["usuarios"][:5])
    tag = "#" + re.sub(r"[^\wñ]", "", _norm(s["nombre"]).replace(" ", "")) if s["nombre"] else ""
    return (f"Respondiendo a {menciones} 👀 ¿Paraguas o chanclas {cuando} en {s['nombre']}?\n\n"
            f"🌡️ {p['tmax']}° / {p['tmin']}° · ☔ {p['lluvia']} %\n"
            f"📍 ¿Y en tu pueblo? Pregúntame en comentarios y te respondo con un vídeo 👇\n\n"
            f"#eltiempo #tiempo {tag} #paraguasochanclas #parati")[:2200]


# ================================================================ principal
def agrupar(preguntas: list[dict], hoy_: datetime) -> list[dict]:
    grupos = {}
    for q in preguntas:
        dia = hoy_.date()
        if q.get("dia") == "mañana" or (q.get("dia") != "hoy" and hoy_.hour >= 17):
            dia = dia + timedelta(days=1)
        clave = (_norm(q["lugar"]), _norm(q.get("provincia", "")), dia)
        g = grupos.setdefault(clave, {"lugar": q["lugar"], "provincia": q.get("provincia", ""),
                                      "pais": q.get("pais", "ES"), "dia": dia, "coms": []})
        g["coms"].append(q)
    return list(grupos.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--publicar", action="store_true")
    ap.add_argument("--demo", action="store_true", help="vídeo de ejemplo sin red")
    ap.add_argument("--comprobar", action="store_true", help="solo lee vídeos y comentarios (no publica nada)")
    ap.add_argument("--salida", default=str(RAIZ / "salida_respuestas"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    salida = Path(a.salida)

    if a.demo:
        g = {"sitio": {"nombre": "Tomelloso", "zona": "Ciudad Real", "lat": 39.16, "lon": -3.02},
             "dia": ahora().date() + timedelta(days=1), "usuarios": ["laura_mancha"],
             "textos": ["¿Y en Tomelloso qué tiempo hará mañana? Que tengo boda 😅"],
             "prev": {"tmax": 19, "tmin": 6, "lluvia": 55, "mm": 2.1, "racha": 30, "icono": "chubascos",
                      "franjas": {"MAÑANA": {"temp": 9, "lluvia": 10, "icono": "sol_nubes"},
                                  "TARDE": {"temp": 18, "lluvia": 55, "icono": "chubascos"},
                                  "NOCHE": {"temp": 11, "lluvia": 30, "icono": "nubes"}}}}
        g["veredicto"] = veredicto(g["prev"])
        os.environ.pop("ANTHROPIC_API_KEY", None)
        r = hacer_video(g, salida, False, demo=True)
        print(caption(g))
        print(r)
        return

    if not uploadpost.disponible():
        print("::notice::Respuestas en vídeo: falta UPLOADPOST_API_KEY (Upload-Post lee los comentarios de TikTok)")
        return
    if a.comprobar:
        perfil = uploadpost.perfil("tiempo")
        for ruta, params in (("uploadposts/media", {"platform": "tiktok", "user": perfil, "limit": 5}),):
            try:
                j = _get(ruta, **params)
                print(f"::notice::{ruta}: claves {list(j)[:8]} · {json.dumps(j, ensure_ascii=False)[:600]}")
            except Exception as e:  # noqa: BLE001
                print(f"::error::{ruta}: {e}")
        ids = videos_recientes()
        print(f"::notice::Vídeos de TikTok encontrados: {ids}")
        coms = comentarios_nuevos({"vistos": []})
        print(f"::notice::Comentarios leídos: {len(coms)} · ejemplos: "
              f"{json.dumps([c['texto'][:60] for c in coms[:6]], ensure_ascii=False)}")
        preg = detectar(coms)
        print(f"::notice::Preguntas por un lugar: {json.dumps([(q['usuario'], q['lugar']) for q in preg], ensure_ascii=False)}")
        return
    primera = not ESTADO.exists()
    estado = _cargar()
    hoy_ = ahora()
    if primera:  # arranque: no se responde a comentarios antiguos, solo a los que lleguen desde ahora
        coms = comentarios_nuevos(estado)
        estado["vistos"] += [c["id"] for c in coms]
        _guardar(estado)
        print(f"::notice::Primera ejecución: {len(coms)} comentarios antiguos marcados como vistos")
        return
    hechas_hoy = [h for h in estado["hechas"] if h["fecha"] == hoy_.date().isoformat()]
    coms = comentarios_nuevos(estado)
    preguntas = detectar(coms)
    log.info("Preguntas por un lugar: %d de %d comentarios", len(preguntas), len(coms))
    estado["vistos"] += [c["id"] for c in coms if c["id"] not in {q["id"] for q in preguntas}]
    _guardar(estado)

    hechos = 0
    for gr in agrupar(preguntas, hoy_):
        ya = next((h for h in estado["hechas"] if h["clave"] == f"{_norm(gr['lugar'])}|{gr['dia']}"), None)
        try:
            if ya:  # ese sitio y ese día ya tienen vídeo: se contesta con el resumen
                for c in gr["coms"]:
                    if a.publicar:
                        responder_texto(c, f"¡Ya lo tienes en vídeo! 🎥 {ya['resumen']} Mira nuestros últimos vídeos 👆")
                    estado["vistos"].append(c["id"])
                continue
            if hechos >= MAX_EJECUCION or len(hechas_hoy) >= MAX_DIA:
                log.info("Límite de respuestas alcanzado; %s queda para la próxima hora", gr["lugar"])
                continue  # no se marcan como vistos: se responderán en la siguiente ejecución
            sitio = geocodificar(gr["lugar"], gr["provincia"], gr["pais"])
            if not sitio:
                log.info("Lugar no encontrado: %s", gr["lugar"])
                estado["vistos"] += [c["id"] for c in gr["coms"]]
                continue
            prev = prevision(sitio, gr["dia"])
            g = {"sitio": sitio, "dia": gr["dia"], "prev": prev, "veredicto": veredicto(prev),
                 "usuarios": list(dict.fromkeys(c["usuario"] for c in gr["coms"] if c["usuario"])) or ["ti"],
                 "textos": [c["texto"] for c in gr["coms"]]}
            con_eleven = sum(1 for h in hechas_hoy if h.get("motor") == "elevenlabs") < MAX_ELEVEN_DIA
            if con_eleven:  # reserva de créditos: primero el parte, luego las historias
                from historias.locucion import creditos_restantes
                restante = creditos_restantes()
                dias = 31 - hoy_.day + 1
                if restante is not None and restante < dias * (1100 + 3800) + 500:
                    log.info("Pocos créditos de ElevenLabs (%d): respuesta con voz gratuita", restante)
                    con_eleven = False
            r = hacer_video(g, salida, con_eleven)
            resumen = (f"{'Hoy' if gr['dia'] == hoy_.date() else 'Mañana'} en {sitio['nombre']}: "
                       f"{prev['tmax']}°/{prev['tmin']}°, {prev['lluvia']} % de lluvia → {g['veredicto'].lower()}.")
            if a.publicar:
                uploadpost.publicar_tiktok(r["video"], caption(g), "tiempo")
                for c in gr["coms"]:
                    responder_texto(c, f"¡Te respondo en vídeo! 🎥 {resumen}")
            h = {"fecha": hoy_.date().isoformat(), "clave": f"{_norm(gr['lugar'])}|{gr['dia']}",
                 "lugar": sitio["nombre"], "usuarios": g["usuarios"], "motor": r["motor"], "resumen": resumen,
                 "publicado": a.publicar}
            estado["hechas"].append(h)
            hechas_hoy.append(h)
            estado["vistos"] += [c["id"] for c in gr["coms"]]
            hechos += 1
            print(f"::notice::Respuesta en vídeo: {sitio['nombre']} para @{', @'.join(g['usuarios'])}")
        except Exception as e:  # noqa: BLE001
            log.error("Respuesta para %s falló: %s", gr["lugar"], e)
        finally:
            _guardar(estado)


if __name__ == "__main__":
    main()
