"""Vídeos especiales de Paraguas o Chanclas.

- Fin de semana (viernes por la tarde): ¿playa, monte o sofá? Previsión del sábado y del domingo.
- Avisos de AEMET: cuando hay avisos naranjas o rojos (DANA, temporal, calor extremo…), un vídeo especial.

  python -m tiempo.especiales finde [--publicar] [--esperar] [--demo] [--fecha AAAA-MM-DD]
  python -m tiempo.especiales avisos [--publicar] [--demo]

Llegan como borrador a TikTok (igual que el parte) y se suben a YouTube Shorts.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import logging
import math
import os
import random
import re
import tarfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from PIL import ImageDraw

from . import eleven, musica, voz
from . import guion as g
from .config import (ANCHO, DURACION_MAX, DURACION_MIN, DURACION_OBJETIVO, MODELO_CLAUDE, RAIZ, VISTA_GENERAL,
                     VOCES, voz_del_dia)
from .horario import ahora
from .mapa import fuente
from .video import MAPA_Y0, Compositor, renderizar

log = logging.getLogger("tiempo.especiales")
HISTORIAL = RAIZ / "historial_especiales"
ACENTO = (255, 196, 45)
MESES_CORTOS = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


# ================================================================ voz (común)
def locutar(escribir, trabajo: Path, tipo_voz: str, demo: bool):
    """escribir(factor, plantilla) -> guion con 'segmentos' y 'orden'. Devuelve (guion, plan, total, trozos, motor)."""
    from .main import COLA_ELEVEN, INICIO, VEL_MAX, VEL_MIN, _habla_objetivo, plan_eleven, planificar
    if not demo and eleven.disponible(tipo_voz):
        try:
            objetivo = DURACION_OBJETIVO - INICIO - COLA_ELEVEN - 0.2
            meta = eleven.ritmo(eleven.voz_id(tipo_voz)) * objetivo
            factor = 1.0
            for _ in range(3):
                guion = escribir(factor, False)
                bloques = [s for s in guion["orden"] if guion["segmentos"].get(s, "").strip()]
                largo = eleven.longitud_hablada([guion["segmentos"][s] for s in bloques])
                if abs(largo - meta) / meta <= 0.08 or guion.get("origen") != "claude":
                    break
                factor *= meta / largo
            wav, dur, lim, pal = eleven.sintetizar([guion["segmentos"][s] for s in bloques], tipo_voz, trabajo, "esp")
            plan, total, wav = plan_eleven(bloques, wav, dur, lim, pal)
            return guion, plan, total, [(wav, INICIO)], f"elevenlabs ({eleven.modelo()})"
        except Exception as e:  # noqa: BLE001
            log.warning("ElevenLabs no disponible (%s): voz gratuita", e)
    factor, mejor = 1.0, None
    for intento in range(3):
        guion = escribir(factor, demo)
        bloques = [s for s in guion["orden"] if guion["segmentos"].get(s, "").strip()]
        objetivo = _habla_objetivo(len(bloques))
        vel = voz.velocidad_base()
        for ajuste in range(3):
            wavs = [voz.sintetizar(guion["segmentos"][s], trabajo / f"e{intento}{ajuste}_{s}.mp3", demo, vel)
                    for s in bloques]
            durs = [voz.duracion(w) for w in wavs]
            mejor = (guion, bloques, wavs, durs)
            habla = sum(durs)
            nueva = min(max(round((1 + vel / 100) * habla / objetivo * 100 - 100), VEL_MIN), VEL_MAX)
            if abs(habla - objetivo) <= 1.0 or nueva == vel:
                break
            vel = nueva
        if abs(habla - objetivo) <= 2.5 or guion.get("origen") != "claude":
            break
        factor *= objetivo / habla
    guion, bloques, wavs, durs = mejor
    try:
        plan, total = planificar(bloques, wavs, durs)
    except RuntimeError as e:
        log.warning("%s → plantilla", e)
        guion = escribir(0.85, True)
        bloques = [s for s in guion["orden"] if guion["segmentos"].get(s, "").strip()]
        wavs = [voz.sintetizar(guion["segmentos"][s], trabajo / f"p_{s}.mp3", demo, VEL_MAX) for s in bloques]
        plan, total = planificar(bloques, wavs, [voz.duracion(w) for w in wavs])
    return guion, plan, total, [(p["wav"], p["inicio"]) for p in plan], "edge-tts"


def _claude_json(prompt: str) -> dict:
    clave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not clave:
        raise RuntimeError("Sin ANTHROPIC_API_KEY")
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": os.environ.get("CLAUDE_MODEL", MODELO_CLAUDE), "max_tokens": 12000,
                            "messages": [{"role": "user", "content": prompt}]}, timeout=240)
    r.raise_for_status()
    texto = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    return json.loads(re.search(r"\{.*\}", texto, re.S).group(0))


def _producir(nombre: str, guion, plan, total, trozos, comp_kwargs: dict, prev, extremos, cabecera: str,
              salida: Path, trabajo: Path) -> Path:
    for p in plan:
        p["texto"] = guion["segmentos"][p["seg"]]
    audio = trabajo / "pista.wav"
    voz.montar_pista(trozos, total, musica.generar(total, ahora().date()), audio)
    comp = Compositor(prev, plan, total, cabecera, extremos, guion.get("titular", ""), fecha=ahora().date(),
                      **comp_kwargs)
    video = salida / f"{nombre}.mp4"
    log.info("Renderizando %.2f s…", total)
    renderizar(comp, audio, video, total)
    real = voz.duracion(video)
    if not DURACION_MIN <= real <= DURACION_MAX:
        raise RuntimeError(f"El vídeo dura {real:.2f} s")
    return video


# ================================================================ fin de semana
PROMPT_FINDE = """Eres el guionista de "Paraguas o Chanclas", un canal de TikTok sobre el tiempo en España con humor
ligero (sin palabrotas, sin política). Es viernes por la tarde: toca el vídeo del FIN DE SEMANA. Usa SOLO estos datos
(no inventes temperaturas, lluvias ni avisos). Lo lee {presenta} con voz sintética.

