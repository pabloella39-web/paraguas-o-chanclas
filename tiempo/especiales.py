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

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter

from . import cumplido, eleven, musica, voz
from . import guion as g
from .config import (ANCHO, DURACION_MAX, DURACION_MIN, DURACION_OBJETIVO, MODELO_CLAUDE, RAIZ, VISTA_GENERAL,
                     VOCES, voz_del_dia)
from .contexto import notas_rango
from .poblaciones import titular_aviso, titular_avisos
from .horario import ahora
from .mapa import fuente
from .video import MAPA_H, MAPA_Y0, Compositor, renderizar

log = logging.getLogger("tiempo.especiales")
HISTORIAL = RAIZ / "historial_especiales"
ACENTO = (255, 196, 45)
MESES_CORTOS = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


# ================================================================ duración (los avisos son cortos)
from contextlib import contextmanager


@contextmanager
def duracion(dmin: float, dmax: float, dobj: float):
    """Cambia temporalmente el rango de duración (65-70 s por defecto) para un vídeo especial."""
    import sys
    from . import main as M
    mods = [M, sys.modules[__name__]]
    viejos = [(m, m.DURACION_MIN, m.DURACION_MAX, m.DURACION_OBJETIVO) for m in mods]
    for m in mods:
        m.DURACION_MIN, m.DURACION_MAX, m.DURACION_OBJETIVO = dmin, dmax, dobj
    try:
        yield
    finally:
        for m, a, b, c in viejos:
            m.DURACION_MIN, m.DURACION_MAX, m.DURACION_OBJETIVO = a, b, c


DURACION_SEMANA = (85.0, 95.0, 90.0)
VOZ_USADA = ""   # voz del especial que se está haciendo (para alternar con el siguiente vídeo)


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
        if not demo and not os.environ.get("PERMITIR_PLANTILLA"):
            raise
        log.warning("%s → plantilla", e)
        guion = escribir(0.85, True)
        bloques = [s for s in guion["orden"] if guion["segmentos"].get(s, "").strip()]
        wavs = [voz.sintetizar(guion["segmentos"][s], trabajo / f"p_{s}.mp3", demo, VEL_MAX) for s in bloques]
        plan, total = planificar(bloques, wavs, [voz.duracion(w) for w in wavs])
    return guion, plan, total, [(p["wav"], p["inicio"]) for p in plan], "edge-tts"


def _claude_json(manual_clave, limite=None, prompt: str = None) -> dict:
    """Primero el guion escrito con el plan de Claude (tiempo/manual.py); si no llega, la API."""
    if prompt is None:  # llamada antigua: _claude_json(prompt)
        manual_clave, limite, prompt = None, None, manual_clave
    if manual_clave:
        from . import manual
        g_ = manual.responder(manual_clave, prompt, limite)
        if g_:
            return g_
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
ligero (sin palabrotas, sin política). Es viernes por la noche: toca el vídeo del FIN DE SEMANA. IMPORTANTE: hoy NO
sale el parte diario: este vídeo es TAMBIÉN el parte de MAÑANA SÁBADO, así que el bloque del sábado es el más largo y
detallado (recorre España por zonas con las ciudades destacadas, sus cifras y un consejo; Ceuta y Melilla solo si tienen algo relevante). Usa SOLO estos datos
(no inventes temperaturas, lluvias ni avisos). Lo lee {presenta} con voz sintética.

Sábado {sab} y domingo {dom}. Datos por ciudad (grados, lluvia = probabilidad máxima del día en %, lluvia_mm = litros previstos;
con menos de 1 litro son lloviznas y con menos del 70 % o de 2 litros nunca digas lluvia segura;
con 5 litros o más di cuántos litros por metro cuadrado caerán):
SÁBADO: {datos_sab}
DOMINGO: {datos_dom}
Otras ciudades para el bloque largo del sábado (nómbralas si tienen algo más llamativo que las de siempre, para variar:
Vigo u Ourense en vez de A Coruña, Gijón en vez de Oviedo, Córdoba en vez de Sevilla, Burgos o León…): {extra}

