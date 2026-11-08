"""Vídeos especiales de Paraguas o Chanclas.

- Fin de semana (viernes por la tarde): ¿playa, monte o sofá? Previsión del sábado y del domingo.
- Avisos de AEMET: cuando hay avisos naranjas o rojos (DANA, temporal, calor extremo…), un vídeo especial.

  python -m tiempo.especiales finde [--publicar] [--esperar] [--demo] [--fecha AAAA-MM-DD]
  python -m tiempo.especiales avisos [--publicar] [--demo]

Llegan como borrador a TikTok (igual que el parte) y se suben a YouTube Shorts.
"""
from __future__ import annotations

from . import promesas as _prom

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


DURACION_SEMANA = (85.0, 100.0, 91.0)
DURACION_FINDE = (66.0, 85.0, 75.0)   # el finde lleva dos días (y a veces avisos): algo más de margen
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
            from .main import avisar_voz_gratuita
            avisar_voz_gratuita(str(e)[:200], f"Especial ({MODO_SEMANA if 'MODO_SEMANA' in globals() else 'especial'})")
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
- intro: gancho + promesa del final. {promesa}
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
    orden = ["intro"] + [x for d in ("sabado", "domingo") for x in ([f"avisos_{d}"] if d in AVISOS_BLOQUE else []) + [d]] \
        + ["general", "cierre"]
    base = dict(PALABRAS_FINDE)
    for d in AVISOS_BLOQUE:
        base[f"avisos_{d}"] = 20
        base[d] = max(16, base[d] - 14)
    palabras = {k: max(8, round(v * factor)) for k, v in base.items()}
    if not plantilla:
        try:
            gg = _claude_json(f"finde-{ahora().date().isoformat()}", "19:50", PROMPT_FINDE.format(promesa=_prom.nota("finde", ahora().date()), presenta=presenta, sab=g.fecha_larga(sab), dom=g.fecha_larga(dom),
                                                  datos_sab=json.dumps(_resumen(prev_s), ensure_ascii=False),
                                                  datos_dom=json.dumps(_resumen(prev_d), ensure_ascii=False),
                                                  palabras=json.dumps(palabras), total=sum(palabras.values()),
                                                  fiestas=(" ".join(notas_rango(sab, dom)) or "(ninguno)") + _dato_real(),
                                                  extra=json.dumps(_extra_por_region(), ensure_ascii=False)))
            orden = _sin_bloques_vacios(orden, gg)
            if all(gg["segmentos"].get(s) for s in orden):
                gg.update(origen="claude", orden=orden)
                _completar_sitios(gg, grupos)
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
        PREVS_DIA.clear(); PREVS_DIA.update({"sabado": prev_s, "domingo": prev_d})
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
    PREVS_DIA.clear(); PREVS_DIA.update({"sabado": prev_s, "domingo": prev_d})
    (ms, _), _ = _mejor_plan(prev_s, prev_d)
    kwargs = {
        "datos_seg": {"sabado": g.prev_para_mapa(prev_s, [guion["segmentos"].get("sabado", "")], EXTRA_SEMANA),
                      "domingo": prev_d, "intro": []},
        "capas_fondo": _capas_dias(), "capas_encima": _capas_encima_dias(),
        "vistas": _kwargs_avisos({"sabado": f"SÁBADO {sab.day}", "domingo": f"DOMINGO {dom.day}"})["vistas"],
        "sin_marcadores": _kwargs_avisos({"sabado": "", "domingo": ""})["sin"],
        "pills": {**_kwargs_avisos({"sabado": f"SÁBADO {sab.day}", "domingo": f"DOMINGO {dom.day}"})["pills"],
                  "sabado": f"SÁBADO {sab.day}", "domingo": f"DOMINGO {dom.day}", "general": "EL MEJOR PLAN DEL FINDE",
                  "promesa": _prom.pill("finde", ahora().date())},
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
de temperaturas?, ¿semana de sol?) y promete que al final dirás cuál es el mejor día de la semana y cuál el peor. {promesa}
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
AVISOS_BLOQUE = []
MESES_LARGOS = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
                "NOVIEMBRE", "DICIEMBRE"]
COMUNIDAD_PROV = {
    "A Coruña": "Galicia", "Lugo": "Galicia", "Ourense": "Galicia", "Pontevedra": "Galicia", "Asturias": "Asturias",
    "Cantabria": "Cantabria", "Bizkaia/Vizcaya": "País Vasco", "Gipuzkoa/Guipúzcoa": "País Vasco",
    "Araba/Álava": "País Vasco", "Navarra": "Navarra", "La Rioja": "La Rioja", "Huesca": "Aragón", "Zaragoza": "Aragón",
    "Teruel": "Aragón", "Girona": "Cataluña", "Barcelona": "Cataluña", "Tarragona": "Cataluña", "Lleida": "Cataluña",
    "Castelló/Castellón": "C. Valenciana", "València/Valencia": "C. Valenciana", "Alacant/Alicante": "C. Valenciana",
    "Murcia": "Murcia", "Illes Balears": "Baleares", "Madrid": "Madrid", "León": "Castilla y León",
    "Palencia": "Castilla y León", "Burgos": "Castilla y León", "Soria": "Castilla y León", "Zamora": "Castilla y León",
    "Valladolid": "Castilla y León", "Segovia": "Castilla y León", "Ávila": "Castilla y León",
    "Salamanca": "Castilla y León", "Guadalajara": "Castilla-La Mancha", "Cuenca": "Castilla-La Mancha",
    "Toledo": "Castilla-La Mancha", "Ciudad Real": "Castilla-La Mancha", "Albacete": "Castilla-La Mancha",
    "Cáceres": "Extremadura", "Badajoz": "Extremadura", "Huelva": "Andalucía", "Sevilla": "Andalucía",
    "Cádiz": "Andalucía", "Málaga": "Andalucía", "Córdoba": "Andalucía", "Jaén": "Andalucía", "Granada": "Andalucía",
    "Almería": "Andalucía", "Las Palmas": "Canarias", "Santa Cruz De Tenerife": "Canarias", "Ceuta": "Ceuta",
    "Melilla": "Melilla"}
PREVS_DIA = {}       # previsión de cada día (para las heladas y rachas del bloque de avisos)   # días con bloque propio de avisos (mapa de España con avisos, olas, nieve y niebla)


def _merece_bloque(k) -> bool:
    gr = AVISOS_DIA.get(k) or []
    ol, ni = MAR_NIEVE.get(k, ([], []))
    # solo si hay algo reseñable: aviso naranja o rojo, mar fuerte o nieve importante (los amarillos sueltos, no)
    pd = PREVS_DIA.get(k) or []
    return (any(NIVELES[x["nivel"]] >= 2 for x in gr)
            or any(o["olas"] >= 4 for o in ol) or any(n["cota"] < 1000 or n["cm"] >= 10 for n in ni)
            or any(c["tmax"] >= 40 or c["tmin"] <= -7 or c.get("granizo") for c in pd))
MAR_NIEVE = {}   # {día: (olas, nieve)} para dibujarlos en el mapa de cada día