Sábado {sab} y domingo {dom}. Datos por ciudad (grados, lluvia = probabilidad en %):
SÁBADO: {datos_sab}
DOMINGO: {datos_dom}

RETENCIÓN: la intro NO saluda: arranca con lo más llamativo del finde (¿se estropea el domingo?, ¿último finde
de playa?, ¿frío de verdad?) y promete que al final dirás dónde está el mejor plan del fin de semana.
Habla de tú, frases que fluyan, nada de listas ni dos puntos, números en cifras con "grados" o "por ciento".
Interpela a la gente de alguna ciudad. Ciudades por su nombre (S.C. Tenerife = Santa Cruz de Tenerife).

Bloques (palabras aproximadas por bloque: {palabras}; total ≈ {total}):
- intro: gancho + promesa del final.
- sabado: cómo será el sábado en España (lo destacado, agrupando zonas).
- domingo: cómo cambia (o no) el domingo.
- general: la recompensa: dónde está el mejor plan del finde (sol y buena temperatura) y dónde mejor sofá y manta,
  con sus cifras.
- cierre: pregunta para comentarios ("¿qué plan tienes este finde?", "¿playa, monte o sofá?") y que sigan la cuenta
  para tener el tiempo de cada día. NUNCA digas horas de publicación.

"titular": 2 a 5 palabras en MAYÚSCULAS, máx. 26 caracteres, sin emojis (ej. "FINDE PASADO POR AGUA").
"caption": una frase gancho (máx. 90 caracteres), con 1 o 2 emojis, sin hashtags.