DÍAS TRANQUILOS (sin avisos naranja/rojo, sin lluvia importante ni temperaturas extremas): el gancho NO puede ser
"cuatro gotas en una ciudad" ni un dato local flojo, porque a quien no es de allí no le importa y desliza. Abre con un
gancho HUMANO para toda España: el plan del día o del finde, un evento del CONTEXTO DEL DÍA (Halloween, festivo,
puente, cambio de hora), qué ropa ponerse, tender la ropa, terraza o manta ("Este finde es día de terraza en casi toda
España, menos en un sitio."). Y el cierre termina con UNA pregunta que se conteste en una o dos palabras y genere
debate ("¿Chaqueta o manga corta mañana? Te leo.", "¿Terraza o sofá este finde?", "¿Castañas o disfraz?"): los
comentarios son lo que hace que TikTok reparta el vídeo.
Varía la fórmula del arranque ("Ojo" vale de vez en cuando, pero no siempre).
PRIMERA FRASE de la intro: MÁXIMO 8 PALABRAS, corta y seca (ej. "Finde de sol, salvo en dos sitios."); luego ya amplías.
RETENCIÓN: la intro NO saluda: arranca con lo más llamativo del finde (¿se estropea el domingo?, ¿último finde
de playa?, ¿frío de verdad?) y promete que al final dirás dónde está el mejor plan del fin de semana.
Habla de tú, frases que fluyan, nada de listas ni dos puntos, números en cifras con "grados" o "por ciento".
Interpela a la gente de alguna ciudad. Ciudades por su nombre (S.C. Tenerife = Santa Cruz de Tenerife).

Festivos y fiestas este finde (los marcados [SIEMPRE] se nombran siempre, en el bloque de su día y ligados al
tiempo; el resto, solo si no hay nada más relevante): {fiestas}

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
PALABRAS_FINDE = {"intro": 22, "sabado": 56, "domingo": 36, "general": 30, "cierre": 20}


def _resumen(prev):
    return [{k: c[k] for k in ("nombre", "tmax", "tmin", "lluvia", "lluvia_mm", "icono") if c.get(k) is not None}
            for c in prev]


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
            gg = _claude_json(f"finde-{ahora().date().isoformat()}", "19:50", PROMPT_FINDE.format(presenta=presenta, sab=g.fecha_larga(sab), dom=g.fecha_larga(dom),
                                                  datos_sab=json.dumps(_resumen(prev_s), ensure_ascii=False),
                                                  datos_dom=json.dumps(_resumen(prev_d), ensure_ascii=False),
                                                  palabras=json.dumps(palabras), total=sum(palabras.values()),
                                                  fiestas=(" ".join(notas_rango(sab, dom)) or "(ninguno)") + _dato_real(),
                                                  extra=json.dumps(_extra_por_region(), ensure_ascii=False)))
            if all(gg["segmentos"].get(s) for s in orden):
                gg.update(origen="claude", orden=orden)
                return gg
        except Exception as e:  # noqa: BLE001
            log.warning("Guion del finde con Claude falló: %s", e)
    if not plantilla and not os.environ.get("PERMITIR_PLANTILLA"):
        raise RuntimeError("Sin guion escrito ni API: no se publica la plantilla básica")
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
    tags = ["#eltiempo", "#finde", "#tiempofindesemana", "#paraguasochanclas"]
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
            from .fuentes import EXTRA
            EXTRA_SEMANA[:] = list(EXTRA)   # otras ciudades para el bloque largo del sábado
            prev_d, _ = obtener_previsiones(dom)
        finally:
            if clave_google:
                os.environ["GOOGLE_WEATHER_API_KEY"] = clave_google
    if not demo:
        _preparar_avisos({"sabado": sab, "domingo": dom})
    tipo_voz = os.environ.get("VOZ_TIPO") or "masculina"   # vídeos importantes: voz masculina
    global VOZ_USADA
    VOZ_USADA = tipo_voz
    voz.elegir_voz(VOCES[tipo_voz])
    guion, plan, total, trozos, motor = locutar(
        lambda f, pl: guion_finde(prev_s, prev_d, sab, dom, f, VOCES[tipo_voz]["presenta"], pl),
        trabajo, tipo_voz, demo)
    todos = prev_s + prev_d
    extremos = {"calor": max(todos, key=lambda c: c["tmax"]), "frio": min(todos, key=lambda c: c["tmin"])}
    rango = f"{sab.day} {MESES_CORTOS[sab.month - 1]} · {dom.day} {MESES_CORTOS[dom.month - 1]}"
    (ms, _), _ = _mejor_plan(prev_s, prev_d)
    kwargs = {
        "datos_seg": {"sabado": g.prev_para_mapa(prev_s, [guion["segmentos"].get("sabado", "")], EXTRA_SEMANA),
                      "domingo": prev_d, "intro": []},
        "capas_fondo": _capas_dias(), "capas_encima": _capas_encima_dias(),
        "pills": {"sabado": f"SÁBADO {sab.day}", "domingo": f"DOMINGO {dom.day}", "general": "EL MEJOR PLAN DEL FINDE",
                  "promesa": "QUÉDATE: AL FINAL, EL MEJOR PLAN DEL FINDE"},
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


# ================================================================ la semana que viene (domingo por la noche)
DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes"]
NOMBRE_DIA = {"lunes": "LUNES", "martes": "MARTES", "miercoles": "MIÉRCOLES", "jueves": "JUEVES", "viernes": "VIERNES",
              "sabado": "SÁBADO", "domingo": "DOMINGO"}
# Dos ediciones: domingo por la noche (de lunes a viernes) y miércoles por la noche (lo que queda de semana + finde)
MODOS_SEMANA = {
    "semana": {"dias": ["lunes", "martes", "miercoles", "jueves", "viernes"], "titulo": "LA SEMANA QUE VIENE",
               "subtitulo": "DE LUNES A VIERNES", "cuando": "Es domingo por la noche: toca el vídeo de LA SEMANA QUE VIENE",
               "rango_txt": "de lunes a viernes", "archivo": "semana"},
    "resto": {"dias": ["jueves", "viernes", "sabado", "domingo"], "titulo": "LO QUE QUEDA DE SEMANA",
              "subtitulo": "DE JUEVES A DOMINGO", "cuando": "Es miércoles por la noche: toca LO QUE QUEDA DE SEMANA Y EL "
              "FIN DE SEMANA (de jueves a domingo); da importancia al finde y a los planes", "rango_txt":
              "de jueves a domingo", "archivo": "resto"},
}
MODO_SEMANA = "semana"


def _dias():
    return MODOS_SEMANA[MODO_SEMANA]["dias"]


def _hablado(d: str) -> str:
    return {"miercoles": "miércoles", "sabado": "sábado"}.get(d, d)
PALABRAS_SEMANA = {"intro": 20, "lunes": 24, "martes": 22, "miercoles": 22, "jueves": 22, "viernes": 24,
                   "general": 26, "cierre": 18}
PROMPT_SEMANA = """Eres el guionista de "Paraguas o Chanclas", un canal de TikTok sobre el tiempo en España con humor
ligero (sin palabrotas, sin política). {cuando}, para que la gente se organice. Usa SOLO estos datos (no inventes). Lo lee {presenta} con voz sintética.

Datos por día y ciudad (grados, lluvia = probabilidad máxima del día en %, lluvia_mm = litros previstos;
con menos de 1 litro son lloviznas y con menos del 70 % o de 2 litros nunca digas lluvia segura; a varios días vista
mejor 'posibles chubascos' que afirmaciones rotundas; con 5 litros o más di cuántos litros por metro cuadrado):
{datos}

Varía la fórmula del arranque ("Ojo" vale de vez en cuando, pero no siempre).
PRIMERA FRASE de la intro: MÁXIMO 8 PALABRAS, corta y seca (ej. "Finde de sol, salvo en dos sitios."); luego ya amplías.
RETENCIÓN: la intro NO saluda: arranca con lo más llamativo de la semana (¿vuelve la lluvia el miércoles?, ¿bajón
de temperaturas?, ¿semana de sol?) y promete que al final dirás cuál es el mejor día de la semana y cuál el peor.
Un bloque por día, {rango_txt}: lo destacado de ese día en España, agrupando zonas, con alguna ciudad concreta
y un consejo práctico (paraguas, chaqueta, tender la ropa, ir en bici...). Habla de tú, frases que fluyan, nada de
listas ni dos puntos, números en cifras con "grados" o "por ciento". Ciudades por su nombre.
- general: la recompensa: el mejor día de la semana y el peor (y por qué), con alguna cifra.
- cierre: pregunta para comentarios ("¿qué día te toca mojarte?", "¿qué plan tienes esta semana?") y que sigan la
  cuenta para tener el tiempo de cada día. NUNCA digas horas de publicación.
IMPORTANTE: hoy NO sale el parte diario: este vídeo es TAMBIÉN el parte de MAÑANA ({primero}). Su bloque es el
más largo y detallado: recorre España por zonas (norte, interior, Mediterráneo, sur, islas) con las ciudades
destacadas, sus cifras y un consejo (Ceuta y Melilla solo si tienen algo relevante). Los demás días, más breves:
solo lo destacado. Si mañana pasa algo llamativo (lluvia fuerte, rachas, calor, frío), la intro puede abrir con ello.
Festivos y fiestas en estos días (los marcados [SIEMPRE] se nombran siempre, cada uno en el bloque de su día y
ligado al tiempo; el resto, solo si no hay nada más relevante): {fiestas}
Para el bloque de mañana tienes además otras ciudades de cada región: {extra}
VARIEDAD: no nombres siempre las mismas capitales; si una de estas otras ciudades tiene algo más llamativo (más
lluvia, más calor o frío, más viento), nómbrala a ella (Vigo, Ourense o Pontevedra en vez de A Coruña; Gijón en vez de
Oviedo; Córdoba o Jaén en vez de Sevilla; Burgos o León en el interior...). Más repetidas en los últimos vídeos (solo
si son la noticia): {repetidas}.
DÍAS TRANQUILOS (sin avisos naranja/rojo, sin lluvia importante ni temperaturas extremas): el gancho NO puede ser
"cuatro gotas en una ciudad" ni un dato local flojo, porque a quien no es de allí no le importa y desliza. Abre con un
gancho HUMANO para toda España: el plan del día o del finde, un evento del CONTEXTO DEL DÍA (Halloween, festivo,
puente, cambio de hora), qué ropa ponerse, tender la ropa, terraza o manta ("Este finde es día de terraza en casi toda
España, menos en un sitio."). Y el cierre termina con UNA pregunta que se conteste en una o dos palabras y genere
debate ("¿Chaqueta o manga corta mañana? Te leo.", "¿Terraza o sofá este finde?", "¿Castañas o disfraz?"): los
comentarios son lo que hace que TikTok reparta el vídeo.
Palabras aproximadas por bloque: {palabras}; total ≈ {total}. Es crucial respetarlo.

"titular": 2 a 5 palabras en MAYÚSCULAS, máx. 26 caracteres, sin emojis (ej. "SEMANA PASADA POR AGUA").
"caption": una frase gancho (máx. 90 caracteres), con 1 o 2 emojis, sin hashtags.

Responde SOLO con JSON: {{"segmentos": {{"intro": "...", {claves_dias}, "general": "...", "cierre": "..."}},
"titular": "...", "caption": "..."}}"""


EXTRA_SEMANA: list = []


AVISOS_TXT = [""]   # avisos y oleaje previstos para los días del vídeo (lo rellenan la_semana y fin_de_semana)
AVISOS_DIA = {}
MAR_NIEVE = {}   # {día: (olas, nieve)} para dibujarlos en el mapa de cada día


def _preparar_avisos(dias: dict):
    """Avisos (coloreados en el mapa de su día) y oleaje fuerte, para el prompt de los especiales."""
    from .fuentes import COSTA, oleaje, texto_oleaje
    AVISOS_DIA.clear()
    try:
        AVISOS_DIA.update(avisos_por_dia(dias))
    except Exception as e:  # noqa: BLE001
        log.warning("Avisos por día: %s", e)
    from .fuentes import nieve, texto_nieve
    olas, nieves = {}, {}
    for k, d in dias.items():
        olas[k] = oleaje(d)
        nieves[k] = nieve(d)
    MAR_NIEVE.clear()
    for k, d in dias.items():
        ol = [{"zona": z, "olas": m, **next((dict(lat=la, lon=lo) for zz, la, lo in COSTA if zz == z), {})}
              for z, m in olas[k]]
        MAR_NIEVE[k] = (ol, nieves[k])
    AVISOS_TXT[0] = texto_avisos(AVISOS_DIA) + texto_oleaje(olas) + texto_nieve(nieves)


def _capas_dias() -> dict:
    return {k: capa_avisos_suave(v) for k, v in AVISOS_DIA.items() if v}


def _capas_encima_dias() -> dict:
    out = {}
    for k in set(MAR_NIEVE) | set(AVISOS_DIA):
        ol, ni = MAR_NIEVE.get(k, ([], []))
        nb = nieblas_de(AVISOS_DIA.get(k))
        if ol or ni or nb:
            out[k] = capa_mar_nieve(ol, ni, nb)
    return out


def _dato_real() -> str:
    """Lo medido tras el aviso naranja/rojo de anoche (si lo hubo), para una frase en la intro."""
    try:
        n = cumplido.nota()
    except Exception as e:  # noqa: BLE001
        log.warning("Dato real del aviso: %s", e)
        n = ""
    extra = f"\n\nADEMÁS, en la intro o en el bloque del primer día: {n}" if n else ""
    try:
        o = g.nota_olvidadas(ahora().date())
    except Exception:  # noqa: BLE001
        o = ""
    return extra + (f"\n\n{o}" if o else "") + AVISOS_TXT[0]


def _extra_por_region() -> dict:
    out = {}
    for c in EXTRA_SEMANA:
        out.setdefault(c["region"], []).append({k: v for k, v in c.items() if k != "region"})
    return out or {"aviso": "no disponibles"}


def _nota_dia(prev):
    return sum(c["tmax"] - c["lluvia"] / 6 - (6 if c["icono"] in ("lluvia", "tormenta", "nieve") else 0)
               for c in prev) / max(1, len(prev))


def guion_semana(prevs: dict, fechas: dict, factor: float, presenta: str, plantilla: bool) -> dict:
    orden = ["intro"] + _dias() + ["general", "cierre"]
    # El primer día (mañana) hace de parte diario: bloque largo; los demás, más breves
    resto_dias = round(116 / (len(_dias()) - 1))   # ≈90 s en total: el vídeo estrella de la semana
    base = {"intro": 24, **{d: resto_dias for d in _dias()}, "general": 30, "cierre": 18}
    base[_dias()[0]] = 54
    palabras = {k: max(8, round(v * factor)) for k, v in base.items()}
    if not plantilla:
        try:
            datos = {f"{d} {fechas[d].day}": _resumen(prevs[d]) for d in _dias()}
            m = MODOS_SEMANA[MODO_SEMANA]
            gg = _claude_json(f"{MODO_SEMANA}-{ahora().date().isoformat()}", "19:50", PROMPT_SEMANA.format(presenta=presenta, datos=json.dumps(datos, ensure_ascii=False),
                                                   palabras=json.dumps(palabras), total=sum(palabras.values()),
                                                   cuando=m["cuando"], rango_txt=m["rango_txt"],
                                                   claves_dias=", ".join(f'"{d}": "..."' for d in _dias()),
                                                   primero=f"{_hablado(_dias()[0])} {fechas[_dias()[0]].day}",
                                                   extra=json.dumps(_extra_por_region(), ensure_ascii=False),
                                                   fiestas=(" ".join(notas_rango(fechas[_dias()[0]], fechas[_dias()[-1]])) or "(ninguno)")
                                                   + _dato_real(),
                                                   repetidas=", ".join(g.ciudades_repetidas(fechas[_dias()[0]],
                                                                                            prevs[_dias()[0]]))
                                                   or "(ninguna)"))
            if all(gg["segmentos"].get(s) for s in orden):
                gg.update(origen="claude", orden=orden)
                return gg
        except Exception as e:  # noqa: BLE001
            log.warning("Guion de la semana con Claude falló: %s", e)
    if not plantilla and not os.environ.get("PERMITIR_PLANTILLA"):
        raise RuntimeError("Sin guion escrito ni API: no se publica la plantilla básica")
    notas = {d: _nota_dia(prevs[d]) for d in _dias()}
    mejor, peor = max(notas, key=notas.get), min(notas, key=notas.get)
    seg = {"intro": "¿Semana de paraguas o de chanclas? Te la cuento día a día, y al final, el mejor y el peor día."}
    for d in _dias():
        pr = prevs[d]
        llueve = [g._nombre(c) for c in pr if c["lluvia"] >= 50]
        seg[d] = (f"El {_hablado(d)}, " +
                  (f"lluvia en {' y '.join(llueve[:2])}" if llueve else "tiempo tranquilo en casi toda España") +
                  f", con máximas de hasta {max(c['tmax'] for c in pr)} grados.")
    seg["general"] = (f"Lo prometido: el mejor día, el {_hablado(mejor)}; y el peor, el "
                      f"{_hablado(peor)}. Organízate bien.")
    seg["cierre"] = "¿Qué día te toca mojarte? Cuéntamelo en comentarios y sígueme para el tiempo de cada día."
    return {"segmentos": seg, "orden": orden, "titular": MODOS_SEMANA[MODO_SEMANA]["titulo"],
            "caption": "Tu semana, día a día: ¿paraguas o chanclas? 👇", "origen": "plantilla"}


def caption_semana(prevs: dict, fechas: dict, gancho) -> str:
    from .descripcion import _estacion
    iconos = {"sol": "☀️", "sol_nubes": "🌤️", "nubes": "☁️", "lluvia": "🌧️", "chubascos": "🌦️", "tormenta": "⛈️",
              "nieve": "❄️", "niebla": "🌫️"}
    lineas = []
    for d in _dias():
        pr = prevs[d]
        dom = max(set(c["icono"] for c in pr), key=lambda i: sum(1 for c in pr if c["icono"] == i))
        llueve = [c["nombre"] for c in sorted(pr, key=lambda c: -c["lluvia"]) if c["lluvia"] >= 50][:2]
        lineas.append(f"{iconos.get(dom, '🌤️')} {NOMBRE_DIA[d].capitalize()} {fechas[d].day}: máx. "
                      f"{max(c['tmax'] for c in pr)}°" + (f" · lluvia en {', '.join(llueve)}" if llueve else ""))
    tags = ["#eltiempo", "#tiempomañana", "#tiemposemana", "#paraguasochanclas"]
    cab = ("El tiempo de la semana que viene en España 🇪🇸" if MODO_SEMANA == "semana"
           else "Lo que queda de semana y el finde en España 🇪🇸")
    return (f"{(gancho or 'Tu semana, día a día 👇').strip()}\n\n{cab}\n"
            + "\n".join(lineas) + "\n\n" + " ".join(tags))[:2200]


def la_semana(domingo: date, salida: Path, demo: bool = False) -> dict:
    from .fuentes import obtener_previsiones, previsiones_demo
    fechas = {d: domingo + timedelta(days=k + 1) for k, d in enumerate(_dias())}
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "trabajo"
    trabajo.mkdir(exist_ok=True)
    prevs = {}
    if demo:
        base, _ = previsiones_demo()
        rnd = random.Random(5)
        for d in _dias():
            prevs[d] = copy.deepcopy(base)
            for c in prevs[d]:
                c["tmax"] += rnd.choice([-3, -1, 0, 2])
                c["lluvia"] = min(100, max(0, c["lluvia"] + rnd.choice([-20, 0, 30])))
    else:
        # Varios días vista: consenso de modelos de Open-Meteo (AEMET y Google solo se piden para el parte diario)
        guardadas = {k: os.environ.pop(k, None) for k in ("GOOGLE_WEATHER_API_KEY", "AEMET_API_KEY")}
        try:
            for d in _dias():
                prevs[d], _ = obtener_previsiones(fechas[d])
                if d == _dias()[0]:  # otras ciudades para el bloque largo de mañana
                    from .fuentes import EXTRA
                    EXTRA_SEMANA[:] = list(EXTRA)
        finally:
            for k, v in guardadas.items():
                if v:
                    os.environ[k] = v
    if not demo:
        _preparar_avisos({d: fechas[d] for d in _dias()})
    tipo_voz = os.environ.get("VOZ_TIPO") or "masculina"   # vídeos importantes: voz masculina
    global VOZ_USADA
    VOZ_USADA = tipo_voz
    voz.elegir_voz(VOCES[tipo_voz])
    guion, plan, total, trozos, motor = locutar(
        lambda f, pl: guion_semana(prevs, fechas, f, VOCES[tipo_voz]["presenta"], pl), trabajo, tipo_voz, demo)
    todos = [c for d in _dias() for c in prevs[d]]
    extremos = {"calor": max(todos, key=lambda c: c["tmax"]), "frio": min(todos, key=lambda c: c["tmin"])}
    lun, vie = fechas[_dias()[0]], fechas[_dias()[-1]]
    rango = f"{lun.day} {MESES_CORTOS[lun.month - 1]} · {vie.day} {MESES_CORTOS[vie.month - 1]}"
    notas = {d: _nota_dia(prevs[d]) for d in _dias()}
    mejor = max(notas, key=notas.get)
    sat = None
    if not demo:  # el vídeo semanal también enseña el satélite si mañana viene algo gordo
        try:
            from . import satelite
            toca, motivo = satelite.merece_satelite(fechas[_dias()[0]])
            if toca:
                sat, info_sat = satelite.preparar(fechas[_dias()[0]])
                log.info("Satélite en el vídeo semanal (%s): %s", motivo, info_sat)
        except Exception as e:  # noqa: BLE001
            log.warning("Sin satélite: %s", e)
    primero = _dias()[0]
    mapa_dias = {d: prevs[d] for d in _dias()}
    mapa_dias[primero] = g.prev_para_mapa(prevs[primero], [guion["segmentos"].get(primero, "")], EXTRA_SEMANA)
    kwargs = {
        "satelite": sat,
        "capas_fondo": _capas_dias(), "capas_encima": _capas_encima_dias(),
        "datos_seg": {**mapa_dias, "intro": []},
        "pills": {**{d: f"{NOMBRE_DIA[d]} {fechas[d].day}" for d in _dias()},
                  "general": "EL MEJOR Y EL PEOR DÍA", "cierre": "¡FELIZ SEMANA!" if MODO_SEMANA == "semana" else "¡BUEN FINDE!",
                  "promesa": "QUÉDATE: AL FINAL, EL MEJOR Y EL PEOR DÍA"},
        # Portada reconocible en el perfil: fondo granate, borde dorado y la tira de días con su icono y máxima
        "dias_portada": [(NOMBRE_DIA[d][:3].upper(), max(set(c["icono"] for c in prevs[d]),
                                                         key=lambda i, pr=prevs[d]: sum(1 for c in pr if c["icono"] == i)),
                          max(c["tmax"] for c in prevs[d])) for d in _dias()],
        "portada_txt": (MODOS_SEMANA[MODO_SEMANA]["titulo"], MODOS_SEMANA[MODO_SEMANA]["subtitulo"], rango,
                        ((f"MEJOR DÍA: {NOMBRE_DIA[mejor]}", (255, 196, 45)),
                         (f"MÁX {extremos['calor']['tmax']}° · MÍN {extremos['frio']['tmin']}°", (140, 205, 255)))),
    }
    video = _producir(f"{MODOS_SEMANA[MODO_SEMANA]['archivo']}_{lun.isoformat()}", guion, plan, total, trozos, kwargs,
                      prevs[_dias()[0]], extremos,
                      ("SEMANA " if MODO_SEMANA == "semana" else "HASTA EL DOMINGO ") + rango, salida, trabajo)
    caption = caption_semana(prevs, fechas, guion.get("caption") if guion.get("origen") == "claude" else None)
    return {"tipo": MODO_SEMANA, "fecha": domingo.isoformat(), "video": str(video), "caption": caption,
            "titular": guion.get("titular"), "motor_voz": motor, "origen_guion": guion.get("origen"),
            "duracion": round(voz.duracion(video), 2), "guion": guion["segmentos"]}


# ================================================================ avisos de AEMET
NS = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}
NIVELES = {"amarillo": 1, "naranja": 2, "rojo": 3}
COLOR_NIVEL = {"amarillo": (255, 205, 40), "naranja": (255, 140, 0), "rojo": (230, 30, 40)}


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


def avisos_relevantes(avisos: list[dict], momento: datetime, horas: int = 12) -> list[dict]:
    """Avisos NARANJAS y ROJOS vigentes o que empiezan en las próximas `horas` y que afectan a alguna población de más
    de 100.000 habitantes (su ubicación cae dentro del polígono oficial de la zona)."""
    from .poblaciones import afectadas
    out = []
    for a in avisos:
        if NIVELES.get(a["nivel"], 0) < 2:
            continue
        try:
            ini, fin = datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"])
        except (TypeError, ValueError):
            continue
        if not (fin > momento and ini < momento + timedelta(hours=horas)):
            continue
        ciudades = afectadas([a.get("poligono") or []], a.get("zona", ""))
        if ciudades:
            out.append({**a, "ciudades": ciudades})
    return out


def agrupar(avisos: list[dict]) -> list[dict]:
    grupos = {}
    for a in avisos:
        k = (a["fenomeno"], a["nivel"])
        gr = grupos.setdefault(k, {"fenomeno": a["fenomeno"], "nivel": a["nivel"], "zonas": [], "inicio": a["inicio"],
                                   "fin": a["fin"], "descripcion": a["descripcion"], "instruccion": a["instruccion"],
                                   "poligonos": [], "ciudades": [], "descripciones": []})
        if a.get("descripcion") and a["descripcion"] not in gr["descripciones"]:
            gr["descripciones"].append(a["descripcion"])
        for c in a.get("ciudades", []):
            if c not in gr["ciudades"]:
                gr["ciudades"].append(c)
        if a["zona"] not in gr["zonas"]:
            gr["zonas"].append(a["zona"])
        gr["inicio"], gr["fin"] = min(gr["inicio"], a["inicio"]), max(gr["fin"], a["fin"])
        if a["poligono"]:
            gr["poligonos"].append(a["poligono"])
    return sorted(grupos.values(), key=lambda gr: (-NIVELES[gr["nivel"]], -len(gr.get("ciudades", [])),
                                                   -len(gr["zonas"])))


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
    cache = {}

    def dibujar(capa, pr, dt):
        from .mapa import es_canaria, lonlat_mapa
        d = ImageDraw.Draw(capa)
        pulso = 0.75 + 0.25 * math.sin(dt * 4)
        clave = (tuple(pr.vista), pr.ancho, pr.alto)
        if clave not in cache:   # provincias pintadas enteras y costa subrayada (se calcula una vez)
            cache[clave] = pintar_avisos(grupos, pr, alfa=170)[0]
        lay = cache[clave].copy()
        lay.putalpha(lay.getchannel("A").point(lambda a: int(a * pulso)))
        capa.alpha_composite(lay, (0, MAPA_Y0))
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


def pintar_avisos(grupos, pr, alfa=120):
    """Capa (ANCHO × MAPA_H) con los avisos pintados como se ven en la tele:
    - oleaje / fenómenos costeros: se subraya la LÍNEA DE COSTA de la zona afectada con el color del nivel;
    - el resto: se pinta ENTERA la provincia (o provincias) del aviso con el color del nivel."""
    import numpy as np
    from .mapa import es_canaria, etiquetas_provincias, lonlat_mapa
    lab, nombres, costa = etiquetas_provincias(pr)
    h, w = lab.shape
    out = np.zeros((h, w, 4), np.uint8)
    vistos = []
    for gr in sorted(grupos, key=lambda x: NIVELES[x["nivel"]]):          # el nivel más alto queda encima
        col = COLOR_NIVEL[gr["nivel"]]
        poli = Image.new("L", (w, h), 0)
        dp = ImageDraw.Draw(poli)
        for pol in gr["poligonos"]:
            pts = []
            for lo, la in pol:
                if es_canaria(la):
                    if not pr.muestra_canarias:
                        continue
                    lo, la = lonlat_mapa(lo, la, True)
                pts.append(pr(lo, la))
            if len(pts) >= 3:
                dp.polygon(pts, fill=255)
        pm = np.array(poli) > 0
        if not pm.any():
            continue
        if "coster" in gr["fenomeno"].lower():
            cerca = np.array(poli.filter(ImageFilter.MaxFilter(31))) > 0
            linea = Image.fromarray(((costa & cerca) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
            m = np.array(linea) > 0
            if m.any():
                out[m] = col + (235,)
                vistos.append(gr)
        else:
            dentro = lab[pm]
            dentro = dentro[dentro > 0]
            if dentro.size == 0:
                continue
            idx, cuenta = np.unique(dentro, return_counts=True)
            pintada = False
            for i, c in zip(idx, cuenta):
                total = (lab == i).sum()
                if c >= 0.25 * dentro.size or c >= 0.15 * total:     # la provincia está afectada de verdad
                    out[lab == i] = col + (alfa,)
                    pintada = True
            if pintada:
                vistos.append(gr)
    return Image.fromarray(out, "RGBA"), vistos


def capa_avisos_suave(grupos):
    """Zonas con aviso (amarillo, naranja o rojo) coloreadas suavemente bajo las tarjetas del parte, con leyenda."""
    cache = {}

    def dibujar(capa, pr, dt):
        aparece = min(1.0, max(0.0, dt / 0.6))
        clave = (tuple(pr.vista), pr.ancho, pr.alto)
        if clave not in cache:
            img, vis = pintar_avisos(grupos, pr)
            full = Image.new("RGBA", capa.size, (0, 0, 0, 0)); full.alpha_composite(img, (0, MAPA_Y0))
            cache[clave] = (full, vis)
        lay, vistos = cache[clave]
        if aparece < 1:
            lay = lay.copy(); lay.putalpha(lay.getchannel("A").point(lambda a: int(a * aparece)))
        capa.alpha_composite(lay)
        d = ImageDraw.Draw(capa)
        y = MAPA_Y0 + MAPA_H - 80            # leyenda abajo a la izquierda
        for gr in list(dict.fromkeys((x["nivel"], nombre_fen(x["fenomeno"])) for x in reversed(vistos)))[:3]:
            nivel, fen = gr
            txt = f"AVISO {nivel.upper()} · {fen.upper()}"
            f = fuente("Black", 30)
            w = f.getlength(txt) + 44
            col = COLOR_NIVEL[nivel]
            d.rounded_rectangle([30, y, 30 + w, y + 50], radius=25, fill=col + (int(235 * aparece),))
            d.text((30 + w / 2, y + 25), txt, font=f, fill=(15, 25, 50) if nivel == "amarillo" else (255, 255, 255),
                   anchor="mm")
            y -= 60
    return dibujar


def nieblas_de(grupos) -> list[dict]:
    """Puntos (centro de cada zona) de los avisos por niebla, con la visibilidad si AEMET la da."""
    out = []
    for gr in grupos or []:
        if "niebla" not in gr["fenomeno"].lower():
            continue
        m = re.search(r"visibilidad[^0-9]{0,30}(\d+)\s*m", " ".join(gr.get("descripciones") or [gr.get("descripcion") or ""]).lower())
        for pol in gr.get("poligonos") or []:
            if len(pol) >= 3:
                out.append({"lon": sum(p[0] for p in pol) / len(pol), "lat": sum(p[1] for p in pol) / len(pol),
                            "vis": int(m.group(1)) if m else None, "nivel": gr["nivel"]})
    return out[:4]


def capa_mar_nieve(olas: list[dict], nieves: list[dict], nieblas: list[dict] | None = None):
    """Altura de las olas en el mar (insignia azul con ola) y cota de nieve en la montaña (copo con la cota)."""
    nieves = sorted(nieves, key=lambda e: (-e["cm"], e["cota"]))[:5]   # solo las principales
    olas = sorted(olas, key=lambda o: -o["olas"])[:5]
    def ola_icono(d, x, y, w=34, col=(255, 255, 255), fase=0.0):
        """Dos olas que avanzan (la fase corre con el tiempo)."""
        for k in range(2):
            pts = [(x + i, y + k * 11 + 4 * math.sin(i / w * 2 * math.pi * 1.5 - fase * 5 - k * 1.2))
                   for i in range(0, w + 1, 2)]
            d.line(pts, fill=col, width=4)

    def copo(d, x, y, r=17, col=(70, 140, 230), giro=0.0):
        """Copo que gira despacio."""
        for k in range(6):
            a = k * math.pi / 3 + giro
            x1, y1 = x + math.cos(a) * r, y + math.sin(a) * r
            d.line([(x, y), (x1, y1)], fill=col, width=4)
            bx, by = x + math.cos(a) * r * .55, y + math.sin(a) * r * .55
            for da in (.7, -.7):
                d.line([(bx, by), (bx + math.cos(a + da) * r * .35, by + math.sin(a + da) * r * .35)], fill=col, width=3)

    def bruma(d, x, y, w=40, fase=0.0, col=(255, 255, 255)):
        """Tres franjas de niebla que se deslizan a un lado y a otro."""
        for k in range(3):
            desp = math.sin(fase * 1.6 + k * 2.1) * 6
            y0 = y - 12 + k * 12
            x0, x1 = x + desp + (k % 2) * 5, x + w + desp - ((k + 1) % 2) * 6
            d.line([(x0, y0), (x1, y0)], fill=col + (int(255 - k * 40),), width=6)
            d.ellipse([x0 - 3, y0 - 3, x0 + 3, y0 + 3], fill=col + (int(255 - k * 40),))
            d.ellipse([x1 - 3, y0 - 3, x1 + 3, y0 + 3], fill=col + (int(255 - k * 40),))

    def libre(x, y, w, h, cajas, puestas, mar=None):
        """Mueve la insignia lo justo para no tapar tarjetas ni otras insignias (y que no se salga del mapa).
        Con `mar` (máscara de tierra): primero se busca un hueco cerca y entero sobre el mar; si no lo hay (costa
        pegada al borde del mapa), se admite que roce un poco la costa antes que llevársela lejos de su zona."""
        def tierra(cx, cy):
            if mar is None:
                return 0.0
            caja = mar.crop((int(cx - w / 2), int(cy - MAPA_Y0 - h / 2), int(cx + w / 2), int(cy - MAPA_Y0 + h / 2)))
            hist = caja.histogram()
            return 1 - hist[0] / max(1, sum(hist))

        def tapa(cx, cy):
            r = (cx - w / 2 - 6, cy - h / 2 - 6, cx + w / 2 + 6, cy + h / 2 + 6)
            return any(r[0] < b[2] and r[2] > b[0] and r[1] < b[3] and r[3] > b[1] for b in list(cajas) + puestas)

        for tolerancia, pasos in ((0.0, 8), (0.45, 8), (0.0, 11)):   # si no cabe en el mar cerca, no se pone
            for paso in range(0, pasos):
                for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                    cx, cy = x + dx * paso * 22, y + dy * paso * 22
                    if 4 + w / 2 < cx < ANCHO - 140 - w / 2 and MAPA_Y0 + h < cy < MAPA_Y0 + MAPA_H - h \
                            and not tapa(cx, cy) and tierra(cx, cy) <= tolerancia:
                        return cx, cy
                    if paso == 0:
                        break
        return None

    def dibujar(capa, pr, dt, cajas=()):
        from .mapa import es_canaria, lonlat_mapa, mascara_tierra
        d = ImageDraw.Draw(capa)
        s_ = min(1.0, max(0.0, (dt - 0.2) / 0.4))
        if s_ <= 0:
            return
        puestas = []
        for o in olas:
            lo, la = o["lon"], o["lat"]
            if es_canaria(la):
                if not pr.muestra_canarias:
                    continue
                lo, la = lonlat_mapa(lo, la, True)
            x, y = pr(lo, la); y += MAPA_Y0
            if not (60 < x < ANCHO - 60 and MAPA_Y0 + 30 < y < MAPA_Y0 + MAPA_H - 30):
                continue
            txt = f"{str(o['olas']).replace('.', ',')} m"
            f = fuente("Black", 34)
            w = f.getlength(txt) + 80
            pos = libre(x, y, w, 56, cajas, puestas, mar=mascara_tierra(pr))
            if not pos:
                continue
            x, y = pos
            puestas.append((x - w / 2, y - 28, x + w / 2, y + 28))
            col = (20, 90, 200) if o["olas"] < 5 else (200, 40, 60)
            d.rounded_rectangle([x - w / 2, y - 28, x + w / 2, y + 28], radius=28, fill=col + (int(240 * s_),),
                                outline=(255, 255, 255, int(230 * s_)), width=3)
            ola_icono(d, x - w / 2 + 14, y - 8, fase=dt)
            d.text((x - w / 2 + 58, y), txt, font=f, fill=(255, 255, 255, int(255 * s_)), anchor="lm")
        for nb in (nieblas or []):
            lo, la = nb["lon"], nb["lat"]
            if es_canaria(la):
                if not pr.muestra_canarias:
                    continue
                lo, la = lonlat_mapa(lo, la, True)
            x, y = pr(lo, la); y += MAPA_Y0
            if not (40 < x < ANCHO - 40 and MAPA_Y0 + 20 < y < MAPA_Y0 + MAPA_H - 20):
                continue
            l1 = "NIEBLA"
            l2 = f"visib. {nb['vis']} m" if nb.get("vis") else ""
            f1, f2 = fuente("Black", 30), fuente("ExtraBold", 22)
            w = max(f1.getlength(l1), f2.getlength(l2) if l2 else 0) + 84
            hh = 64 if l2 else 52
            pos = libre(x, y, w, hh, cajas, puestas)
            if not pos:
                continue
            x, y = pos
            puestas.append((x - w / 2, y - hh / 2, x + w / 2, y + hh / 2))
            d.rounded_rectangle([x - w / 2, y - hh / 2, x + w / 2, y + hh / 2], radius=hh / 2,
                                fill=(120, 132, 150, int(240 * s_)), outline=(255, 255, 255, int(220 * s_)), width=3)
            bruma(d, x - w / 2 + 14, y, fase=dt)
            d.text((x - w / 2 + 66, y - (8 if l2 else 0)), l1, font=f1, fill=(255, 255, 255, int(255 * s_)), anchor="lm")
            if l2:
                d.text((x - w / 2 + 66, y + 17), l2, font=f2, fill=(225, 232, 245, int(255 * s_)), anchor="lm")
        for n in nieves:
            x, y = pr(n["lon"], n["lat"]); y += MAPA_Y0
            if not (60 < x < ANCHO - 60 and MAPA_Y0 + 30 < y < MAPA_Y0 + MAPA_H - 30):
                continue
            l1, l2 = f"{n['cota']:,} m".replace(",", "."), f"{n['cm']} cm"
            f1, f2 = fuente("Black", 32), fuente("ExtraBold", 24)
            w = max(f1.getlength(l1), f2.getlength(l2)) + 74
            pos = libre(x, y, w, 68, cajas, puestas)
            if not pos:
                continue
            x, y = pos
            puestas.append((x - w / 2, y - 34, x + w / 2, y + 34))
            d.rounded_rectangle([x - w / 2, y - 34, x + w / 2, y + 34], radius=18, fill=(255, 255, 255, int(245 * s_)),
                                outline=(70, 140, 230, int(255 * s_)), width=4)
            copo(d, x - w / 2 + 30, y, giro=dt * 0.9)
            for k in range(3):   # copitos que caen junto a la insignia
                u = (dt * 0.6 + k / 3) % 1
                fx, fy = x - w / 2 + 12 + k * 14, y + 36 + u * 28
                d.ellipse([fx - 3, fy - 3, fx + 3, fy + 3], fill=(255, 255, 255, int(220 * (1 - u) * s_)))
            d.text((x - w / 2 + 56, y - 9), l1, font=f1, fill=(20, 40, 90, int(255 * s_)), anchor="lm")
            d.text((x - w / 2 + 56, y + 18), l2, font=f2, fill=(70, 120, 200, int(255 * s_)), anchor="lm")
    return dibujar


def combinar(*funcs):
    funcs = [f for f in funcs if f]
    if not funcs:
        return None
    def dibujar(capa, pr, dt):
        for f in funcs:
            f(capa, pr, dt)
    return dibujar


def nombre_fen(f: str) -> str:
    from .gancho import nombre_fenomeno
    return nombre_fenomeno(f)


def avisos_por_dia(dias: dict) -> dict:
    """{clave_día: grupos de avisos de AEMET (todos los niveles) que afectan a ese día} para semanales y finde."""
    clave = os.environ.get("AEMET_API_KEY", "").strip()
    if not clave:
        return {}
    try:
        avisos = descargar_avisos(clave)
    except Exception as e:  # noqa: BLE001
        log.warning("Avisos para el vídeo semanal: %s", e)
        return {}
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Madrid")
    out = {}
    for k, d in dias.items():
        ini_d = datetime(d.year, d.month, d.day, tzinfo=tz); fin_d = ini_d + timedelta(days=1)
        vig = []
        for a in avisos:
            try:
                ini, fin = datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"])
            except (TypeError, ValueError):
                continue
            if fin > ini_d and ini < fin_d:
                vig.append(a)
        if vig:
            out[k] = agrupar(vig)
    return out


def texto_avisos(por_dia: dict) -> str:
    """Resumen de los avisos previstos para el prompt (con el dato: litros, km/h, altura de las olas…)."""
    partes = []
    for k, grupos in por_dia.items():
        for gr in sorted(grupos, key=lambda x: -NIVELES[x["nivel"]])[:4]:
            zonas = ", ".join(z.split(" - ")[-1] for z in gr["zonas"][:3])
            dato = dato_aviso(gr)
            partes.append(f"{k}: aviso {gr['nivel']} por {nombre_fen(gr['fenomeno'])} en {zonas}"
                          + (f" ({dato.lower()})" if dato else ""))
    if not partes:
        return ""
    return ("\n\nAVISOS DE AEMET PREVISTOS (se ven coloreados en el mapa de su día): " + "; ".join(partes)
            + ". Menciónalos en el bloque de su día: los naranjas y rojos, siempre; los amarillos, de pasada. Si hay "
              "oleaje o temporal en el mar, di la altura de las olas.")


PROMPT_AVISO = """Eres el guionista de "Paraguas o Chanclas", canal de TikTok del tiempo en España. Es un vídeo
FLASH de 25 segundos por avisos de AEMET: solo para llamar la atención sobre lo urgente. Sin humor, tono directo y
claro, con urgencia pero sin sensacionalismo. Usa SOLO estos datos oficiales de AEMET (no inventes cifras, zonas, horas
ni daños). Lo lee {presenta} con voz sintética.

Hoy es {fecha}. Avisos vigentes o para las próximas horas:
{avisos}

Bloques (palabras aproximadas: {palabras}; total ≈ {total}; es crucial no pasarse):
- intro: la PRIMERA FRASE (máx. 8 palabras) es el titular de última hora: {titular} + nivel + fenómeno ("Atención
  Valencia: aviso rojo por lluvias torrenciales.", "Aviso naranja en la Región de Murcia."). Si es una comunidad, NO
  abras con pueblos o ciudades pequeñas (Lorca, Mazarrón…): esos van en "zonas". Luego, en una frase, lo más grave que se espera.
- zonas: dónde y cuándo, muy resumido (las zonas principales y desde qué hora; horas en palabras).
- consejos: los dos consejos más importantes de la "instrucción" de AEMET + "y si hay una emergencia, llama al 112".
- cierre: una sola frase: "Compártelo con quien viva allí." (puedes variarla un poco).
Frases cortas y directas, de tú; números en cifras con "grados", "por ciento", "litros", "kilómetros por hora".
Nombres de fenómeno naturales: "oleaje" (no "costeros"), "viento", "lluvias", "tormentas", "nieve", "calor".

"titular": 2 a 5 palabras en MAYÚSCULAS, máx. 26 caracteres, con la ciudad (ej. "VALENCIA: AVISO ROJO").
"consejos_pantalla": 3 consejos MUY cortos (máx. 26 caracteres cada uno) para la pantalla.
"caption": una frase (máx. 90 caracteres) con 1 emoji ⚠️, sin hashtags.

Responde SOLO con JSON: {{"segmentos": {{"intro": "...", "zonas": "...", "consejos": "...", "cierre": "..."}},
"titular": "...", "consejos_pantalla": ["...", "...", "..."], "caption": "..."}}"""
PALABRAS_AVISO = {"intro": 20, "zonas": 20, "consejos": 18, "cierre": 6}
DURACION_AVISO = (20.0, 30.0, 25.0)
CONSEJOS_BASE = {"lluvias": ["EVITA ZONAS INUNDABLES", "NO CRUCES CAUCES", "LLAMA AL 112"],
                 "tormentas": ["RESGUÁRDATE BAJO TECHO", "LEJOS DE ÁRBOLES", "LLAMA AL 112"],
                 "vientos": ["CUIDADO CON OBJETOS", "EVITA PARQUES", "LLAMA AL 112"],
                 "costeros": ["LEJOS DE LA COSTA", "NO TE ACERQUES A DIQUES", "LLAMA AL 112"],
                 "temperaturas máximas": ["BEBE AGUA", "EVITA EL SOL", "CUIDA A LOS MAYORES"],
                 "nevadas": ["EVITA CARRETERA", "CADENAS Y DEPÓSITO", "LLAMA AL 112"]}


def dato_aviso(gr) -> str:
    """El número clave del aviso para la portada, sacado del texto oficial de AEMET (el máximo de todas las zonas):
    '40 L/M² EN 1 HORA', 'RACHAS DE 100 KM/H', '20 CM DE NIEVE', 'HASTA 42 °C', 'OLAS DE 7 METROS'."""
    t = " ".join(gr.get("descripciones") or [gr.get("descripcion") or ""]).lower()
    fen = gr.get("fenomeno", "").lower()
    nums = lambda pat: [int(x) for x in re.findall(pat, t)]
    if "lluvia" in fen or "tormenta" in fen:
        # "Precipitación acumulada en una hora: 20 mm. Precipitación acumulada en 12 horas: 60 mm" → cada cifra con
        # SUS horas; se prefiere la intensidad en una hora (lo más llamativo y lo que pide la gente)
        pares = [(1 if hh == "una" else int(hh), int(v))
                 for hh, v in re.findall(r"en (una|\d+) horas?[^0-9]{0,40}?(\d+)\s*mm", t)]
        if pares:
            una = [v for hh, v in pares if hh == 1]
            horas, v = (1, max(una)) if una else max(pares, key=lambda p: p[1])
            return f"{v} L/M² EN {horas} HORA{'S' if horas > 1 else ''}"
        mm = nums(r"(\d+)\s*mm")
        if mm:
            return f"{max(mm)} L/M²"
    if "viento" in fen or "tormenta" in fen:
        kmh = nums(r"(\d+)\s*km/h")
        if kmh:
            return f"RACHAS DE {max(kmh)} KM/H"
    if "nev" in fen or "nieve" in fen:
        cm = nums(r"(\d+)\s*cm")
        if cm:
            return f"{max(cm)} CM DE NIEVE"
    if "temperatura" in fen:
        g_ = [int(x) for x in re.findall(r"(-?\d+)\s*[º°]\s*c", t)]
        if g_:
            return f"HASTA {max(g_)} °C" if "máxima" in fen else f"MÍNIMAS DE {min(g_)} °C"
    if "coster" in fen:
        olas = nums(r"(\d+)\s*(?:m\b|metros)")
        if olas:
            return f"OLAS DE {max(olas)} METROS"
    return ""


def _ciudades_portada(gr) -> list[str]:
    """Primera línea grande: la ciudad si es muy grande o la comunidad; segunda: las ciudades afectadas."""
    cs = gr.get("ciudades") or [x.split(" - ")[-1] for x in gr["zonas"]]
    tit = titular_aviso(cs)
    if tit in cs:
        return [tit] + [c for c in cs if c != tit]
    return [tit, " · ".join(cs[:3])]


def _ciudades_portada_todos(grupos) -> list[str]:
    """Rojo: el sitio concreto. Naranja con varias comunidades: todas (hasta 3) en grande y sus ciudades debajo."""
    gr = grupos[0]
    if gr["nivel"] == "rojo":   # rojo: el sitio concreto, en grande
        cs = list(dict.fromkeys(c for x in grupos for c in (x.get("ciudades") or []))) or \
            [z.split(" - ")[-1] for z in gr["zonas"]]
        prim = titular_avisos(cs, "rojo")
        resto = [c for c in cs if c not in prim]
        return [prim] + ([" · ".join(resto[:3])] if resto else [])
    if len(grupos) == 1 and len(gr.get("ciudades") or []) <= 1:
        return _ciudades_portada(gr)
    cs = list(dict.fromkeys(c for x in grupos for c in (x.get("ciudades") or [])))
    tit = titular_avisos(cs, gr["nivel"])
    if tit in cs:
        return [tit] + [c for c in cs if c != tit][:2]
    return [tit, " · ".join(cs[:3])]


def _cuando_portada(gr, hoy: date) -> str:
    """'ESTA NOCHE DESDE LAS 22:00', 'HOY HASTA LAS 18:00', 'MAÑANA DESDE LAS 06:00'…"""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Madrid")
        ini, fin = datetime.fromisoformat(gr["inicio"]).astimezone(tz), datetime.fromisoformat(gr["fin"]).astimezone(tz)
    except Exception:  # noqa: BLE001
        return ""
    if ini <= datetime.now(tz):
        return f"EN CURSO HASTA LAS {fin:%H:%M}" if fin.date() == hoy else f"EN CURSO HASTA EL {g.DIAS[fin.weekday()]}"
    dia = "HOY" if ini.date() == hoy else "MAÑANA" if ini.date() == hoy + timedelta(days=1) else g.DIAS[ini.weekday()]
    if dia == "HOY" and ini.hour >= 20:
        dia = "ESTA NOCHE"
    return f"{dia} DESDE LAS {ini:%H:%M}"


def _hora_txt(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{g.DIAS[d.weekday()]} {d.day} a las {d:%H:%M}"


def guion_aviso(grupos, hoy: date, factor: float, presenta: str, plantilla: bool) -> dict:
    orden = ["intro", "zonas", "consejos", "cierre"]
    palabras = {k: max(8, round(v * factor)) for k, v in PALABRAS_AVISO.items()}
    datos = [{"nivel": gr["nivel"], "fenomeno": gr["fenomeno"], "zonas": gr["zonas"][:12],
              "grandes_ciudades_afectadas": gr.get("ciudades", [])[:8],
              "desde": _hora_txt(gr["inicio"]), "hasta": _hora_txt(gr["fin"]), "descripcion": gr["descripcion"],
              "instruccion": gr["instruccion"]} for gr in grupos[:4]]
    if not plantilla:
        try:
            gg = _claude_json(None, None, PROMPT_AVISO.format(titular=titular_avisos(
                                  [c for gr in grupos for c in gr.get("ciudades", [])], grupos[0]["nivel"]) or "CIUDAD", presenta=presenta, fecha=g.fecha_larga(hoy),
                                                  avisos=json.dumps(datos, ensure_ascii=False, indent=1),
                                                  palabras=json.dumps(palabras), total=sum(palabras.values())))
            if all(gg["segmentos"].get(s) for s in orden):
                gg.update(origen="claude", orden=orden)
                return gg
        except Exception as e:  # noqa: BLE001
            log.warning("Guion del aviso con Claude falló: %s", e)
    if not plantilla and not os.environ.get("PERMITIR_PLANTILLA"):
        raise RuntimeError("Sin guion escrito ni API: no se publica la plantilla básica")
    gr = grupos[0]
    zonas = ", ".join(z.split(" - ")[-1] for z in gr["zonas"][:4])
    from .gancho import nombre_fenomeno
    fen = nombre_fenomeno(gr["fenomeno"])
    seg = {
        "intro": f"Atención: aviso {gr['nivel']} de AEMET por {fen}.",
        "zonas": f"Afecta a {zonas}, desde el {_hora_txt(gr['inicio'])}.",
        "consejos": "Extrema la precaución y, si hay una emergencia, llama al 112.",
        "cierre": "Compártelo con quien viva allí.",
    }
    return {"segmentos": seg, "orden": orden, "titular": f"AVISO {gr['nivel'].upper()}",
            "caption": f"⚠️ Aviso {gr['nivel']} por {gr['fenomeno']}: lo que tienes que saber",
            "consejos_pantalla": CONSEJOS_BASE.get(gr["fenomeno"], ["SIGUE A AEMET", "PRECAUCIÓN", "LLAMA AL 112"]),
            "origen": "plantilla"}


def caption_aviso(grupos, gancho) -> str:
    lineas = []
    for gr in grupos[:4]:
        from .gancho import nombre_fenomeno
        sitios = gr.get("ciudades") or [z.split(" - ")[-1] for z in gr["zonas"]]
        icono = {"rojo": "🔴", "naranja": "🟠"}.get(gr["nivel"], "🟡")
        lineas.append(f"{icono} Aviso {gr['nivel']} por {nombre_fenomeno(gr['fenomeno'])}: {', '.join(sitios[:4])}"
                      + (" y más" if len(sitios) > 4 else ""))
    lineas += ["ℹ️ Fuente: AEMET. Sigue las indicaciones de Protección Civil. Emergencias: 112."]
    tags = ["#aviso", "#AEMET", "#eltiempo", "#paraguasochanclas"]
    for gr in grupos[:1]:
        for c in (gr.get("ciudades") or [])[:1]:
            tags.append("#" + re.sub(r"\W", "", c.split()[0]))
    return (f"{(gancho or '⚠️ Aviso de AEMET: lo que tienes que saber').strip()}\n\n" + "\n".join(lineas)
            + "\n\n" + " ".join(dict.fromkeys(tags)))[:2200]


def _gancho_aviso(grupos) -> dict:
    from .config import CIUDADES
    from .gancho import fenomeno_del_dia
    prev = [{**c, "tmax": 0, "tmin": 0, "lluvia": 0, "icono": "nubes", "racha": None} for c in CIUDADES]
    return fenomeno_del_dia(prev, grupos)


def video_aviso(grupos, hoy: date, salida: Path, demo: bool = False, sufijo: str = "") -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "trabajo"
    trabajo.mkdir(exist_ok=True)
    tipo_voz = os.environ.get("VOZ_TIPO") or "masculina"   # vídeos importantes: voz masculina
    global VOZ_USADA
    VOZ_USADA = tipo_voz
    voz.elegir_voz(VOCES[tipo_voz])
    with duracion(*DURACION_AVISO):  # vídeo flash de 20-30 s
        guion, plan, total, trozos, motor = locutar(
            lambda f, pl: guion_aviso(grupos, hoy, f, VOCES[tipo_voz]["presenta"], pl), trabajo, tipo_voz, demo)
    zona = _vista_zonas(grupos)
    consejos = [c.upper()[:28] for c in (guion.get("consejos_pantalla") or [])][:3] or \
        CONSEJOS_BASE.get(grupos[0]["fenomeno"], ["SIGUE A AEMET", "PRECAUCIÓN", "LLAMA AL 112"])
    gr = grupos[0]
    kwargs = {
        "vistas": {"intro": zona, "zonas": zona, "consejos": zona, "cierre": zona},
        "sin_marcadores": ("intro", "zonas", "consejos", "cierre"),
        "pills": {"zonas": "ZONAS Y HORAS", "consejos": "QUÉ HACER", "cierre": "COMPÁRTELO",
                  "promesa": "COMPÁRTELO CON QUIEN VIVA ALLÍ", "cierre_1": "COMPÁRTELO",
                  "cierre_2": "con quien viva en esas zonas", "cierre_3": "Sígueme · avisos al momento"},
        "capas": {"intro": _capa_poligonos(grupos), "zonas": _capa_poligonos(grupos, con_lista=True),
                  "consejos": _capa_poligonos(grupos, consejos=consejos), "cierre": _capa_poligonos(grupos)},
        "gancho": _gancho_aviso(grupos),
        "aviso_portada": {"nivel": gr["nivel"],
                          "fenomeno": " y ".join(dict.fromkeys("oleaje" if "costeros" in x["fenomeno"] else x["fenomeno"]
                                                               for x in grupos)) if gr["nivel"] == "naranja"
                          else ("oleaje" if "costeros" in gr["fenomeno"] else gr["fenomeno"]),
                          "icono": _gancho_aviso(grupos).get("icono"),
                          "ciudades": _ciudades_portada_todos(grupos),
                          "cuando": _cuando_portada(gr, hoy), "dato": dato_aviso(gr),
                          "variante": len(list(HISTORIAL.glob("aviso-*.json")))},
        "portada_txt": ("AVISO DE AEMET", f"AVISO {gr['nivel'].upper()}", gr["fenomeno"].upper(),
                        tuple((z.upper()[:30], COLOR_NIVEL.get(gr["nivel"], (255, 205, 40)))
                              for z in (gr.get("ciudades") or [x.split(" - ")[-1] for x in gr["zonas"]])[:2])),
    }
    with duracion(*DURACION_AVISO):
        video = _producir(f"aviso_{hoy.isoformat()}" + (f"_{sufijo}" if sufijo else ""), guion, plan, total, trozos, kwargs, [], None,
                          g.fecha_larga(hoy).upper(), salida, trabajo)
    caption = caption_aviso(grupos, guion.get("caption") if guion.get("origen") == "claude" else None)
    return {"tipo": "aviso", "fecha": hoy.isoformat(), "video": str(video), "caption": caption,
            "titular": guion.get("titular"), "motor_voz": motor, "origen_guion": guion.get("origen"),
            "duracion": round(voz.duracion(video), 2), "firma": firma(grupos), "guion": guion["segmentos"],
            "nivel_max": max(NIVELES[x["nivel"]] for x in grupos),
            "avisos": [cumplido.resumen_aviso(x) for x in grupos]}


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
            meta["primer_comentario"] = None if meta.get("tipo") == "aviso" else uploadpost.comentario_pueblo(hoy)
            meta["tiktok"] = uploadpost.publicar_tiktok(Path(meta["video"]), meta["caption"], "tiempo",
                                                        primer_comentario=meta["primer_comentario"])
            hecho = True
        except Exception as e:  # noqa: BLE001
            log.error("Upload-Post falló (%s): borrador", e)
    if not hecho and not hay_credenciales():
        meta["tiktok"] = publicar_con_reintentos(Path(meta["video"]), meta["caption"], 0)
    meta["tipo_youtube"] = {"semana": "semana", "resto": "semana", "finde": "finde"}.get(meta.get("tipo"), "aviso")
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
    ap.add_argument("tipo", choices=["finde", "avisos", "semana", "resto"])
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
    elif a.tipo in ("semana", "resto"):
        global MODO_SEMANA
        MODO_SEMANA = a.tipo
        hist = HISTORIAL / f"{a.tipo}-{hoy.isoformat()}.json"
        if hist.exists() and not a.demo:
            log.info("El vídeo de %s ya está hecho", a.tipo)
            return
        with duracion(*DURACION_SEMANA):  # el vídeo estrella: más largo (y hace de parte de mañana)
            meta = la_semana(hoy, Path(a.salida), a.demo)
        titulo = "La semana que viene" if a.tipo == "semana" else "Lo que queda de semana"
    else:
        if a.demo:
            grupos = avisos_demo()
        else:
            clave = os.environ.get("AEMET_API_KEY", "")
            grupos = agrupar(avisos_relevantes(descargar_avisos(clave), datetime.now().astimezone()))
        if not grupos:
            log.info("No hay avisos naranjas ni rojos en poblaciones de más de 100.000 habitantes")
            return
        # Un vídeo por nivel y día: uno con todos los rojos y otro con todos los naranjas
        for nivel in ("rojo", "naranja"):
            del_nivel = [x for x in grupos if x["nivel"] == nivel]
            if not del_nivel:
                continue
            hist_n = HISTORIAL / f"aviso-{hoy.isoformat()}-{nivel}.json"
            if hist_n.exists() and not a.demo:
                log.info("El vídeo de avisos %ss de hoy ya está publicado", nivel)
                continue
            if not a.demo and _repetido(del_nivel, hoy, nivel):
                log.info("Aviso %s ya contado ayer (mismo fenómeno y zona): no se repite el vídeo", nivel)
                continue
            meta = video_aviso(del_nivel, hoy, Path(a.salida), a.demo, sufijo=nivel)
            _cerrar(meta, f"Aviso {nivel}", hist_n, a, hoy)
        return

    _cerrar(meta, titulo, hist, a, hoy)


def _repetido(grupos, hoy: date, nivel: str) -> bool:
    """True si ayer ya se publicó un vídeo del mismo nivel, fenómeno y zona (el 4/11/2026 el segundo aviso seguido
    de Cartagena se quedó en 283 visualizaciones: la gente ya lo había visto). Un rojo nuevo sí sale siempre."""
    ruta = HISTORIAL / f"aviso-{(hoy - timedelta(days=1)).isoformat()}-{nivel}.json"
    try:
        ayer = json.loads(ruta.read_text(encoding="utf-8")).get("avisos") or []
    except Exception:  # noqa: BLE001
        return False
    if nivel == "rojo" or not ayer:
        return False
    vistos = {(x["fenomeno"], c) for x in ayer for c in (x.get("ciudades") or [])}
    return all(gr.get("ciudades") and all((gr["fenomeno"], c) in vistos for c in gr["ciudades"]) for gr in grupos)


def _cerrar(meta: dict, titulo: str, hist: Path, a, hoy: date):
    log.info("Especial listo: %s (%.2f s, voz %s, guion %s)", meta["video"], meta["duracion"], meta["motor_voz"],
             meta["origen_guion"])
    (Path(a.salida) / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.demo:
        return
    _guardar_texto(meta, titulo)
    if a.publicar:
        if a.esperar and a.tipo in ("finde", "semana", "resto"):
            from .horario import TZ
            import time as _t
            h, m = 20, 26   # viernes, domingo y miércoles no hay parte: el especial lo sustituye
            objetivo = ahora().replace(hour=h, minute=m, second=0, microsecond=0)
            falta = (objetivo - ahora()).total_seconds()
            if 0 < falta < 4 * 3600:
                log.info("Esperando %.0f min hasta la hora de publicación", falta / 60)
                _t.sleep(falta)
        _publicar(meta, hoy)
        if VOZ_USADA:
            from .config import registrar_voz
            registrar_voz(VOZ_USADA, hoy)
    meta.setdefault("voz", VOZ_USADA)
    hist.write_text(json.dumps({k: v for k, v in meta.items() if k != "video"}, ensure_ascii=False, indent=1),
                    encoding="utf-8")


if __name__ == "__main__":
    main()