def _preparar_avisos(dias: dict):
    """Avisos (coloreados en el mapa de su día) y oleaje fuerte, para el prompt de los especiales."""
    from .fuentes import COSTA, oleaje, texto_oleaje
    AVISOS_DIA.clear()
    try:
        AVISOS_DIA.update(avisos_por_dia(dias))
    except Exception as e:  # noqa: BLE001
        log.warning("Avisos por día: %s", e)
    for k, pd in PREVS_DIA.items():   # icono de tormenta donde hay aviso por tormentas ese día
        marcar_tormentas(pd, AVISOS_DIA.get(k))
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
    AVISOS_BLOQUE[:] = [k for k in dias if _merece_bloque(k)]
    ext = []
    for k in dias:
        pd = PREVS_DIA.get(k) or []
        cal = [f"{c['nombre']} {c['tmax']}°" for c in sorted(pd, key=lambda c: -c["tmax"]) if c["tmax"] >= 38][:2]
        fri = [f"{c['nombre']} {c['tmin']}°" for c in sorted(pd, key=lambda c: c["tmin"]) if c["tmin"] <= -5][:2]
        gra = [c["nombre"] for c in pd if c.get("granizo")][:3]
        tor = [c["nombre"] for c in pd if c.get("icono") == "tormenta"][:3]
        partes = ([f"calor extremo ({', '.join(cal)})"] if cal else []) + ([f"frío extremo ({', '.join(fri)})"] if fri else []) \
            + ([f"posible granizo ({', '.join(gra)})"] if gra else []) + ([f"tormentas ({', '.join(tor)})"] if tor else [])
        if partes:
            ext.append(f"{k}: " + "; ".join(partes))
    AVISOS_TXT[0] = texto_avisos(AVISOS_DIA) + texto_oleaje(olas) + texto_nieve(nieves)
    graves_ = any(x["nivel"] in ("naranja", "rojo") for v in AVISOS_DIA.values() for x in v or [])
    AVISOS_TXT[0] += ("\n\nDURACIÓN: respeta las palabras de cada bloque (no te alargues"
                      + (": hay aviso naranja o rojo, así que el bloque de avisos puede ser algo más largo)." if graves_
                         else "; si sobra algo, recorta lo menos importante)."))
    if ext:
        AVISOS_TXT[0] += ("\n\nFENÓMENOS DESTACADOS (salen en el mapa con su icono animado): " + " | ".join(ext)
                          + ". Menciónalos en su día: el granizo y las tormentas con prudencia ('posibles'), el calor o "
                            "el frío extremos con la cifra y un consejo.")
    try:   # la capital más fría / calurosa de esos días y, además, el sitio más extremo (un pueblo)
        from . import pueblos
        cf_, cc_, pf_, pc_ = [], [], [], []
        for k, d in dias.items():
            caps = PREVS_DIA.get(k) or []
            if caps:
                x = min(caps, key=lambda c: c["tmin"]); cf_.append((x["tmin"], k, x["nombre"]))
                x = max(caps, key=lambda c: c["tmax"]); cc_.append((x["tmax"], k, x["nombre"]))
            pr = pueblos.previstos(d, aemet=False)
            if pr.get("frio"):
                pf_.append((pr["frio"]["tmin"], k, f"{pr['frio']['nombre']} ({pr['frio']['provincia']})"))
            if pr.get("calor"):
                pc_.append((pr["calor"]["tmax"], k, f"{pr['calor']['nombre']} ({pr['calor']['provincia']})"))
        if cf_ and cc_:
            vf, kf, nf = min(cf_); vc, kc, nc = max(cc_)
            frio = f"la capital más fría, {nf}, con {vf} grados el {kf}"
            if pf_ and min(pf_)[0] < vf:
                v, k, n = min(pf_); frio += f"; y el sitio más frío de España, {n}, con {v} grados el {k}"
            calor = f"la capital más calurosa, {nc}, con {vc} grados el {kc}"
            if pc_ and max(pc_)[0] > vc:
                v, k, n = max(pc_); calor += f"; y el sitio más caluroso de España, {n}, con {v} grados el {k}"
            AVISOS_TXT[0] += (f"\n\nLO MÁS FRÍO Y LO MÁS CALUROSO DE ESOS DÍAS (capitales y pueblos): FRÍO: {frio}. "
                              f"CALOR: {calor}. Cuando lo digas, di las dos cosas: la capital y, si lo hay, el pueblo "
                              "aún más extremo con su provincia, esté donde esté.")
    except Exception as e:  # noqa: BLE001
        log.warning("Pueblos extremos no disponibles: %s", e)
    if AVISOS_BLOQUE:
        AVISOS_TXT[0] += ("\n\nBLOQUES DE AVISOS: " + ", ".join(f'"avisos_{k}"' for k in AVISOS_BLOQUE)
                          + ". Cada uno va justo ANTES del bloque de su día, con un mapa de España con los avisos, las "
                            "olas, la nieve y la niebla: resume ahí en 1-2 frases lo importante de ese día (nivel, zona, "
                            "dato: litros, olas, cota). En el bloque del día ya NO lo repitas: habla de temperaturas, "
                            "lluvia y planes.")


def _capas_dias() -> dict:
    """Días con bloque de avisos: ahí, avisos a tope; en el bloque del día, solo un tono suave sin leyenda."""
    out = {}
    for k, v in AVISOS_DIA.items():
        if not v:
            continue
        if k in AVISOS_BLOQUE:
            out[f"avisos_{k}"] = capa_avisos_suave(v, alfa=160)
            out[k] = capa_avisos_suave(v, alfa=60, leyenda=False)
        else:
            out[k] = capa_avisos_suave(v)
    return out


def _capas_encima_dias() -> dict:
    out = {}
    for k in set(MAR_NIEVE) | set(AVISOS_DIA) | set(PREVS_DIA):
        ol, ni = MAR_NIEVE.get(k, ([], []))
        nb = nieblas_de(AVISOS_DIA.get(k))
        if k in AVISOS_BLOQUE:   # el bloque de avisos nunca vacío: fichas de cada aviso + heladas y rachas del día
            out[f"avisos_{k}"] = combinar_encima(capa_mar_nieve(ol, ni, nb) if (ol or ni or nb) else None,
                                                 capa_fichas(AVISOS_DIA.get(k), PREVS_DIA.get(k)))
        else:
            out_k = combinar_encima(capa_mar_nieve(ol, ni, nb) if (ol or ni or nb) else None,
                                    capa_tormentas(PREVS_DIA.get(k)))
            if out_k:
                out[k] = out_k
    return out


def _sin_bloques_vacios(orden, gg):
    """Si el guion no trae algún bloque de avisos, ese día va sin bloque (y sus avisos se ven en su mapa normal)."""
    faltan = [s_ for s_ in orden if s_.startswith("avisos_") and not (gg.get("segmentos") or {}).get(s_)]
    for s_ in faltan:
        k = s_[len("avisos_"):]
        if k in AVISOS_BLOQUE:
            AVISOS_BLOQUE.remove(k)
    return [s_ for s_ in orden if s_ not in faltan]