Responde SOLO con JSON: {{"segmentos": {{"intro": "...", "sabado": "...", "domingo": "...", "general": "...",
"cierre": "..."}}, "titular": "...", "caption": "..."}}"""
PALABRAS_FINDE = {"intro": 22, "sabado": 42, "domingo": 42, "general": 36, "cierre": 22}


def _resumen(prev):
    return [{k: c[k] for k in ("nombre", "tmax", "tmin", "lluvia", "icono")} for c in prev]


def _mejor_plan(prev_s, prev_d):
    def nota(c):
        return c["tmax"] - c["lluvia"] / 8 - (8 if c["icono"] in ("lluvia", "tormenta", "nieve") else 0)
    pares = [(cs, cd) for cs in prev_s for cd in prev_d if cs["nombre"] == cd["nombre"]]
    mejor = max(pares, key=lambda p: nota(p[0]) + nota(p[1]))
    peor = min(pares, key=lambda p: nota(p[0]) + nota(p[1]))
    return mejor, peor


def guion_finde(prev_s, prev_d, sab: date, dom: date, factor: float, presenta: str, plantilla: bool) -> dict:
    orden = ["intro", "sabado", "domingo", "general", "cierre"]
    palabras = {k: max(8, round(v * factor)) for k, v in PALABRAS_FINDE.items()}
    if not plantilla:
        try:
            gg = _claude_json(PROMPT_FINDE.format(presenta=presenta, sab=g.fecha_larga(sab), dom=g.fecha_larga(dom),
                                                  datos_sab=json.dumps(_resumen(prev_s), ensure_ascii=False),
                                                  datos_dom=json.dumps(_resumen(prev_d), ensure_ascii=False),
                                                  palabras=json.dumps(palabras), total=sum(palabras.values())))
            if all(gg["segmentos"].get(s) for s in orden):
                gg.update(origen="claude", orden=orden)
                return gg
        except Exception as e:  # noqa: BLE001
            log.warning("Guion del finde con Claude falló: %s", e)
    (ms, md), (ps, pd) = _mejor_plan(prev_s, prev_d)
    lluvia_s = [g._nombre(c) for c in prev_s if c["lluvia"] >= 50]
    lluvia_d = [g._nombre(c) for c in prev_d if c["lluvia"] >= 50]
    seg = {
        "intro": ("¿Finde de terraza o de manta? Te lo cuento en un minuto, y al final, dónde está el mejor plan "
                  "de España."),
        "sabado": ("El sábado, " + (f"ojo a la lluvia en {' y '.join(lluvia_s[:2])}, " if lluvia_s else
                                    "pocas nubes que echarse a la cara, ")
                   + f"con máximas de hasta {max(c['tmax'] for c in prev_s)} grados."),
        "domingo": ("Y el domingo, " + (f"lluvia en {' y '.join(lluvia_d[:2])}" if lluvia_d else "tranquilo")
                    + f", con máximas de hasta {max(c['tmax'] for c in prev_d)} grados."),
        "general": (f"Lo prometido: el mejor plan, {g._nombre(ms)}, con {ms['tmax']} grados el sábado y "
                    f"{md['tmax']} el domingo. Y para sofá y manta, {g._nombre(ps)}."),
        "cierre": "¿Y tú, qué plan tienes este finde? Cuéntamelo en comentarios y sígueme para el tiempo de cada día.",
    }
    return {"segmentos": seg, "orden": orden, "titular": "¿QUÉ TIEMPO HARÁ EL FINDE?",
            "caption": "¿Playa, monte o sofá? El tiempo del finde 👇", "origen": "plantilla"}


def caption_finde(prev_s, prev_d, sab, dom, gancho) -> str:
    from .descripcion import _estacion
    (ms, md), _ = _mejor_plan(prev_s, prev_d)
    calor = max(prev_s + prev_d, key=lambda c: c["tmax"])
    lineas = [f"El tiempo del fin de semana en España, {sab.day}-{dom.day} de {g.MESES[dom.month - 1]} 🇪🇸",
              f"☀️ Mejor plan: {ms['nombre']} ({ms['tmax']}° / {md['tmax']}°)",
              f"🔥 Máxima del finde: {calor['tmax']}° en {calor['nombre']}"]
    llueve = sorted({c["nombre"] for c in prev_s + prev_d if c["lluvia"] >= 50})
    if llueve:
        lineas.append("🌧️ Lluvia en " + ", ".join(llueve[:3]))
    tags = ["#finde", "#findesemana", "#eltiempo", "#tiempo", "#españa", "#AEMET", "#parati", "#paraguasochanclas",
            _estacion(sab)]
    return (f"{(gancho or '¿Playa, monte o sofá? 👇').strip()}\n\n" + "\n".join(lineas) + "\n\n" + " ".join(tags))[:2200]


def fin_de_semana(viernes: date, salida: Path, demo: bool = False) -> dict:
    from .fuentes import obtener_previsiones, previsiones_demo
    sab, dom = viernes + timedelta(days=1), viernes + timedelta(days=2)
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "trabajo"
    trabajo.mkdir(exist_ok=True)
    if demo:
        prev_s, _ = previsiones_demo()
        prev_d = copy.deepcopy(prev_s)
        rnd = random.Random(3)
        for c in prev_d:
            c["tmax"] += rnd.choice([-3, -2, 0, 1])
            c["lluvia"] = min(100, c["lluvia"] + rnd.choice([0, 20, 40]))
    else:
        clave_google = os.environ.pop("GOOGLE_WEATHER_API_KEY", None)  # Google solo da el día de hoy
        try:
            prev_s, _ = obtener_previsiones(sab)
            prev_d, _ = obtener_previsiones(dom)
        finally:
            if clave_google:
                os.environ["GOOGLE_WEATHER_API_KEY"] = clave_google
    tipo_voz = os.environ.get("VOZ_TIPO") or voz_del_dia(viernes)
    voz.elegir_voz(VOCES[tipo_voz])
    guion, plan, total, trozos, motor = locutar(
        lambda f, pl: guion_finde(prev_s, prev_d, sab, dom, f, VOCES[tipo_voz]["presenta"], pl),
        trabajo, tipo_voz, demo)
    todos = prev_s + prev_d
    extremos = {"calor": max(todos, key=lambda c: c["tmax"]), "frio": min(todos, key=lambda c: c["tmin"])}
    rango = f"{sab.day} {MESES_CORTOS[sab.month - 1]} · {dom.day} {MESES_CORTOS[dom.month - 1]}"
    (ms, _), _ = _mejor_plan(prev_s, prev_d)
    kwargs = {
        "datos_seg": {"sabado": prev_s, "domingo": prev_d, "intro": []},
        "pills": {"sabado": f"SÁBADO {sab.day}", "domingo": f"DOMINGO {dom.day}", "general": "EL MEJOR PLAN DEL FINDE"},
        "portada_txt": ("EL TIEMPO DEL FINDE", "FIN DE SEMANA", rango,
                        ((f"MEJOR PLAN: {ms['nombre'].upper()} {ms['tmax']}°", (255, 196, 45)),
                         (f"MÁX {extremos['calor']['tmax']}° · MÍN {extremos['frio']['tmin']}°", (140, 205, 255)))),
    }
    video = _producir(f"finde_{sab.isoformat()}", guion, plan, total, trozos, kwargs, prev_s, extremos,
                      f"FIN DE SEMANA {rango}", salida, trabajo)
    caption = caption_finde(prev_s, prev_d, sab, dom, guion.get("caption") if guion.get("origen") == "claude" else None)
    return {"tipo": "finde", "fecha": viernes.isoformat(), "video": str(video), "caption": caption,
            "titular": guion.get("titular"), "motor_voz": motor, "origen_guion": guion.get("origen"),
            "duracion": round(voz.duracion(video), 2), "guion": guion["segmentos"]}


# ================================================================ avisos de AEMET
NS = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}
NIVELES = {"amarillo": 1, "naranja": 2, "rojo": 3}
COLOR_NIVEL = {"naranja": (255, 140, 0), "rojo": (230, 30, 40)}


def descargar_avisos(clave: str) -> list[dict]:
    from .fuentes import AEMET_BASE
    r = requests.get(f"{AEMET_BASE}/avisos_cap/ultimoelaborado/area/esp", headers={"api_key": clave}, timeout=30)
    meta = r.json()
    if meta.get("estado") != 200:
        raise RuntimeError(f"AEMET avisos: {meta.get('descripcion')}")
    contenido = requests.get(meta["datos"], timeout=60).content
    avisos = []
    with tarfile.open(fileobj=io.BytesIO(contenido)) as tar:
        for m in tar.getmembers():
            if not m.isfile() or not m.name.endswith(".xml"):
                continue
            try:
                raiz = ET.fromstring(tar.extractfile(m).read())
            except ET.ParseError:
                continue
            avisos.extend(_parsear_cap(raiz))
    return avisos


def _parsear_cap(raiz) -> list[dict]:
    out = []
    for info in raiz.findall("c:info", NS):
        if info.findtext("c:language", namespaces=NS) != "es-ES":
            continue
        params = {p.findtext("c:valueName", namespaces=NS): p.findtext("c:value", namespaces=NS)
                  for p in info.findall("c:parameter", NS)}
        nivel = (params.get("AEMET-Meteoalerta nivel") or "").lower()
        if nivel not in NIVELES:
            continue
        evento = info.findtext("c:event", namespaces=NS) or ""
        m = re.match(r"Aviso de (.+?) de nivel", evento)
        for area in info.findall("c:area", NS):
            poligono = []
            for txt in (area.findtext("c:polygon", namespaces=NS) or "").split():
                try:
                    la, lo = txt.split(",")
                    poligono.append((float(lo), float(la)))
                except ValueError:
                    pass
            out.append({"nivel": nivel, "fenomeno": m.group(1) if m else evento,
                        "zona": area.findtext("c:areaDesc", namespaces=NS) or "",
                        "inicio": info.findtext("c:onset", namespaces=NS), "fin": info.findtext("c:expires", namespaces=NS),
                        "descripcion": (info.findtext("c:description", namespaces=NS) or "").strip(),
                        "instruccion": (info.findtext("c:instruction", namespaces=NS) or "").strip(),
                        "probabilidad": params.get("AEMET-Meteoalerta probabilidad"), "poligono": poligono})
    return out


def avisos_relevantes(avisos: list[dict], momento: datetime, horas: int = 36) -> list[dict]:
    """Naranjas y rojos vigentes o que empiezan en las próximas `horas`."""
    out = []
    for a in avisos:
        if NIVELES[a["nivel"]] < 2:
            continue
        try:
            ini, fin = datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"])
        except (TypeError, ValueError):
            continue
        if fin > momento and ini < momento + timedelta(hours=horas):
            out.append(a)
    return out


def agrupar(avisos: list[dict]) -> list[dict]:
    grupos = {}
    for a in avisos:
        k = (a["fenomeno"], a["nivel"])
        gr = grupos.setdefault(k, {"fenomeno": a["fenomeno"], "nivel": a["nivel"], "zonas": [], "inicio": a["inicio"],
                                   "fin": a["fin"], "descripcion": a["descripcion"], "instruccion": a["instruccion"],
                                   "poligonos": []})
        if a["zona"] not in gr["zonas"]:
            gr["zonas"].append(a["zona"])
        gr["inicio"], gr["fin"] = min(gr["inicio"], a["inicio"]), max(gr["fin"], a["fin"])
        if a["poligono"]:
            gr["poligonos"].append(a["poligono"])
    return sorted(grupos.values(), key=lambda gr: (-NIVELES[gr["nivel"]], -len(gr["zonas"])))


def firma(grupos) -> str:
    return "|".join(sorted(f"{gr['nivel']}:{gr['fenomeno']}:{len(gr['zonas'])}" for gr in grupos))


def _vista_zonas(grupos):
    pts = [p for gr in grupos for pol in gr["poligonos"] for p in pol]
    if not pts or any(la < 30 for _, la in pts):
        return VISTA_GENERAL  # incluye Canarias (se dibujan en su recuadro)
    lo0, lo1 = min(p[0] for p in pts), max(p[0] for p in pts)
    la0, la1 = min(p[1] for p in pts), max(p[1] for p in pts)
    clon, clat = (lo0 + lo1) / 2, (la0 + la1) / 2
    dlon, dlat = max(lo1 - lo0 + 1.5, 4.5), max(la1 - la0 + 1.2, 3.4)
    return (clon - dlon / 2, clon + dlon / 2, clat - dlat / 2, clat + dlat / 2)


def _capa_poligonos(grupos, con_lista=False, consejos=None):
    def dibujar(capa, pr, dt):
        from .mapa import es_canaria, lonlat_mapa
        d = ImageDraw.Draw(capa)
        pulso = 0.75 + 0.25 * math.sin(dt * 4)
        for gr in sorted(grupos, key=lambda x: NIVELES[x["nivel"]]):
            col = COLOR_NIVEL[gr["nivel"]]
            for pol in gr["poligonos"]:
                pts = []
                for lo, la in pol:
                    if es_canaria(la):
                        if not pr.muestra_canarias:
                            continue
                        lo, la = lonlat_mapa(lo, la, True)
                    x, y = pr(lo, la)
                    pts.append((x, MAPA_Y0 + y))
                if len(pts) >= 3:
                    d.polygon(pts, fill=col + (int(150 * pulso),), outline=col + (255,))
                    d.line(pts + [pts[0]], fill=(255, 255, 255, 200), width=3)
        if con_lista:  # etiquetas con el nivel y el fenómeno
            y = MAPA_Y0 + 30
            for gr in grupos[:3]:
                txt = f"AVISO {gr['nivel'].upper()} · {gr['fenomeno'].upper()}"
                f = fuente("Black", 40)
                w = f.getlength(txt) + 50
                d.rounded_rectangle([40, y, 40 + w, y + 64], radius=32, fill=COLOR_NIVEL[gr["nivel"]] + (240,))
                d.text((40 + w / 2, y + 32), txt, font=f, fill=(255, 255, 255), anchor="mm")
                y += 78
        if consejos:
            capa_osc = (5, 12, 30, 200)
            d.rounded_rectangle([40, MAPA_Y0 + 120, ANCHO - 150, MAPA_Y0 + 140 + 150 * len(consejos)], radius=30,
                                fill=capa_osc)
            for k, txt in enumerate(consejos):
                s = min(1, max(0, (dt - 0.3 - k * 0.5) / 0.3))
                if s <= 0:
                    continue
                y = MAPA_Y0 + 160 + k * 150
                d.ellipse([70, y + 10, 130, y + 70], fill=ACENTO + (int(255 * s),))
                d.text((100, y + 40), str(k + 1), font=fuente("Black", 40), fill=(15, 25, 50), anchor="mm")
                f = fuente("ExtraBold", 44)
                d.text((160, y + 40), txt, font=f, fill=(255, 255, 255, int(255 * s)), anchor="lm")
    return dibujar


PROMPT_AVISO = """Eres el guionista de "Paraguas o Chanclas", canal de TikTok del tiempo en España. Hoy NO hay humor:
es un vídeo ESPECIAL por avisos de AEMET. Tono serio, claro y cercano, sin alarmismo ni sensacionalismo. Usa SOLO
estos datos oficiales de AEMET (no inventes cifras, zonas, horas ni daños). Lo lee {presenta} con voz sintética.