def _kwargs_avisos(fechas_dia: dict) -> dict:
    """Vista de España, sin tarjetas y con su etiqueta para cada bloque de avisos."""
    return {"vistas": {f"avisos_{k}": VISTA_GENERAL for k in AVISOS_BLOQUE},
            "sin": [f"avisos_{k}" for k in AVISOS_BLOQUE],
            "pills": {f"avisos_{k}": f"AVISOS · {fechas_dia[k]}" for k in AVISOS_BLOQUE}}


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
    orden = ["intro"] + [x for d in _dias() for x in ([f"avisos_{d}"] if d in AVISOS_BLOQUE else []) + [d]] \
        + ["general", "cierre"]
    # El primer día (mañana) hace de parte diario: bloque largo; los demás, más breves
    resto_dias = round(116 / (len(_dias()) - 1))   # ≈90 s en total: el vídeo estrella de la semana
    base = {"intro": 24, **{d: resto_dias for d in _dias()}, "general": 30, "cierre": 18}
    base[_dias()[0]] = 54
    for d in AVISOS_BLOQUE:   # lo de los avisos pasa del bloque del día a su bloque propio
        base[f"avisos_{d}"] = 20
        base[d] = max(16, base[d] - 14)
    palabras = {k: max(8, round(v * factor)) for k, v in base.items()}
    if not plantilla:
        try:
            datos = {f"{d} {fechas[d].day}": _resumen(prevs[d]) for d in _dias()}
            m = MODOS_SEMANA[MODO_SEMANA]
            gg = _claude_json(f"{MODO_SEMANA}-{ahora().date().isoformat()}", "19:50", PROMPT_SEMANA.format(promesa=_prom.nota("semana", ahora().date()), presenta=presenta, datos=json.dumps(datos, ensure_ascii=False),
                                                   palabras=json.dumps(palabras), total=sum(palabras.values()),
                                                   cuando=m["cuando"], rango_txt=m["rango_txt"],
                                                   claves_dias=", ".join(f'"{d}": "..."' for d in orden[1:-2]),
                                                   primero=f"{_hablado(_dias()[0])} {fechas[_dias()[0]].day}",
                                                   extra=json.dumps(_extra_por_region(), ensure_ascii=False),
                                                   fiestas=(" ".join(notas_rango(fechas[_dias()[0]], fechas[_dias()[-1]])) or "(ninguno)")
                                                   + _dato_real(),
                                                   repetidas=", ".join(g.ciudades_repetidas(fechas[_dias()[0]],
                                                                                            prevs[_dias()[0]]))
                                                   or "(ninguna)"))
            orden = _sin_bloques_vacios(orden, gg)
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
        PREVS_DIA.clear(); PREVS_DIA.update(prevs)
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
    PREVS_DIA.clear(); PREVS_DIA.update(prevs)
    primero = _dias()[0]
    mapa_dias = {d: prevs[d] for d in _dias()}
    mapa_dias[primero] = g.prev_para_mapa(prevs[primero], [guion["segmentos"].get(primero, "")], EXTRA_SEMANA)
    kwargs = {
        "satelite": sat,
        "capas_fondo": _capas_dias(), "capas_encima": _capas_encima_dias(),
        "datos_seg": {**mapa_dias, "intro": []},
        "vistas": _kwargs_avisos({d: "" for d in _dias()})["vistas"],
        "sin_marcadores": _kwargs_avisos({d: "" for d in _dias()})["sin"],
        "pills": {**_kwargs_avisos({d: f"{NOMBRE_DIA[d]} {fechas[d].day}" for d in _dias()})["pills"],
                  **{d: f"{NOMBRE_DIA[d]} {fechas[d].day}" for d in _dias()},
                  "general": "EL MEJOR Y EL PEOR DÍA", "cierre": "¡FELIZ SEMANA!" if MODO_SEMANA == "semana" else "¡BUEN FINDE!",
                  "promesa": _prom.pill("semana", ahora().date())},
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
                      (f"DEL {lun.day} AL {vie.day} DE {MESES_LARGOS[vie.month - 1]}" if lun.month == vie.month
                       else ("SEMANA " if MODO_SEMANA == "semana" else "HASTA EL DOMINGO ") + rango), salida, trabajo)
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
    # El mismo aviso (fenómeno y nivel) en otras zonas sin ciudades grandes también entra: si el naranja por lluvias
    # es en Tenerife, La Palma, La Gomera y El Hierro, el vídeo no puede hablar solo de Tenerife
    claves = {(a["fenomeno"], a["nivel"]) for a in out}
    ya = {id(a) for a in avisos if any(a.get("zona") == o.get("zona") and a["fenomeno"] == o["fenomeno"]
                                      and a["nivel"] == o["nivel"] for o in out)}
    for a in avisos:
        if id(a) in ya or (a["fenomeno"], a["nivel"]) not in claves:
            continue
        try:
            ini, fin = datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"])
        except (TypeError, ValueError):
            continue
        # las demás zonas con ese aviso en las próximas 24 h (el de Gran Canaria empezaba a las 12:00 y el vídeo de
        # la medianoche lo dejó fuera)
        if fin > momento and ini < momento + timedelta(hours=max(horas, 24)):
            out.append({**a, "ciudades": []})
    return out


AMARILLOS: list = []    # avisos amarillos del mismo fenómeno en la misma zona (Lanzarote y Fuerteventura, 8/11)
AMPLIACION: list = []   # sitios nuevos cuando AEMET amplía un aviso ya publicado hoy
ISLAS = ["Tenerife", "Gran Canaria", "Lanzarote", "Fuerteventura", "La Palma", "La Gomera", "El Hierro"]


def islas_de(zonas) -> list[str]:
    """Islas canarias que aparecen en los nombres de zona de AEMET («Este, sur y oeste de La Palma»...)."""
    t = " | ".join(zonas).lower()
    return [i for i in ISLAS if i.lower() in t or (i == "La Gomera" and "gomera" in t) or (i == "El Hierro" and "hierro" in t)]


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
        for isla in islas_de([a["zona"]]):   # en Canarias, las islas también cuentan como «sitios»
            if isla not in gr["ciudades"] and not (isla == "Tenerife" and any("Tenerife" in c for c in gr["ciudades"])) \
                    and not (isla == "Gran Canaria" and any("Gran Canaria" in c for c in gr["ciudades"])):
                gr["ciudades"].append(isla)
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


CAJA_ISLA = {"Tenerife": (-16.93, -16.12, 28.0, 28.59), "Gran Canaria": (-15.84, -15.36, 27.73, 28.18),
             "La Palma": (-18.01, -17.72, 28.45, 28.86), "La Gomera": (-17.35, -17.09, 28.01, 28.22),
             "El Hierro": (-18.17, -17.87, 27.63, 27.86), "Lanzarote": (-13.88, -13.41, 28.84, 29.24),
             "Fuerteventura": (-14.52, -13.82, 28.04, 28.76)}


def _encuadre(lo0, lo1, la0, la1, canaria, margen=(0.18, 0.14), minimo=(1.1, 0.8)):
    from .mapa import lonlat_mapa
    lo0, la0 = lonlat_mapa(lo0, la0, canaria)
    lo1, la1 = lonlat_mapa(lo1, la1, canaria)
    clon, clat = (lo0 + lo1) / 2, (la0 + la1) / 2
    dlon, dlat = max(lo1 - lo0 + 2 * margen[0], minimo[0]), max(la1 - la0 + 2 * margen[1], minimo[1])
    return (clon - dlon / 2, clon + dlon / 2, clat - dlat / 2, clat + dlat / 2)


def _zona_zoom(grupos):
    """Encuadre ajustado a la zona con aviso (también en Canarias, sobre su recuadro). En Canarias se usa la tierra de
    las islas afectadas: los polígonos de AEMET de costa se meten mucho en el mar y el zoom quedaba lejos."""
    pts = [p for gr in grupos for pol in gr["poligonos"] for p in pol]
    if not pts:
        return VISTA_GENERAL
    can = [la < 30 for _, la in pts]
    if any(can) and not all(can):
        return VISTA_GENERAL   # península y Canarias a la vez: el mapa entero
    if all(can):
        islas = islas_de([z for gr in grupos for z in gr["zonas"]]) or \
            [i for i, (a, b, c, d) in CAJA_ISLA.items() if any(a <= lo <= b and c <= la <= d for lo, la in pts)]
        cajas = [CAJA_ISLA[i] for i in islas if i in CAJA_ISLA]
        if cajas:
            return _encuadre(min(c[0] for c in cajas), max(c[1] for c in cajas), min(c[2] for c in cajas),
                             max(c[3] for c in cajas), True)
    return _encuadre(min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts),
                     max(p[1] for p in pts), False, margen=(0.25, 0.2), minimo=(1.8, 1.4))


def _zona_cerca(grupos, nucleos):
    """Segundo zoom, más cerca: los núcleos más poblados afectados (si la zona es grande)."""
    ancho = _zona_zoom(grupos)
    if ancho[1] - ancho[0] < 2.2 or len(nucleos) < 2:
        return ancho
    top = sorted(nucleos, key=lambda c: -c["poblacion"])[:3]
    can = top[0]["lat"] < 30
    top = [c for c in top if (c["lat"] < 30) == can]
    # que no se aleje demasiado: los que estén a menos de 1,6° del mayor
    top = [c for c in top if abs(c["lon"] - top[0]["lon"]) < 1.6 and abs(c["lat"] - top[0]["lat"]) < 1.2]
    return _encuadre(min(c["lon"] for c in top), max(c["lon"] for c in top), min(c["lat"] for c in top),
                     max(c["lat"] for c in top), can, margen=(0.35, 0.3), minimo=(1.2, 0.9))