Hoy es {fecha}. Avisos naranjas y rojos vigentes o para las próximas horas:
{avisos}

Bloques (palabras aproximadas: {palabras}; total ≈ {total}):
- intro: gancho directo (qué aviso, de qué nivel y dónde) y "quédate, que al final te digo qué hacer".
- zonas: qué zonas concretas y cuándo (horas en palabras, p. ej. "desde las seis de la tarde del domingo").
- detalle: qué se espera exactamente según la descripción de AEMET y qué significa el nivel (naranja: riesgo
  importante; rojo: riesgo extraordinario).
- consejos: las recomendaciones oficiales (de "instrucción") contadas con tus palabras + "en una emergencia, llama
  al 112" + "sigue las indicaciones de AEMET y de Protección Civil".
- cierre: pide compartir el vídeo con quien viva en esas zonas y seguir la cuenta. Sin horas de publicación.
Habla de tú, frases completas que fluyan; números en cifras con "grados", "por ciento", "litros"... sin símbolos.

"titular": 2 a 5 palabras en MAYÚSCULAS, máx. 26 caracteres (ej. "AVISO ROJO EN VALENCIA").
"consejos_pantalla": 3 consejos MUY cortos (máx. 26 caracteres cada uno) para la pantalla.
"caption": una frase (máx. 90 caracteres) con 1 emoji ⚠️, sin hashtags.