def _dentro(x, y, pol) -> bool:
    dentro = False
    for (x1, y1), (x2, y2) in zip(pol, pol[1:] + pol[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            dentro = not dentro
    return dentro


def nucleos_afectados(grupos, n: int = 7) -> list[dict]:
    """Los núcleos de población más grandes dentro de las zonas con aviso (GeoNames)."""
    try:
        nucleos = json.loads((RAIZ / "assets" / "nucleos.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    pols = [pol for gr in grupos for pol in gr["poligonos"]]
    dentro = [(nombre, la, lo, pob, [i for i, pol in enumerate(pols) if _dentro(lo, la, pol)])
              for nombre, la, lo, pob in nucleos]   # ya vienen de más a menos habitantes
    dentro = [x for x in dentro if x[4]]
    out = []

    def poner(nombre, la, lo, pob):
        if any(o["nombre"] == nombre or math.hypot(la - o["lat"], (lo - o["lon"]) * math.cos(math.radians(la))) < 0.05
               for o in out):
            return   # «Realejo Alto» junto a «Los Realejos»: uno basta
        out.append({"nombre": nombre, "lat": la, "lon": lo, "poblacion": pob})

    # primero el más grande de cada zona (para que salga también San Sebastián de La Gomera), luego por tamaño
    for i in range(len(pols)):
        mayor = next((x for x in dentro if i in x[4]), None)
        if mayor:
            poner(*mayor[:4])
    out.sort(key=lambda o: -o["poblacion"])
    out = out[:n]
    for x in dentro:
        if len(out) >= n:
            break
        poner(*x[:4])
    return out


def _capa_nucleos(nucleos, color=(255, 255, 255)):
    """Puntos y nombres de los núcleos afectados, apareciendo uno tras otro tras el zoom."""
    from .video import TRANSICION
    f = fuente("ExtraBold", 27)

    def dibujar(capa, pr, dt):
        d = ImageDraw.Draw(capa)
        puestas = []   # nombres y puntos ya puestos (por orden de importancia: el grande nunca se queda fuera)
        for k, c in enumerate(nucleos):
            s = min(1.0, max(0.0, (dt - TRANSICION - 0.15 - k * 0.35) / 0.3))
            if s <= 0:
                continue
            x, y = pr.ciudad(c)
            y += MAPA_Y0
            if not (20 < x < ANCHO - 20 and MAPA_Y0 + 20 < y < MAPA_Y0 + MAPA_H - 20):
                continue
            punto = (x - 11, y - 11, x + 11, y + 11)
            if any(punto[0] < b[2] and punto[2] > b[0] and punto[1] < b[3] and punto[3] > b[1] for b in puestas):
                continue   # su punto quedaría debajo del nombre o el punto de otro más importante
            txt = c["nombre"]
            w, h = f.getlength(txt) + 24, 40
            cands = [(x + 16, y - h / 2), (x - 16 - w, y - h / 2), (x - w / 2, y - h - 14), (x - w / 2, y + 14)]
            if x < ANCHO / 2:   # hacia fuera de la zona: a la izquierda los de la izquierda (si no, arriba o abajo)
                cands = [cands[1], cands[2], cands[3], cands[0]]
            for cx0, cy0 in cands:
                caja = (cx0, cy0, cx0 + w, cy0 + h)
                if caja[0] < 10 or caja[2] > ANCHO - 10:
                    continue
                if any(caja[0] < b[2] + 6 and caja[2] + 6 > b[0] and caja[1] < b[3] + 4 and caja[3] + 4 > b[1]
                       for b in puestas):
                    continue
                break
            else:
                continue
            puestas += [caja, punto]
            a = int(255 * s)
            pulso = 1 + 0.25 * math.sin(dt * 5 + k)
            r = 9 * pulso
            d.ellipse([x - r - 5, y - r - 5, x + r + 5, y + r + 5], outline=color + (int(a * 0.6),), width=3)
            d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=color + (a,), outline=(8, 20, 45, a), width=3)
            d.rounded_rectangle(caja, radius=h / 2, fill=(8, 20, 45, int(225 * s)))
            d.text(((caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2), txt, font=f, fill=(255, 255, 255, a),
                   anchor="mm")
    return dibujar


def _juntar_capas(*fs):
    def dibujar(capa, pr, dt):
        for f_ in fs:
            f_(capa, pr, dt)
    return dibujar


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
                provs = {}
                cerca2 = np.array(poli.filter(ImageFilter.MaxFilter(41))) > 0
                for i in np.unique(lab[cerca2]):
                    if i <= 0:
                        continue
                    sel = m & (np.array(Image.fromarray(((lab == i) * 255).astype(np.uint8)).filter(
                        ImageFilter.MaxFilter(15))) > 0)
                    if sel.any():
                        ys, xs = np.nonzero(sel)
                        provs[nombres[i - 1]] = (float(xs.mean()), float(ys.mean()), int(xs.size))
                gr.setdefault("_provs", {})[tuple(pr.vista)] = provs
        else:
            dentro = lab[pm]
            dentro = dentro[dentro > 0]
            if dentro.size == 0:
                continue
            idx, cuenta = np.unique(dentro, return_counts=True)
            pintadas = []
            for i, c in zip(idx, cuenta):
                total = (lab == i).sum()
                if c >= 0.25 * dentro.size or c >= 0.15 * total:     # la provincia está afectada de verdad
                    out[lab == i] = col + (alfa,)
                    pintadas.append(i)
            if pintadas:
                vistos.append(gr)
                provs = {}
                for i in pintadas:
                    ys, xs = np.nonzero(lab == i)
                    provs[nombres[i - 1]] = (float(xs.mean()), float(ys.mean()), int(xs.size))
                gr.setdefault("_provs", {})[tuple(pr.vista)] = provs
    return Image.fromarray(out, "RGBA"), vistos


def capa_avisos_suave(grupos, alfa=120, leyenda=True):
    """Zonas con aviso (amarillo, naranja o rojo) coloreadas suavemente bajo las tarjetas del parte, con leyenda."""
    cache = {}

    def dibujar(capa, pr, dt):
        aparece = min(1.0, max(0.0, dt / 0.6))
        clave = (tuple(pr.vista), pr.ancho, pr.alto)
        if clave not in cache:
            img, vis = pintar_avisos(grupos, pr, alfa=alfa)
            full = Image.new("RGBA", capa.size, (0, 0, 0, 0)); full.alpha_composite(img, (0, MAPA_Y0))
            cache[clave] = (full, vis)
        lay, vistos = cache[clave]
        if aparece < 1:
            lay = lay.copy(); lay.putalpha(lay.getchannel("A").point(lambda a: int(a * aparece)))
        capa.alpha_composite(lay)
        d = ImageDraw.Draw(capa)
        y = MAPA_Y0 + MAPA_H - 80            # leyenda abajo a la derecha
        for gr in ([] if not leyenda else list(dict.fromkeys((x["nivel"], nombre_fen(x["fenomeno"])) for x in reversed(vistos)))[:3]):
            nivel, fen = gr
            txt = f"AVISO {nivel.upper()} · {fen.upper()}"
            f = fuente("Black", 30)
            w = f.getlength(txt) + 44
            col = COLOR_NIVEL[nivel]
            x0 = ANCHO - 30 - w   # abajo a la derecha: abajo a la izquierda está el recuadro de Canarias
            d.rounded_rectangle([x0, y, x0 + w, y + 50], radius=25, fill=col + (int(235 * aparece),))
            d.text((x0 + w / 2, y + 25), txt, font=f, fill=(15, 25, 50) if nivel == "amarillo" else (255, 255, 255),
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


ICONO_AVISO = {"lluvias": "lluvia", "tormentas": "tormenta", "nevadas": "nieve", "vientos": "viento",
               "nieblas": "niebla", "costeros": "viento", "temperaturas máximas": "calor", "temperaturas mínimas": "helada"}


def _nombre_prov(n: str) -> str:
    return n.split("/")[-1].replace("Santa Cruz De Tenerife", "Tenerife").replace("Illes Balears", "Baleares")


def capa_fichas(grupos, prev_dia=None):
    """Para el bloque de avisos: una ficha por aviso junto a su zona (icono animado, nivel, sitio y dato) y, para que
    el mapa no quede vacío, heladas y rachas fuertes de ese día aunque no tengan aviso."""
    from .mapa import icono, fase_de

    def dibujar(capa, pr, dt, cajas=()):
        from .mapa import etiquetas_provincias
        s_ = min(1.0, max(0.0, (dt - 0.3) / 0.4))
        if s_ <= 0:
            return
        d = ImageDraw.Draw(capa)
        puestas = cajas if isinstance(cajas, list) else list(cajas)
        visibles = [x for x in grupos or [] if (x.get("_provs") or {}).get(tuple(pr.vista))]
        n_ley = min(3, len({(x["nivel"], nombre_fen(x["fenomeno"])) for x in visibles}))
        from .config import RECUADRO_CANARIAS
        x0_, y1_ = pr(RECUADRO_CANARIAS[0], RECUADRO_CANARIAS[2])
        x1_, y0_ = pr(RECUADRO_CANARIAS[1], RECUADRO_CANARIAS[3])
        if 0 <= x0_ < ANCHO and 0 <= y0_ < MAPA_H:   # el recuadro de Canarias tampoco se tapa
            puestas.append((x0_, MAPA_Y0 + y0_, x1_, MAPA_Y0 + y1_))
        if n_ley:   # la leyenda de avisos (abajo a la derecha) no se pisa
            puestas.append((ANCHO - 560, MAPA_Y0 + MAPA_H - 80 - 60 * (n_ley - 1) - 14, ANCHO, MAPA_Y0 + MAPA_H - 16))
        fichas = []
        for gr in sorted(grupos or [], key=lambda x: -NIVELES[x["nivel"]]):
            provs = (gr.get("_provs") or {}).get(tuple(pr.vista)) or {}
            if not provs or "niebla" in gr["fenomeno"]:
                continue   # la niebla ya lleva su insignia animada
            por_com = {}
            for p_, (x, y, n) in provs.items():
                por_com.setdefault(COMUNIDAD_PROV.get(p_, p_), []).append((p_, x, y, n))
            dato = dato_aviso(gr) if len(por_com) == 1 else ""
            dato = dato.replace(" EN 1 HORA", "/H") if dato else ""
            for com, lista in sorted(por_com.items(), key=lambda kv: -sum(t[3] for t in kv[1])):
                tot = sum(t[3] for t in lista)
                x = sum(t[1] * t[3] for t in lista) / tot
                y = sum(t[2] * t[3] for t in lista) / tot
                sitio = _nombre_prov(lista[0][0]) if len(lista) == 1 else com
                fichas.append((x, MAPA_Y0 + y, COLOR_NIVEL[gr["nivel"]], ICONO_AVISO.get(gr["fenomeno"].lower(), "lluvia"),
                               sitio.upper(), (nombre_fen(gr["fenomeno"]) + (f" · {dato}" if dato else "")).upper(),
                               gr["nivel"], com.upper()))
        extra = []
        pd = prev_dia or []
        for c in sorted(pd, key=lambda c: -c["tmax"])[:2]:          # ola de calor / calor extremo
            if c["tmax"] >= 38:
                extra.append((c, "calor", (255, 120, 60), c["nombre"].upper(), f"CALOR EXTREMO · {c['tmax']}°"))
        for c in sorted(pd, key=lambda c: c["tmin"])[:3]:            # frío extremo y heladas
            if c["tmin"] <= -5:
                extra.append((c, "helada", (120, 170, 255), c["nombre"].upper(), f"FRÍO EXTREMO · {c['tmin']}°"))
            elif c["tmin"] <= 0:
                extra.append((c, "helada", (140, 200, 255), c["nombre"].upper(), f"HELADA · {c['tmin']}°"))
        for c in [c for c in pd if c.get("granizo")][:2]:              # granizo
            extra.append((c, "granizo", (200, 220, 255), c["nombre"].upper(), "POSIBLE GRANIZO"))
        for c in [c for c in pd if c.get("icono") == "tormenta" and not c.get("granizo")][:2]:
            extra.append((c, "tormenta", (255, 214, 90), c["nombre"].upper(), "TORMENTAS"))
        if pd:   # para que el mapa nunca quede vacío: lo más caluroso y lo más frío del día
            if not any(e_[4].startswith("CALOR") for e_ in extra):
                c = max(pd, key=lambda c: c["tmax"])
                extra.append((c, "sol", (255, 170, 60), c["nombre"].upper(), f"MÁXIMA · {c['tmax']}°"))
            if not any(e_[4].startswith(("HELADA", "FRÍO")) for e_ in extra):
                c = min(pd, key=lambda c: c["tmin"])
                extra.append((c, "nubes", (140, 200, 255), c["nombre"].upper(), f"MÍNIMA · {c['tmin']}°"))
        for c in sorted(prev_dia or [], key=lambda c: -(c.get("racha") or 0))[:2]:
            if (c.get("racha") or 0) >= 60:
                extra.append((c, "viento", (200, 220, 255), c["nombre"].upper(), f"RACHAS · {round(c['racha'])} KM/H"))
        # Una sola ficha por sitio: si en Tenerife hay lluvia, viento, oleaje y tormentas, van juntas (antes salían
        # cuatro fichas apiladas y se solapaban)
        juntas = {}
        for x, y, col, ic, l1, l2, nivel, com in fichas:   # por comunidad: «Tenerife» y «Canarias» van juntas
            if com in juntas:
                j_ = juntas[com]
                if l1 != j_[4]:
                    j_[4] = com
                if l2.split(" · ")[0] not in [t.split(" · ")[0] for t in j_[5]]:
                    j_[5].append(l2)
            else:
                juntas[com] = [x, y, col, ic, l1, [l2], nivel]
        fichas = []
        f2 = fuente("ExtraBold", 24)
        for x, y, col, ic, l1, ls, nivel in juntas.values():
            lineas = [ls[0]]
            if len(ls) > 1:
                resto = " · ".join(t.split(" · ")[0] if len(ls) > 2 else t for t in ls[1:])
                while f2.getlength(resto) > 430 and " · " in resto:
                    resto = resto.rsplit(" · ", 1)[0] + " Y MÁS"
                lineas.append(resto)
            fichas.append((x, y, col, ic, l1, lineas, nivel))
        for c, ic, col, l1, l2 in extra:
            x, y = pr.ciudad(c)
            fichas.append((x, MAPA_Y0 + y, col, ic, l1, [l2], "info"))
        f1 = fuente("Black", 30)
        for k, (x, y, col, ic, l1, lineas, nivel) in enumerate(fichas[:9]):
            w = max([f1.getlength(l1)] + [f2.getlength(t) for t in lineas]) + 112
            h = 76 + 30 * (len(lineas) - 1)
            pos = None
            for paso in range(0, 22):
                for dx, dy in ((0, -1), (0, 1), (1, 0), (-1, 0), (1, -1), (-1, -1), (1, 1), (-1, 1)):
                    cx, cy = x + dx * paso * 22, y - 70 + dy * paso * 22
                    r = (cx - w / 2 - 6, cy - h / 2 - 6, cx + w / 2 + 6, cy + h / 2 + 6)
                    if 10 + w / 2 < cx < ANCHO - 140 - w / 2 and MAPA_Y0 + h / 2 < cy < MAPA_Y0 + MAPA_H - h / 2 - 20 \
                            and not any(r[0] < b[2] and r[2] > b[0] and r[1] < b[3] and r[3] > b[1] for b in puestas):
                        pos = (cx, cy)
                        break
                    if paso == 0:
                        break
                if pos:
                    break
            if not pos:
                continue
            cx, cy = pos
            puestas.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
            a = int(240 * s_)
            d.line([(cx, cy + h / 2), (x, y)], fill=(255, 255, 255, int(170 * s_)), width=3)
            d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(255, 255, 255, a), outline=(8, 20, 45, a), width=3)
            d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=22, fill=(10, 22, 48, a),
                                outline=col + (a,), width=5)
            im = icono(ic, 64, fase_de(dt, k * 0.4))
            if s_ < 1:
                im = im.copy(); im.putalpha(im.getchannel("A").point(lambda v: int(v * s_)))
            capa.alpha_composite(im, (int(cx - w / 2 + 14), int(cy - 32)))
            y0 = cy - h / 2 + 24
            d.text((cx - w / 2 + 90, y0), l1, font=f1, fill=(255, 255, 255, int(255 * s_)), anchor="lm")
            for j, t in enumerate(lineas):
                d.text((cx - w / 2 + 90, y0 + 32 + 30 * j), t, font=f2,
                       fill=(col if j == 0 else (225, 232, 245)) + (int(255 * s_),), anchor="lm")
    return dibujar


def capa_tormentas(prev):
    """Insignia con rayo que parpadea donde hay tormentas (y 'GRANIZO' si es posible), esquivando las tarjetas."""
    sitios = [c for c in prev or [] if c.get("icono") == "tormenta" or c.get("granizo")]
    sitios = sorted(sitios, key=lambda c: (not c.get("granizo"), -(c.get("lluvia") or 0)))[:3]

    def rayo(d, x, y, brillo):
        pts = [(x + 6, y - 14), (x - 4, y + 2), (x + 2, y + 2), (x - 3, y + 15), (x + 9, y - 3), (x + 3, y - 3), (x + 8, y - 14)]
        d.polygon(pts, fill=(255, 214, 40, int(255 * brillo)))

    def dibujar(capa, pr, dt, cajas=()):
        if not sitios:
            return
        s_ = min(1.0, max(0.0, (dt - 0.3) / 0.4))
        if s_ <= 0:
            return
        d = ImageDraw.Draw(capa)
        puestas = cajas if isinstance(cajas, list) else list(cajas)
        f = fuente("Black", 28)
        from .video import CAJAS_CIUDAD
        for k, c in enumerate(sitios):
            x, y = pr.ciudad(c); y += MAPA_Y0
            txt = "GRANIZO" if c.get("granizo") else "TORMENTA"
            w, h = f.getlength(txt) + 70, 50
            pos = None
            cj = CAJAS_CIUDAD.get(c["nombre"])
            if cj:   # pegada a su tarjeta: justo debajo (o encima si no cabe)
                for cy in (cj[3] + h / 2 - 6, cj[1] - h / 2 + 6):
                    cx = (cj[0] + cj[2]) / 2
                    r = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                    if MAPA_Y0 + h / 2 < cy < MAPA_Y0 + MAPA_H - h / 2 and not any(
                            r[0] < b[2] and r[2] > b[0] and r[1] < b[3] and r[3] > b[1] for b in puestas if b != cj):
                        pos = (cx, cy)
                        break
            for paso in range(0 if not pos else 99, 8):   # cerca de su ciudad o nada (la tarjeta ya lleva la tormenta)
                for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1), (1, 1), (-1, 1)):
                    cx, cy = x + dx * paso * 22, y + 38 + dy * paso * 22
                    r = (cx - w / 2 - 6, cy - h / 2 - 6, cx + w / 2 + 6, cy + h / 2 + 6)
                    if 10 + w / 2 < cx < ANCHO - 20 - w / 2 and MAPA_Y0 + h < cy < MAPA_Y0 + MAPA_H - h \
                            and not any(r[0] < b[2] and r[2] > b[0] and r[1] < b[3] and r[3] > b[1] for b in puestas):
                        pos = (cx, cy); break
                    if paso == 0:
                        break
                if pos:
                    break
            if not pos:
                continue
            cx, cy = pos
            puestas.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
            fl = (math.sin(dt * 9 + k * 2) > 0.55)           # destello del rayo
            fondo = (70, 60, 110) if not fl else (110, 95, 170)
            d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=25,
                                fill=fondo + (int(240 * s_),), outline=(255, 214, 40, int(230 * s_)), width=3)
            rayo(d, cx - w / 2 + 22, cy, s_ * (1.0 if fl else 0.75))
            if c.get("granizo"):
                for j in range(3):
                    u = (dt * 1.2 + j / 3) % 1
                    gx, gy = cx - w / 2 + 34 + j * 6, cy - 6 + u * 16
                    d.ellipse([gx - 3, gy - 3, gx + 3, gy + 3], fill=(230, 240, 255, int(230 * (1 - u) * s_)))
            d.text((cx - w / 2 + 48, cy), txt, font=f, fill=(255, 255, 255, int(255 * s_)), anchor="lm")
    return dibujar


def combinar_encima(*funcs):
    funcs = [f for f in funcs if f]
    if not funcs:
        return None
    def dibujar(capa, pr, dt, cajas=()):
        acc = list(cajas)   # cada capa añade lo que pone, para que la siguiente no lo pise
        for f in funcs:
            f(capa, pr, dt, acc)
    return dibujar


_OLAS = {}


def _ola_sprite(fase: float) -> Image.Image:
    """Icono de ola rompiendo (48×44), dibujado con supermuestreo; 24 fotogramas en bucle."""
    k = int((fase * 12) % 24)
    if k in _OLAS:
        return _OLAS[k]
    S, W, H = 4, 48, 44
    im = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    t = k / 24 * 2 * math.pi
    sx, sy = math.sin(t) * 2.5, math.cos(t) * 1.8          # balanceo de la cresta
    P = lambda px, py: ((px + sx) * S, (py + sy) * S)
    # cuerpo de la ola: sube desde la izquierda, cresta arriba a la derecha y cae con un rizo
    cuerpo = [P(2, 40), P(4, 34), P(9, 27), P(15, 19), P(22, 12), P(30, 8), P(37, 8), P(42, 11), P(44, 16),
              P(42, 21), P(38, 22), P(35, 19), P(36, 15), P(33, 15), P(29, 19), P(28, 26), P(31, 33), P(36, 38),
              P(40, 40)]
    d.polygon(cuerpo, fill=(255, 255, 255, 255))
    # hueco del rizo (azul) y espuma
    d.ellipse([*P(29, 15), *P(37, 22)], fill=(40, 120, 220, 255))
    for fx, fy, r in ((40, 10, 2.2), (44, 13, 1.8), (35, 7, 1.6)):
        cx, cy = P(fx, fy)
        d.ellipse([cx - r * S, cy - r * S, cx + r * S, cy + r * S], fill=(255, 255, 255, 255))
    # línea de agua que avanza por debajo
    pts = [((i) * S, (42 + 1.6 * math.sin(i / 6 - t * 2)) * S) for i in range(0, W + 1)]
    d.line(pts, fill=(200, 230, 255, 255), width=3 * S)
    im = im.resize((W, H), Image.LANCZOS)
    _OLAS[k] = im
    return im