Responde SOLO con JSON: {{"segmentos": {{"intro": "...", "zonas": "...", "detalle": "...", "consejos": "...",
"cierre": "..."}}, "titular": "...", "consejos_pantalla": ["...", "...", "..."], "caption": "..."}}"""
PALABRAS_AVISO = {"intro": 26, "zonas": 40, "detalle": 38, "consejos": 44, "cierre": 22}
CONSEJOS_BASE = {"lluvias": ["EVITA ZONAS INUNDABLES", "NO CRUCES CAUCES", "LLAMA AL 112"],
                 "tormentas": ["RESGUÁRDATE BAJO TECHO", "LEJOS DE ÁRBOLES", "LLAMA AL 112"],
                 "vientos": ["CUIDADO CON OBJETOS", "EVITA PARQUES", "LLAMA AL 112"],
                 "costeros": ["LEJOS DE LA COSTA", "NO TE ACERQUES A DIQUES", "LLAMA AL 112"],
                 "temperaturas máximas": ["BEBE AGUA", "EVITA EL SOL", "CUIDA A LOS MAYORES"],
                 "nevadas": ["EVITA CARRETERA", "CADENAS Y DEPÓSITO", "LLAMA AL 112"]}


def _hora_txt(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{g.DIAS[d.weekday()]} {d.day} a las {d:%H:%M}"


def guion_aviso(grupos, hoy: date, factor: float, presenta: str, plantilla: bool) -> dict:
    orden = ["intro", "zonas", "detalle", "consejos", "cierre"]
    palabras = {k: max(8, round(v * factor)) for k, v in PALABRAS_AVISO.items()}
    datos = [{"nivel": gr["nivel"], "fenomeno": gr["fenomeno"], "zonas": gr["zonas"][:12],
              "desde": _hora_txt(gr["inicio"]), "hasta": _hora_txt(gr["fin"]), "descripcion": gr["descripcion"],
              "instruccion": gr["instruccion"]} for gr in grupos[:4]]
    if not plantilla:
        try:
            gg = _claude_json(PROMPT_AVISO.format(presenta=presenta, fecha=g.fecha_larga(hoy),
                                                  avisos=json.dumps(datos, ensure_ascii=False, indent=1),
                                                  palabras=json.dumps(palabras), total=sum(palabras.values())))
            if all(gg["segmentos"].get(s) for s in orden):
                gg.update(origen="claude", orden=orden)
                return gg
        except Exception as e:  # noqa: BLE001
            log.warning("Guion del aviso con Claude falló: %s", e)
    gr = grupos[0]
    zonas = ", ".join(z.split(" - ")[-1] for z in gr["zonas"][:4])
    seg = {
        "intro": f"Atención: AEMET activa el aviso {gr['nivel']} por {gr['fenomeno']}. Quédate, que al final te digo qué hacer.",
        "zonas": f"Afecta a {zonas}, desde el {_hora_txt(gr['inicio'])} hasta el {_hora_txt(gr['fin'])}.",
        "detalle": f"{gr['descripcion']} El nivel {gr['nivel']} significa un riesgo "
                   + ("importante." if gr["nivel"] == "naranja" else "extraordinario."),
        "consejos": "Mantente informado con AEMET, sigue las indicaciones de Protección Civil y, en una emergencia, "
                    "llama al 112.",
        "cierre": "Comparte este vídeo con quien viva en esas zonas y sígueme para tener el tiempo de cada día.",
    }
    return {"segmentos": seg, "orden": orden, "titular": f"AVISO {gr['nivel'].upper()}",
            "caption": f"⚠️ Aviso {gr['nivel']} por {gr['fenomeno']}: lo que tienes que saber",
            "consejos_pantalla": CONSEJOS_BASE.get(gr["fenomeno"], ["SIGUE A AEMET", "PRECAUCIÓN", "LLAMA AL 112"]),
            "origen": "plantilla"}


def caption_aviso(grupos, gancho) -> str:
    lineas = []
    for gr in grupos[:4]:
        zonas = ", ".join(z.split(" - ")[-1] for z in gr["zonas"][:3])
        lineas.append(f"{'🔴' if gr['nivel'] == 'rojo' else '🟠'} Aviso {gr['nivel']} por {gr['fenomeno']}: {zonas}"
                      + (" y más" if len(gr["zonas"]) > 3 else ""))
    lineas += ["ℹ️ Fuente: AEMET. Sigue las indicaciones de Protección Civil. Emergencias: 112."]
    tags = ["#aviso", "#AEMET", "#alerta", "#eltiempo", "#tiempo", "#españa", "#parati", "#paraguasochanclas"]
    for gr in grupos[:2]:
        tags.append("#" + re.sub(r"\W", "", gr["fenomeno"].split()[0]))
    return (f"{(gancho or '⚠️ Aviso de AEMET: lo que tienes que saber').strip()}\n\n" + "\n".join(lineas)
            + "\n\n" + " ".join(dict.fromkeys(tags)))[:2200]


def video_aviso(grupos, hoy: date, salida: Path, demo: bool = False) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "trabajo"
    trabajo.mkdir(exist_ok=True)
    tipo_voz = os.environ.get("VOZ_TIPO") or voz_del_dia(hoy)
    voz.elegir_voz(VOCES[tipo_voz])
    guion, plan, total, trozos, motor = locutar(
        lambda f, pl: guion_aviso(grupos, hoy, f, VOCES[tipo_voz]["presenta"], pl), trabajo, tipo_voz, demo)
    zona = _vista_zonas(grupos)
    consejos = [c.upper()[:28] for c in (guion.get("consejos_pantalla") or [])][:3] or \
        CONSEJOS_BASE.get(grupos[0]["fenomeno"], ["SIGUE A AEMET", "PRECAUCIÓN", "LLAMA AL 112"])
    gr = grupos[0]
    kwargs = {
        "vistas": {"intro": zona, "zonas": zona, "detalle": VISTA_GENERAL, "consejos": zona, "cierre": VISTA_GENERAL},
        "sin_marcadores": ("intro", "zonas", "detalle", "consejos", "cierre"),
        "pills": {"zonas": "ZONAS AFECTADAS", "detalle": "QUÉ SE ESPERA", "consejos": "QUÉ HACER",
                  "cierre": "COMPÁRTELO"},
        "capas": {"intro": _capa_poligonos(grupos), "zonas": _capa_poligonos(grupos, con_lista=True),
                  "detalle": _capa_poligonos(grupos, con_lista=True),
                  "consejos": _capa_poligonos(grupos, consejos=consejos), "cierre": _capa_poligonos(grupos)},
        "portada_txt": ("AVISO DE AEMET", f"AVISO {gr['nivel'].upper()}", gr["fenomeno"].upper(),
                        tuple((z.split(" - ")[-1].upper()[:30], COLOR_NIVEL[gr["nivel"]]) for z in gr["zonas"][:2])),
    }
    video = _producir(f"aviso_{hoy.isoformat()}", guion, plan, total, trozos, kwargs, [], None,
                      g.fecha_larga(hoy).upper(), salida, trabajo)
    caption = caption_aviso(grupos, guion.get("caption") if guion.get("origen") == "claude" else None)
    return {"tipo": "aviso", "fecha": hoy.isoformat(), "video": str(video), "caption": caption,
            "titular": guion.get("titular"), "motor_voz": motor, "origen_guion": guion.get("origen"),
            "duracion": round(voz.duracion(video), 2), "firma": firma(grupos), "guion": guion["segmentos"],
            "nivel_max": max(NIVELES[x["nivel"]] for x in grupos)}


def avisos_demo() -> list[dict]:
    pol = [(-0.6, 39.9), (-0.1, 39.9), (0.1, 39.4), (-0.2, 38.9), (-0.5, 38.9), (-0.7, 39.4)]
    pol2 = [(-0.5, 38.8), (0.2, 38.8), (0.2, 38.4), (-0.6, 38.3)]
    return [{"fenomeno": "lluvias", "nivel": "rojo", "zonas": ["Litoral sur de Valencia", "Litoral norte de Valencia"],
             "inicio": "2026-10-26T06:00:00+01:00", "fin": "2026-10-26T23:59:59+01:00",
             "descripcion": "Precipitación acumulada en una hora de 90 litros por metro cuadrado.",
             "instruccion": "Tome medidas preventivas y actúe según las indicaciones de las autoridades.",
             "poligonos": [pol]},
            {"fenomeno": "lluvias", "nivel": "naranja", "zonas": ["Litoral norte de Alicante"],
             "inicio": "2026-10-26T06:00:00+01:00", "fin": "2026-10-26T23:59:59+01:00",
             "descripcion": "Precipitación acumulada en una hora de 40 litros por metro cuadrado.",
             "instruccion": "Esté preparado.", "poligonos": [pol2]}]


# ================================================================ publicación y CLI
def _publicar(meta: dict, hoy: date):
    from . import uploadpost
    from .main import publicar_youtube
    from .tiktok import hay_credenciales, publicar_con_reintentos
    hecho = False
    if uploadpost.disponible():
        try:
            meta["tiktok"] = uploadpost.publicar_tiktok(Path(meta["video"]), meta["caption"], "tiempo")
            hecho = True
        except Exception as e:  # noqa: BLE001
            log.error("Upload-Post falló (%s): borrador", e)
    if not hecho and not hay_credenciales():
        meta["tiktok"] = publicar_con_reintentos(Path(meta["video"]), meta["caption"], 0)
    publicar_youtube(meta, hoy)


def _guardar_texto(meta: dict, titulo: str):
    """Añade el texto del especial a la página del móvil (docs/hoy.html) junto al del parte."""
    from .repo import subir
    ruta = RAIZ / "docs" / "hoy.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        datos = {}
    hoy = ahora().date().isoformat()
    if datos.get("fecha") != hoy:
        datos = {"fecha": hoy, "caption": datos.get("caption", ""), "anterior": True}
    datos.setdefault("extras", []).append({"titulo": titulo, "caption": meta["caption"], "hora": f"{ahora():%H:%M}"})
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    subir([ruta], f"Texto del especial: {titulo}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tipo", choices=["finde", "avisos"])
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--publicar", action="store_true")
    ap.add_argument("--esperar", action="store_true", help="finde: esperar a las 17:30")
    ap.add_argument("--fecha")
    ap.add_argument("--salida", default=str(RAIZ / "salida_especial"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hoy = date.fromisoformat(a.fecha) if a.fecha else ahora().date()
    HISTORIAL.mkdir(exist_ok=True)

    if a.tipo == "finde":
        hist = HISTORIAL / f"finde-{hoy.isoformat()}.json"
        if hist.exists() and not a.demo:
            log.info("El vídeo del finde ya está hecho")
            return
        meta = fin_de_semana(hoy, Path(a.salida), a.demo)
        titulo = "Fin de semana"
    else:
        hist_aviso = HISTORIAL / f"aviso-{hoy.isoformat()}.json"
        previo = json.loads(hist_aviso.read_text()) if hist_aviso.exists() else None
        if a.demo:
            grupos = avisos_demo()
        else:
            clave = os.environ.get("AEMET_API_KEY", "")
            grupos = agrupar(avisos_relevantes(descargar_avisos(clave), datetime.now().astimezone()))
        if not grupos:
            log.info("No hay avisos naranjas ni rojos: no se hace especial")
            return
        nivel = max(NIVELES[x["nivel"]] for x in grupos)
        # Un especial al día, salvo que la situación empeore a rojo después de uno naranja
        if previo and not a.demo and (nivel <= previo.get("nivel_max", 0)):
            log.info("Ya se publicó un especial hoy (%s) y el nivel no ha empeorado", previo.get("firma"))
            return
        meta = video_aviso(grupos, hoy, Path(a.salida), a.demo)
        hist = hist_aviso
        titulo = f"Aviso {grupos[0]['nivel']}"

    log.info("Especial listo: %s (%.2f s, voz %s, guion %s)", meta["video"], meta["duracion"], meta["motor_voz"],
             meta["origen_guion"])
    (Path(a.salida) / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.demo:
        return
    _guardar_texto(meta, titulo)
    if a.publicar:
        if a.esperar and a.tipo == "finde":
            from .horario import TZ
            import time as _t
            objetivo = ahora().replace(hour=17, minute=26, second=0, microsecond=0)
            falta = (objetivo - ahora()).total_seconds()
            if 0 < falta < 4 * 3600:
                log.info("Esperando %.0f min hasta las 17:30", falta / 60)
                _t.sleep(falta)
        _publicar(meta, hoy)
    hist.write_text(json.dumps({k: v for k, v in meta.items() if k != "video"}, ensure_ascii=False, indent=1),
                    encoding="utf-8")


if __name__ == "__main__":
    main()