def capa_mar_nieve(olas: list[dict], nieves: list[dict], nieblas: list[dict] | None = None):
    """Altura de las olas en el mar (insignia azul con ola) y cota de nieve en la montaña (copo con la cota)."""
    nieves = sorted(nieves, key=lambda e: (-e["cm"], e["cota"]))[:5]   # solo las principales
    olas = sorted(olas, key=lambda o: -o["olas"])[:5]
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
            w = f.getlength(txt) + 86
            pos = libre(x, y, w, 56, cajas, puestas, mar=mascara_tierra(pr))
            if not pos:
                continue
            x, y = pos
            puestas.append((x - w / 2, y - 28, x + w / 2, y + 28))
            col = (20, 90, 200) if o["olas"] < 5 else (200, 40, 60)
            d.rounded_rectangle([x - w / 2, y - 28, x + w / 2, y + 28], radius=28, fill=col + (int(240 * s_),),
                                outline=(255, 255, 255, int(230 * s_)), width=3)
            capa.alpha_composite(_ola_sprite(dt), (int(x - w / 2 + 10), int(y - 22)))
            d.text((x - w / 2 + 64, y), txt, font=f, fill=(255, 255, 255, int(255 * s_)), anchor="lm")
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
            from .mapa import icono as _icono, fase_de as _fase
            capa.alpha_composite(_icono("niebla", 56, _fase(dt)), (int(x - w / 2 + 6), int(y - 28)))
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
        if isinstance(cajas, list):
            cajas.extend(puestas)
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
            sit = sitios_aviso(gr)
            zonas = ", ".join(sit if gr["nivel"] in ("rojo", "naranja") else sit[:3])
            dato = dato_aviso(gr)
            partes.append(f"{k}: aviso {gr['nivel']} por {nombre_fen(gr['fenomeno'])} en {zonas}"
                          + (f" ({dato.lower()})" if dato else ""))
    if not partes:
        return ""
    return ("\n\nAVISOS DE AEMET PREVISTOS (se ven coloreados en el mapa de su día): " + "; ".join(partes)
            + ". Menciónalos en el bloque de su día: los naranjas y rojos, siempre y nombrando los sitios (en Canarias, "
              "las islas; en los ROJOS, TODOS los sitios, es imprescindible); los amarillos, de pasada. Si hay "
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
- zonas: dónde y cuándo (desde qué hora; horas en palabras). Nombra TODOS los sitios de "sitios_afectados" (en
  Canarias, todas las islas: si el aviso es de cuatro islas no puede salir solo Tenerife); si son muchos, agrúpalos
  («todo el litoral de Valencia y el norte de Alicante»). Si el aviso es ROJO es OBLIGATORIO nombrar cada sitio, aunque el
  bloque quede más largo. En pantalla se hace zoom a la zona y se señalan los núcleos de "nucleos_senalados_en_el_mapa".
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
    from .poblaciones import _islas
    if len(_islas(cs)) >= 2:   # Canarias: debajo, las islas afectadas
        return [tit, " · ".join(_islas(cs)[:5])] if tit == "Canarias" else [tit]
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


def _fecha_portada(gr, hoy: date) -> str:
    """'JUEVES 5 DE NOVIEMBRE': el día en que empieza el aviso (o hoy, si ya está en curso)."""
    try:
        from zoneinfo import ZoneInfo
        d = max(datetime.fromisoformat(gr["inicio"]).astimezone(ZoneInfo("Europe/Madrid")).date(), hoy)
    except Exception:  # noqa: BLE001
        d = hoy
    return f"{g.DIAS[d.weekday()].upper()} {d.day} DE {MESES_LARGOS[d.month - 1]}"


def _hora_txt(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{g.DIAS[d.weekday()]} {d.day} a las {d:%H:%M}"


def amarillos_cerca(todos, grupos, momento) -> list[dict]:
    """Avisos amarillos del mismo fenómeno, en las próximas 24 h y en la misma zona que los naranjas/rojos (en
    Canarias, el resto de islas): para decir «en Lanzarote y Fuerteventura, aviso amarillo» y que nadie crea que se
    ha librado."""
    if not grupos:
        return []
    fen = {g["fenomeno"] for g in grupos}
    pts = [p for g in grupos for pol in g["poligonos"] for p in pol]
    canaria = bool(pts) and all(la < 30 for _, la in pts)
    lo0, lo1 = min(p[0] for p in pts or [(0, 0)]), max(p[0] for p in pts or [(0, 0)])
    la0, la1 = min(p[1] for p in pts or [(0, 0)]), max(p[1] for p in pts or [(0, 0)])
    out = []
    for a in todos:
        if a["nivel"] != "amarillo" or a["fenomeno"] not in fen or not a.get("poligono"):
            continue
        try:
            ini, fin = datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"])
        except (TypeError, ValueError):
            continue
        if not (fin > momento and ini < momento + timedelta(hours=24)):
            continue
        cx = sum(p[0] for p in a["poligono"]) / len(a["poligono"])
        cy = sum(p[1] for p in a["poligono"]) / len(a["poligono"])
        if canaria:
            if cy >= 30:
                continue
        elif not (lo0 - 1.5 <= cx <= lo1 + 1.5 and la0 - 1.2 <= cy <= la1 + 1.2):
            continue
        out.append({**a, "ciudades": []})
    gs = agrupar(out)
    # sin repetir zonas que ya están en naranja/rojo (el amarillo de 1 hora dentro del naranja de 12 horas)
    ya = {z for g in grupos for z in g["zonas"]}
    ya_islas = set(islas_de(list(ya)))
    for g in gs:
        g["zonas"] = [z for z in g["zonas"] if z not in ya and not (set(islas_de([z])) & ya_islas)]
    return [g for g in gs if g["zonas"]]


def sitios_aviso(gr) -> list[str]:
    """Los sitios que hay que nombrar: en Canarias, las islas; si no, las zonas de AEMET (todas en rojo, hasta 6 en
    naranja), sin repetir."""
    islas = islas_de(gr["zonas"])
    if len(islas) >= 2:
        return islas
    zonas = list(dict.fromkeys(z.split(" - ")[-1] for z in gr["zonas"]))
    return zonas[:14]   # todas: es lo que evita que alguien se lleve un susto


def _completar_sitios(gg: dict, grupos):
    """Si el guion se dejó algún sitio (islas en Canarias, o cualquier zona en un aviso rojo), se añade una frase."""
    texto = _norm_txt(" ".join(gg["segmentos"].values()))
    faltan = []
    for gr in grupos[:4]:
        if gr["nivel"] not in ("rojo", "naranja"):
            continue
        for sitio in sitios_aviso(gr):
            # todas sus palabras con sentido («norte» y «valencia» en «Litoral norte de Valencia»)
            claves = [w for w in _norm_txt(sitio).replace(",", " ").split()
                      if (len(w) > 3 or w in ("sur", "este")) and w not in ("litoral", "zona", "area", "zonas")]
            if claves and not all(w in texto for w in claves) and sitio not in faltan:
                faltan.append(sitio)
    if faltan:
        lista = faltan[0] if len(faltan) == 1 else ", ".join(faltan[:-1]) + " y " + faltan[-1]
        gg["segmentos"]["zonas"] = gg["segmentos"]["zonas"].rstrip() + f" También afecta a {lista}."
        log.info("Aviso: se añaden al guion los sitios que faltaban: %s", lista)


def _norm_txt(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def guion_aviso(grupos, hoy: date, factor: float, presenta: str, plantilla: bool) -> dict:
    orden = ["intro", "zonas", "consejos", "cierre"]
    palabras = {k: max(8, round(v * factor)) for k, v in PALABRAS_AVISO.items()}
    datos = [{"nivel": gr["nivel"], "fenomeno": gr["fenomeno"], "zonas": gr["zonas"][:12],
              "grandes_ciudades_afectadas": gr.get("ciudades", [])[:8],
              "desde": _hora_txt(gr["inicio"]), "hasta": _hora_txt(gr["fin"]), "descripcion": gr["descripcion"],
              "instruccion": gr["instruccion"]} for gr in grupos[:4]]
    for d_, gr in zip(datos, grupos[:4]):
        d_["sitios_afectados"] = sitios_aviso(gr)
    if datos and AMARILLOS:
        datos[0]["ADEMAS_AVISO_AMARILLO"] = [f"{nombre_fen(g['fenomeno'])} en " + ", ".join(sitios_aviso(g))
                                             for g in AMARILLOS]
        datos[0]["nota_amarillo"] = ("Al final de «zonas» añade una frase corta con los avisos amarillos de "
                                     "ADEMAS_AVISO_AMARILLO («En Lanzarote y Fuerteventura, aviso amarillo por lluvias y "
                                     "tormentas»), para que nadie de esas zonas crea que se ha librado.")
    if datos and AMPLIACION:
        datos[0]["NOVEDAD"] = ("AEMET AMPLÍA el aviso a: " + ", ".join(AMPLIACION) + ". Empieza el vídeo con eso "
                               "(«AEMET amplía el aviso naranja a Gran Canaria») y luego nombra TODOS los sitios.")
    extra = max(0, sum(len(sitios_aviso(gr)) for gr in grupos[:4]) - 3)
    palabras["zonas"] += 3 * extra   # con muchos sitios, el bloque de zonas puede alargarse
    if datos:
        datos[0]["nucleos_senalados_en_el_mapa"] = [c["nombre"] for c in nucleos_afectados(grupos)]
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
    sit = sitios_aviso(gr)
    zonas = (", ".join(sit[:-1]) + " y " + sit[-1]) if len(sit) > 1 else (sit[0] if sit else "")
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
        sitios = list(dict.fromkeys(sitios_aviso(gr) + [c for c in gr.get("ciudades") or [] if c not in ISLAS]))
        icono = {"rojo": "🔴", "naranja": "🟠"}.get(gr["nivel"], "🟡")
        n = 14   # todos los sitios
        lineas.append(f"{icono} Aviso {gr['nivel']} por {nombre_fenomeno(gr['fenomeno'])}: {', '.join(sitios[:n])}"
                      + (" y más" if len(sitios) > n else ""))
    for g in AMARILLOS:
        lineas.append(f"🟡 Aviso amarillo por {nombre_fenomeno(g['fenomeno'])}: {', '.join(sitios_aviso(g))}")
    lineas += ["ℹ️ Fuente: AEMET. Sigue las indicaciones de Protección Civil. Emergencias: 112.",
               "Mapa de núcleos: GeoNames (CC BY 4.0)."]
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
    # Primero el mapa entero (como siempre) y después zoom sobre la zona, con sus principales núcleos señalados
    zona = _zona_zoom(grupos)
    nucleos = nucleos_afectados(grupos)
    consejos = [c.upper()[:28] for c in (guion.get("consejos_pantalla") or [])][:3] or \
        CONSEJOS_BASE.get(grupos[0]["fenomeno"], ["SIGUE A AEMET", "PRECAUCIÓN", "LLAMA AL 112"])
    gr = grupos[0]
    lluvia_aviso = None
    if not demo and any("lluvia" in x["fenomeno"].lower() for x in grupos):   # en el zoom, la lluvia en colores
        try:
            from . import campos
            from zoneinfo import ZoneInfo
            dia = max(datetime.fromisoformat(gr["inicio"]).astimezone(ZoneInfo("Europe/Madrid")).date(), hoy)
            lluvia_aviso = campos.capa_lluvia(dia, con_canarias=any(la < 30 for x in grupos for pol in x["poligonos"]
                                                                    for _, la in pol))
        except Exception as e:  # noqa: BLE001
            log.warning("Lluvia en colores para el aviso: %s", e)
    kwargs = {
        "vistas": {"intro": VISTA_GENERAL, "zonas": zona, "consejos": _zona_cerca(grupos, nucleos), "cierre": zona},
        "sin_marcadores": ("intro", "zonas", "consejos", "cierre"),
        "pills": {"zonas": "ZONAS Y HORAS", "consejos": "QUÉ HACER", "cierre": "COMPÁRTELO",
                  "promesa": "COMPÁRTELO CON QUIEN VIVA ALLÍ", "cierre_1": "COMPÁRTELO",
                  "cierre_2": "con quien viva en esas zonas", "cierre_3": "Sígueme · avisos al momento"},
        "capas": {"intro": _capa_poligonos(grupos + AMARILLOS),
                  "zonas": _juntar_capas(_capa_poligonos(grupos + AMARILLOS, con_lista=True), _capa_nucleos(nucleos)),
                  "consejos": _juntar_capas(_capa_poligonos(grupos + AMARILLOS, consejos=consejos),
                                            *([lluvia_aviso] if lluvia_aviso else []), _capa_nucleos(nucleos[:4])),
                  "cierre": _capa_poligonos(grupos + AMARILLOS)},
        "gancho": _gancho_aviso(grupos),
        "aviso_portada": {"nivel": gr["nivel"],
                          "fenomeno": " y ".join(dict.fromkeys("oleaje" if "costeros" in x["fenomeno"] else x["fenomeno"]
                                                               for x in grupos)) if gr["nivel"] == "naranja"
                          else ("oleaje" if "costeros" in gr["fenomeno"] else gr["fenomeno"]),
                          "icono": _gancho_aviso(grupos).get("icono"),
                          "ciudades": _ciudades_portada_todos(grupos),
                          "cuando": _cuando_portada(gr, hoy), "dato": dato_aviso(gr),
                          "fecha": _fecha_portada(gr, hoy),
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
    uploadpost.instagram_seguro(meta)   # también como Reel en Instagram


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
        with duracion(*DURACION_FINDE):
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
            todos = descargar_avisos(clave)
            grupos = agrupar(avisos_relevantes(todos, datetime.now().astimezone()))
            AMARILLOS[:] = amarillos_cerca(todos, grupos, datetime.now().astimezone())
        if not grupos:
            log.info("No hay avisos naranjas ni rojos en poblaciones de más de 100.000 habitantes")
            return
        # Un vídeo por nivel y día: uno con todos los rojos y otro con todos los naranjas
        for nivel in ("rojo", "naranja"):
            del_nivel = [x for x in grupos if x["nivel"] == nivel]
            if not del_nivel:
                continue
            hist_n = HISTORIAL / f"aviso-{hoy.isoformat()}-{nivel}.json"
            AMPLIACION[:] = []
            if hist_n.exists() and not a.demo:
                # Ya salió el de hoy: solo se hace otro si AEMET ha AMPLIADO el aviso a sitios nuevos (Gran Canaria
                # el 8/11/2026). Nunca más de tres vídeos del mismo nivel en un día.
                previos = sorted(HISTORIAL.glob(f"aviso-{hoy.isoformat()}-{nivel}*.json"))
                ya = set()
                for f in previos:
                    for x in json.loads(f.read_text(encoding="utf-8")).get("avisos") or []:
                        ya |= set(x.get("ciudades") or []) | set(x.get("zonas") or [])
                nuevos = list(dict.fromkeys(c for x in del_nivel for c in sitios_aviso(x) + (x.get("ciudades") or [])
                                            if c not in ya and not any(c in z for z in ya)))
                if os.environ.get("REHACER"):   # a mano: rehacer el vídeo de hoy (zoom más cerca, etc.)
                    nuevos = nuevos or ["(rehecho)"]
                if not nuevos or len(previos) >= 3:
                    log.info("El vídeo de avisos %ss de hoy ya está publicado (sin sitios nuevos)", nivel)
                    continue
                AMPLIACION[:] = [x for x in nuevos if x != "(rehecho)"]
                log.info("AEMET amplía el aviso %s a: %s → vídeo nuevo", nivel, nuevos)
                hist_n = HISTORIAL / f"aviso-{hoy.isoformat()}-{nivel}-{len(previos) + 1}.json"
            if not a.demo and not AMPLIACION and _repetido(del_nivel, hoy, nivel):
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
