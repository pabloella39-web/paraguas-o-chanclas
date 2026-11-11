"""Orquestador: datos → guion → voz → vídeo (65–70 s) → espera a las 7:30 → TikTok.

Ejemplos:
  python -m tiempo.main --demo                 # vídeo de prueba con datos inventados y sin voz
  python -m tiempo.main                        # vídeo real (necesita claves), sin publicar
  python -m tiempo.main --publicar --esperar   # lo que hace GitHub Actions cada mañana
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path

from . import descripcion
from . import guion as g
from . import eleven, musica, voz
from .config import (DURACION_MAX, DURACION_MIN, DURACION_OBJETIVO, FPS, RAIZ, SEGMENTOS, VOCES,
                     voz_del_dia)
from .fuentes import obtener_previsiones, previsiones_demo
from .horario import ahora, esperar_hasta_publicacion
from .video import Compositor, renderizar

log = logging.getLogger("tiempo")

INICIO = 0.12      # la voz arranca desde el primer instante (retención: nada de segundos muertos)
COLA_ELEVEN = 1.3  # cola tras la despedida con la toma continua de ElevenLabs
PAUSA = 0.35       # respiración entre bloques (fija: ya no se estira para rellenar)
COLA_MIN = 1.2     # tras la despedida (tarjeta de "sígueme")
VEL_MIN, VEL_MAX = 10, 35  # nunca más lenta de +10 %: si sobra tiempo, se alarga el guion


AVISO_GRAVE: list = [None]
CAMPO_PARTE: list = [None]   # lluvia acumulada del aviso (campos, máximos por sitio)
MAPA_EXTRA: list = [None]   # (capa, pastilla) para el bloque «general»: lluvia en colores o isobaras, de vez en cuando


def _kwargs_juntos(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict):
            out[k] = {**(out.get(k) or {}), **v}
        elif isinstance(v, (tuple, list)) and isinstance(out.get(k), (tuple, list)):
            out[k] = tuple(out[k]) + tuple(v)   # sin_marcadores de los dos
        else:
            out[k] = v
    return out


def mapa_extra(prev, avisos, hoy) -> str:
    """De vez en cuando, más información en el bloque general: el mapa de lluvia en escala de colores (si es un día de
    lluvia) o el de isobaras (si hay una borrasca o un anticiclón que manda). Devuelve la nota para el guion."""
    from . import campos
    lluviosas = [c for c in prev if c.get("lluvia", 0) >= 50]
    hay_aviso_lluvia = any("lluvia" in x["fenomeno"].lower() or "tormenta" in x["fenomeno"].lower() for x in avisos)
    try:
        if (len(lluviosas) >= 4 or hay_aviso_lluvia) and hoy.toordinal() % 2 == 0:
            capa = campos.capa_lluvia(hoy)
            if capa:
                MAPA_EXTRA[0] = (capa, "LLUVIA PREVISTA (L/M²)")
                return ("\n\nMAPA DE LLUVIA: en el bloque «general» sale el mapa de lluvia acumulada en colores (de "
                        "celeste a morado: de 1 a más de 120 litros). Dedícale una frase: dónde se acumulará más lluvia "
                        "(«fíjate en las zonas en verde y amarillo: ahí caerán más de 15 litros»).")
        if hoy.toordinal() % 3 == 0 or (len(lluviosas) >= 4 and hoy.toordinal() % 2 == 1):
            r = campos.capa_isobaras(hoy)
            if r:
                capa, centros, pmin, pmax = r
                fuertes = [c for c in centros if (c[0] == "B" and c[3] <= 1005) or (c[0] == "A" and c[3] >= 1026)]
                if fuertes:
                    MAPA_EXTRA[0] = (capa, "ISOBARAS · MEDIODÍA")
                    desc = "; ".join(f"{'borrasca' if t == 'B' else 'anticiclón'} de {p:.0f} hPa"
                                     f" ({'al oeste' if lo < -10 else 'al norte' if la > 45 else 'cerca'})"
                                     for t, lo, la, p in fuertes[:3])
                    return ("\n\nMAPA DE ISOBARAS: en el bloque «general» sale el mapa de isobaras del mediodía con "
                            f"las altas (A) y bajas (B): {desc}. Dedícale una frase sencilla que explique qué "
                            "significa para el tiempo (líneas muy juntas = viento; la B trae lluvia; la A, estabilidad).")
    except Exception as e:  # noqa: BLE001
        log.warning("Mapa extra no disponible: %s", e)
    return ""   # avisos naranja/rojo del día (para el tramo «aviso» con zoom)


def _kwargs_aviso(racimos, segmentos: dict | None = None) -> dict:
    """Un tramo con zoom por cada zona distante con aviso («aviso», «aviso2», «aviso3»): zonas pintadas, núcleos y
    ciudades señalados y, en la primera, la lluvia acumulada en colores. Entre zonas lejanas, zoom out y zoom in."""
    if not racimos:
        return {}
    from .especiales import (_caja_lista, _capa_despues, _capa_nucleos, _capa_poligonos, _juntar_capas, _zona_zoom,
                             ciudades_zoom, nucleos_afectados, nucleos_nombrados)
    segmentos = segmentos or {}
    todos = [g_ for _, r in racimos for g_ in r]
    out = {"vistas": {}, "sin_marcadores": (), "transiciones": {}, "capas": {}, "pills": {}}
    for n, (clave, graves) in enumerate(racimos):
        if clave not in segmentos:
            continue
        nivel = "rojo" if any(x["nivel"] == "rojo" for x in graves) else "naranja"
        gn, otras = nucleos_afectados(graves, n=10), ciudades_zoom(graves, [])
        dentro = [c for c in gn if c["poblacion"] >= 20000]
        nucleos = dentro + otras + [c for c in gn if c not in dentro]
        nombrados = nucleos_nombrados(segmentos.get(clave, ""), graves)   # lo que se nombra, se señala
        nucleos = nombrados + [c for c in nucleos if c["nombre"] not in {x["nombre"] for x in nombrados}]
        capa = _juntar_capas(_capa_poligonos(todos, con_lista=True),
                             _capa_nucleos(nucleos, reservado=_caja_lista(graves)))
        if n == 0 and CAMPO_PARTE[0]:   # lluvia acumulada en colores (la de la zona principal)
            from . import campos
            campo_ = CAMPO_PARTE[0]
            h_ = campo_[2] if len(campo_) > 2 else {}
            anim = None
            if h_.get("cajas"):   # el acumulado creciendo hora a hora, con los litros de cada zona (no una imagen fija)
                anim = campos.capa_acumulado(h_["lons"], h_["lats"], h_["horas"], h_["cubo"], h_["canaria"],
                                             h_["cajas"], titulo="LLUVIA ACUMULADA PREVISTA (L/M²)")
            base = anim or campos.capa_lluvia_fuerte(campo_[0], "LLUVIA ACUMULADA PREVISTA (L/M²)")
            partes = [base, _capa_nucleos(nucleos, reservado=getattr(base, "reservado", None))]
            if getattr(base, "encima", None):
                partes.append(base.encima)   # al final, la cifra total sobre el mapa donde más cae
            lluvia = _juntar_capas(*partes)
            capa = _capa_despues(capa, lluvia, 4.5, sustituye=True)
        out["vistas"][clave] = _zona_zoom(graves)
        out["sin_marcadores"] += (clave,)
        out["transiciones"][clave] = 2.4 if n == 0 else 3.4   # entre zonas lejanas: alejarse y volver a acercarse
        out["capas"][clave] = capa
        out["pills"][clave] = f"AVISO {nivel.upper()}"
    return out


SISTEMA: list = [None]   # (capa, etiqueta) del tramo «sistema»: borrasca/DANA hora a hora


def _kwargs_sistema() -> dict:
    if not SISTEMA[0]:
        return {}
    from .sistemas import VISTA_SISTEMA
    capa, etiqueta = SISTEMA[0]
    return {"vistas": {"sistema": VISTA_SISTEMA}, "sin_marcadores": ("sistema",), "canarias_real": ("sistema",),
            "capas": {"sistema": capa},
            "pills": {"sistema": etiqueta}}


EXTREMOS_PUEBLOS: list = [None]   # {calor, frio} con el pueblo si es más extremo que la capital

def secuencia(guion: dict) -> list[str]:
    """Gancho, regiones de más a menos relevantes, la 'recompensa' (más calor y más frío) y la despedida."""
    orden = guion.get("orden") or [s for s in SEGMENTOS if s not in ("intro", "general", "cierre")]
    # «aviso» (solo si hay naranja o rojo): justo tras el gancho, con zoom a la zona y sus pueblos señalados
    return [s for s in ("intro", "aviso", "aviso2", "aviso3", "sistema", *orden, "general", "cierre")
            if str(guion["segmentos"].get(s, "")).strip()]


def _capas_parte(avisos):
    """Zonas con aviso coloreadas (debajo de las tarjetas), en todos los bloques regionales."""
    from .especiales import capa_avisos_suave
    return {"*": capa_avisos_suave(avisos)} if avisos else None


def _capas_encima(mar_nieve, avisos=None, prev=None):
    """Olas, nieve, niebla con aviso y tormentas/granizo (encima de todo, esquivando las tarjetas)."""
    from .especiales import capa_mar_nieve, capa_tormentas, combinar_encima, nieblas_de
    ol, ni = mar_nieve
    nb = nieblas_de(avisos)
    f = combinar_encima(capa_mar_nieve(ol, ni, nb) if (ol or ni or nb) else None, capa_tormentas(prev))
    return {"*": f} if f else None


def generar_eleven(prev, hoy, texto_aemet, trabajo: Path, tipo_voz: str):
    """Guion de la longitud justa ANTES de sintetizar (para gastar los mínimos créditos) y una sola toma."""
    objetivo = DURACION_OBJETIVO - INICIO - COLA_ELEVEN - 0.2
    meta = eleven.ritmo(eleven.voz_id(tipo_voz)) * objetivo   # caracteres que caben
    factor, guion, bloques = 1.0, None, []
    for intento in range(3):
        guion = g.escribir_guion(prev, hoy, texto_aemet, factor, VOCES[tipo_voz]["presenta"])
        bloques = secuencia(guion)
        largo = eleven.longitud_hablada([guion["segmentos"][s] for s in bloques])
        log.info("Guion %d (%s): %d caracteres hablados (objetivo ≈ %d)", intento + 1, guion.get("origen"), largo, meta)
        if abs(largo - meta) / meta <= 0.08 or guion.get("origen") != "claude":
            break
        factor *= meta / largo
    recortar_si_largo(guion, bloques, largo, meta)
    textos = [guion["segmentos"][s] for s in bloques]
    wav, dur, lim, pal = eleven.sintetizar(textos, tipo_voz, trabajo, "1")
    if not 0.88 * objetivo <= dur <= 1.12 * objetivo and guion.get("origen") == "claude":
        # Muy lejos de la duración (raro): un segundo intento con el ritmo ya corregido
        log.info("Toma de %.1f s (objetivo %.1f): se ajusta el guion y se repite una vez", dur, objetivo)
        guion = g.escribir_guion(prev, hoy, texto_aemet, factor * objetivo / dur, VOCES[tipo_voz]["presenta"])
        bloques = secuencia(guion)
        textos = [guion["segmentos"][s] for s in bloques]
        wav, dur, lim, pal = eleven.sintetizar(textos, tipo_voz, trabajo, "2")
    return guion, bloques, wav, dur, lim, pal


MAXIMO_ABSOLUTO = 100.0   # ningún vídeo pasa de 1 minuto 40...
MAXIMO_CON_AVISOS = 145.0   # ...salvo con avisos naranja o rojo, para explicarlos bien (hasta ~2:25, nunca 3 min)
HAY_AVISOS_GRAVES = [False]


MAXIMO_ESPECIAL = [0.0]   # semanal, media semana y finde: hasta 2:30 (los fija especiales)


def maximo_absoluto() -> float:
    return max(MAXIMO_ESPECIAL[0], MAXIMO_CON_AVISOS if HAY_AVISOS_GRAVES[0] else MAXIMO_ABSOLUTO)


def recortar_si_largo(guion: dict, bloques: list[str], largo: float, meta: float):
    """Si el guion no cabe en el máximo (1:40, o ~2:25 con avisos naranja/rojo), se recortan frases; solo lo que sobra."""
    cabe = meta * (maximo_absoluto() - INICIO - COLA_ELEVEN - 1.5) / (DURACION_OBJETIVO - INICIO - COLA_ELEVEN - 0.2)
    if largo > cabe:
        from .especiales import _recortar
        _recortar(guion, bloques, cabe / largo)


def _alargar(nuevo_max: float):
    """Sube el máximo de duración del vídeo en curso (en este módulo y en el de especiales)."""
    import sys
    global DURACION_MAX
    DURACION_MAX = nuevo_max
    for nombre in ("tiempo.especiales", "__main__"):   # «python -m tiempo.especiales» lo carga como __main__
        m = sys.modules.get(nombre)
        if m is not None and hasattr(m, "DURACION_MAX"):
            m.DURACION_MAX = nuevo_max


AVISO_VOZ = RAIZ / "aviso_voz.txt"


def avisar_voz_gratuita(motivo: str, que: str):
    """Deja constancia para que el workflow falle al final (y llegue el correo de GitHub) si se publicó con la voz
    gratuita en vez de la de ElevenLabs."""
    try:
        AVISO_VOZ.write_text(f"{que}: se usó la voz gratuita en vez de ElevenLabs ({motivo})", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def plan_eleven(bloques, wav, dur, lim, pal):
    """Encaja la toma en 65-70 s: ajuste fino con atempo (sin cambiar el tono) y cola al final."""
    max_habla = DURACION_MAX - 0.6 - INICIO - COLA_ELEVEN
    min_habla = DURACION_MIN + 0.4 - INICIO - 4.0   # como mucho 4 s de tarjeta final
    tempo = 1.0
    if dur > max_habla:
        tempo = dur / max_habla
    elif dur < min_habla:
        tempo = max(dur / min_habla, 0.92)
    if tempo > 1.06:
        # Se alarga el vídeo en vez de acelerar la voz (o caer en la voz gratuita)... pero NUNCA más de 1:40
        tempo = 1.0
        nuevo_max = INICIO + dur + COLA_ELEVEN + 0.8
        if nuevo_max > maximo_absoluto():
            tempo = dur / (maximo_absoluto() - 0.8 - INICIO - COLA_ELEVEN)
            if tempo > 1.15:
                raise RuntimeError(f"La locución dura {dur:.1f} s: no cabe en {maximo_absoluto():.0f} s")
            nuevo_max = maximo_absoluto()
        log.warning("Locución larga (%.1f s): el vídeo se alarga a %.1f s", dur, nuevo_max)
        _alargar(nuevo_max)
        max_habla = DURACION_MAX - 0.6 - INICIO - COLA_ELEVEN
    if abs(tempo - 1) > 0.002:
        log.info("Ajustando la toma x%.3f", tempo)
        wav = voz.acelerar(wav, tempo)
        dur = voz.duracion(wav)
        lim = [(a / tempo, b / tempo) for a, b in lim]
        pal = [[(a / tempo, b / tempo, w) for a, b, w in p] for p in pal]
    plan = [{"seg": s, "inicio": INICIO + a, "fin": INICIO + b, "wav": None,
             "palabras": [(INICIO + x, INICIO + y, w) for x, y, w in p]} for s, (a, b), p in zip(bloques, lim, pal)]
    plan[-1]["fin"] = INICIO + dur
    total = round(max(INICIO + dur + COLA_ELEVEN, DURACION_MIN + 0.4) * FPS) / FPS
    if not DURACION_MIN + 0.2 <= total <= DURACION_MAX - 0.2:
        raise RuntimeError(f"Duración fuera de rango: {total:.2f} s")
    return plan, total, wav


def _habla_objetivo(n_bloques: int) -> float:
    return DURACION_OBJETIVO - INICIO - PAUSA * (n_bloques - 1) - COLA_MIN - 0.3


def generar_locucion(prev, hoy, texto_aemet, trabajo: Path, demo: bool, tipo_voz: str = "masculina",
                     plantilla: bool = False):
    """Genera la voz y ajusta su VELOCIDAD (no las pausas) para que encaje en 65-70 s."""
    factor, mejor = 1.0, None
    for intento in range(3):
        guion = (g.guion_plantilla(prev, hoy, factor) if demo or plantilla
                 else g.escribir_guion(prev, hoy, texto_aemet, factor, VOCES[tipo_voz]["presenta"]))
        if plantilla:
            guion["origen"] = "plantilla"
        # Gancho, regiones en orden de relevancia, recompensa final y despedida
        bloques = secuencia(guion)
        objetivo = _habla_objetivo(len(bloques))
        vel = voz.velocidad_base()
        for ajuste in range(3):
            wavs = [voz.sintetizar(guion["segmentos"][s], trabajo / f"{intento}_{ajuste}_{s}.mp3", demo, vel)
                    for s in bloques]
            durs = [voz.duracion(w) for w in wavs]
            habla = sum(durs)
            log.info("Guion %d (%s), velocidad %+d%%: %d palabras, %.1f s de voz (objetivo %.1f s)",
                     intento + 1, guion.get("origen", "plantilla"), vel,
                     sum(len(guion["segmentos"][s].split()) for s in bloques), habla, objetivo)
            mejor = (guion, bloques, wavs, durs)
            if abs(habla - objetivo) <= 1.0:
                return mejor
            # La duración es inversamente proporcional a la velocidad
            nueva = round((1 + vel / 100) * habla / objetivo * 100 - 100)
            if not VEL_MIN <= nueva <= VEL_MAX:
                limite = min(max(nueva, VEL_MIN), VEL_MAX)
                if limite == vel:
                    break  # haría falta una voz demasiado lenta o rápida: se cambia la longitud del guion
                vel = limite
                continue
            vel = nueva
        # Guion demasiado corto o largo para una velocidad natural: se pide otro de distinta longitud
        factor *= objetivo * (1 + vel / 100) / (habla * (1 + voz.velocidad_base() / 100))
    return mejor


def planificar(bloques, wavs, durs):
    """Coloca los bloques con pausas fijas y garantiza que el total quede entre 65 y 70 s."""
    n = len(bloques)
    habla = sum(durs)
    fijo = INICIO + PAUSA * (n - 1) + COLA_MIN
    limite = DURACION_MAX - 0.8
    if habla + fijo > limite:  # último recurso: acelerar un poco sin cambiar el tono
        tempo = habla / (limite - fijo)
        if tempo > 1.12:
            raise RuntimeError(f"La locución dura {habla:.1f} s: demasiado larga")
        log.info("Acelerando la voz x%.3f para no pasar de %.0f s", tempo, DURACION_MAX)
        wavs = [voz.acelerar(w, tempo) for w in wavs]
        durs = [voz.duracion(w) for w in wavs]
    plan, t = [], INICIO
    for s, w, d in zip(bloques, wavs, durs):
        plan.append({"seg": s, "inicio": t, "fin": t + d, "wav": w})
        t += d + PAUSA
    # Lo que sobre se queda al final, con la tarjeta de "¡Sígueme!" y la música
    total = max(plan[-1]["fin"] + COLA_MIN, DURACION_MIN + 0.5)
    total = round(total * FPS) / FPS
    if not DURACION_MIN + 0.2 <= total <= DURACION_MAX - 0.2:
        raise RuntimeError(f"Duración fuera de rango: {total:.2f} s")
    return plan, total


def _nota_aviso_ya_publicado(hoy: date) -> str:
    """Si hoy ya se han publicado vídeos de aviso, el parte no compite con ellos: abre con otra cosa y remite al aviso."""
    try:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo
        dias = {_dt.now(ZoneInfo("Europe/Madrid")).date().isoformat(), hoy.isoformat()}
        titulares = []
        for d in sorted(dias):
            for ruta in sorted((RAIZ / "historial_especiales").glob(f"aviso-{d}*.json")):
                h = json.loads(ruta.read_text(encoding="utf-8"))
                if h.get("tiktok") or h.get("youtube") or h.get("instagram"):
                    t = (h.get("caption") or h.get("titular") or "").split("\n")[0].replace("⚠️", "").strip()
                    if t and t not in titulares:
                        titulares.append(t)
        if not titulares:
            return ""
        log.info("Ya hay %d vídeo(s) de aviso publicados: el parte abre con otra cosa", len(titulares))
        return ("\n\nYA HAY VÍDEO DE AVISO PUBLICADO (" + " · ".join(titulares[-4:]) + "). Quien nos sigue ya lo ha "
                "visto, así que este parte NO lo repite (esto manda sobre «Fenómeno que abre el vídeo» de arriba): el gancho, el titular y la primera línea de la descripción NO "
                "abren con ese aviso; abren con lo que ese vídeo no cuenta y le importa a media España (el resto del "
                "país, qué pasa después, cuándo mejora, el contraste del día). El tramo «aviso» se mantiene, con todas "
                "sus zonas, pero contado con otras palabras y otro arranque que el vídeo del aviso, y termina "
                "remitiendo a él en una frase corta («el detalle, en el vídeo del aviso que tienes en el perfil»).")
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo comprobar si ya hay vídeo de aviso publicado: %s", e)
        return ""


def construir(hoy: date, salida: Path, demo: bool = False) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "trabajo"
    trabajo.mkdir(exist_ok=True)
    prev, texto_aemet = previsiones_demo() if demo else obtener_previsiones(hoy)
    (salida / "datos.json").write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    # Gancho de los primeros segundos: fenómeno del día con datos reales (avisos de AEMET, rachas, lluvia...)
    from . import gancho as gancho_mod
    avisos = [] if demo else gancho_mod.avisos_de_hoy(hoy)
    from .especiales import marcar_tormentas
    marcar_tormentas(prev, avisos)   # aviso por tormentas → icono de tormenta (no de lluvia) en esas ciudades
    fen = gancho_mod.fenomeno_del_dia(prev, avisos)
    g.GANCHO, g.GANCHO_TEXTO = fen, gancho_mod.para_guion(fen)
    if not demo:   # avisos de todos los niveles (coloreados en el mapa) y oleaje fuerte: también al guion
        from .especiales import texto_avisos
        from .fuentes import COSTA, nieve, oleaje, texto_nieve, texto_oleaje
        cuando = "mañana" if os.environ.get("VISPERA") else "hoy"
        olas_hoy, nieve_hoy = oleaje(hoy), nieve(hoy)
        g.GANCHO_TEXTO += texto_avisos({cuando: avisos} if avisos else {}) + texto_oleaje({cuando: olas_hoy}) \
            + texto_nieve({cuando: nieve_hoy})
        try:   # el pueblo más frío / más caluroso, no solo la capital (y lo medido esta madrugada)
            from . import pueblos
            from datetime import datetime as _dt
            nota_p, EXTREMOS_PUEBLOS[0] = pueblos.texto(prev, hoy, _dt.now(pueblos.TZ).date(), cuando)
            g.GANCHO_TEXTO += nota_p
            g.EXTREMOS = EXTREMOS_PUEBLOS[0]
        except Exception as e:  # noqa: BLE001
            log.warning("Extremos en pueblos no disponibles: %s", e)
        try:   # AEMET frente a los modelos: dónde dudan y dónde coinciden todos
            from . import contraste
            g.GANCHO_TEXTO += contraste.texto(prev, cuando)
        except Exception as e:  # noqa: BLE001
            log.warning("Contraste de fuentes no disponible: %s", e)
        # el bloque «general» (más calor / más frío) lleva el mapa de temperaturas en colores, como en la tele; la
        # lluvia en colores sale en los tramos de aviso y de borrasca
        g.GANCHO_TEXTO += ("\n\nMAPA DE TEMPERATURAS: en el bloque «general» sale España coloreada por la máxima, con "
                           "las cifras sobre las ciudades. Puedes decir «mira el mapa: el sur, en rojo»…")
        SISTEMA[0] = None
        g.POST_GUION[:] = []
        try:   # borrascas (con nombre o no), temporales y DANAs que entran: su evolución por horas
            from . import sistemas
            s_ = sistemas.detectar(hoy, " ".join([texto_aemet or ""] + [f"{x.get('descripcion', '')}" for x in avisos]))
            rachas = max((c.get("racha") or 0) for c in prev) if prev else 0
            if s_ and (s_.get("nombre") or s_["distancia"] == 0 or (s_["tipo"] == "borrasca" and s_["minimo"] <= 1000)
                       or rachas >= 70):
                capa_s, notas = sistemas.preparar(s_, hoy)
                etiqueta = sistemas.titulo_sistemas(s_)
                SISTEMA[0] = (capa_s, etiqueta)
                g.GANCHO_TEXTO += sistemas.texto_guion(s_, cuando, capa_s.duracion + 0.8) + (
                    " Datos del tramo: " + "; ".join(notas) + "." if notas else "")
        except Exception as e:  # noqa: BLE001
            log.warning("Seguimiento de borrascas/DANAs no disponible: %s", e)
        graves = [x for x in avisos if x["nivel"] in ("naranja", "rojo") and x.get("poligonos")]
        # Duración: lo que mejor funciona ronda los 70 s; solo se alarga cuando de verdad hay mucho que contar
        g.GANCHO_TEXTO += ("\n\nDURACIÓN: el vídeo debe rondar los 70 segundos: respeta las palabras de cada bloque. "
                           + ("Hoy hay aviso naranja o rojo: puedes alargar un poco (hasta un 20 % más) para el tramo de "
                              "aviso." if graves else "No te alargues: si sobra algo, recorta lo menos importante."))
        HAY_AVISOS_GRAVES[0] = bool(graves)
        if graves:   # tramo «aviso»: un zoom por cada zona distante, con sus núcleos señalados
            from .especiales import agrupar_lejanos, ciudades_zoom, nucleos_afectados, sitios_aviso, _campo_aviso
            racimos = list(zip(("aviso", "aviso2", "aviso3"), agrupar_lejanos(graves)))
            AVISO_GRAVE[0] = racimos
            CAMPO_PARTE[0] = _campo_aviso(racimos[0][1], hoy)
            if CAMPO_PARTE[0]:
                top = sorted(CAMPO_PARTE[0][1].items(), key=lambda t: -t[1])[:5]
                g.GANCHO_TEXTO += ("\n\nEn el tramo «aviso», tras las zonas sale el mapa de lluvia acumulada en colores; "
                                   "lluvia máxima prevista por zona (l/m²): " + ", ".join(f"{n} {v}" for n, v in top)
                                   + ". Di cuánta lluvia y dónde más (cifras redondas).")
            g.GANCHO_TEXTO += ("\n\nTRAMO DE AVISO (va justo después del gancho). " + (
                "Hay avisos en zonas DISTANTES: escribe un bloque por zona, en este orden; en pantalla se hace zoom a "
                "cada una cuando se habla de ella (y se aleja y vuelve a acercarse entre una y otra). "
                if len(racimos) > 1 else "") + "Todo lo que nombres se señala en el mapa.")
            from .especiales import REGLA_ZONA_ENTERA, asegurar_zona_entera, comarcas_de, variar_discurso

            def _zona_entera(guion_, racimos=racimos):
                variar_discurso(guion_, graves)   # sin la coletilla de «daños graves o catastróficos»
                for clave_, r_ in racimos:
                    if guion_["segmentos"].get(clave_):
                        guion_["segmentos"][clave_] = asegurar_zona_entera(guion_["segmentos"][clave_], r_)
            g.POST_GUION[:] = [_zona_entera]
            g.GANCHO_TEXTO += (" No uses la coletilla de AEMET «daños graves / muy graves o catastróficos»: cuenta el "
                               "peligro con lo concreto de ese fenómeno, como posibilidad y cada día de una forma.")
            g.GANCHO_TEXTO += " " + REGLA_ZONA_ENTERA + (
                " comarcas_de_la_zona: " + "; ".join(f"{z} = {', '.join(c)}" for z, c in comarcas_de(graves).items()) + "."
                if comarcas_de(graves) else "")
            for clave, r in racimos:
                g.GANCHO_TEXTO += (
                    f"\n- \"{clave}\" (unas {34 if clave == 'aviso' and CAMPO_PARTE[0] else 26} palabras): aviso "
                    + "/".join(dict.fromkeys(x["nivel"] for x in r)) + " por "
                    + "/".join(dict.fromkeys(x["fenomeno"].lower() for x in r))
                    + ". Nombra TODAS las zonas: " + "; ".join(", ".join(sitios_aviso(x)) for x in r)
                    + ". Núcleos señalados: " + ", ".join(c["nombre"] for c in nucleos_afectados(r)[:8])
                    + ". Atentas también, por si se desvía: "
                    + ", ".join(c["nombre"] for c in ciudades_zoom(r, [], n_amarillo=0, n_ref=5))
                    + " (con su nivel). Cuándo y lo más grave que se espera, con un consejo corto.")
            g.GANCHO_TEXTO += _nota_aviso_ya_publicado(hoy)
        gra =[c["nombre"] for c in prev if c.get("granizo")][:3]
        if gra:
            g.GANCHO_TEXTO += (f" POSIBLE GRANIZO en {', '.join(gra)} (sale en el mapa): menciónalo con prudencia "
                               "('no se descarta granizo') y un consejo (el coche a cubierto).")
        MAR_NIEVE_HOY = ([{"zona": z, "olas": m, **next((dict(lat=la, lon=lo) for zz, la, lo in COSTA if zz == z), {})}
                          for z, m in olas_hoy], nieve_hoy)
    else:
        MAR_NIEVE_HOY = ([], [])
    log.info("Gancho: %s · %s · %s", fen["insignia"], fen["dato"], fen["ciudades"])
    # Satélite con el viento animado: solo los días que lo merecen (borrasca, DANA, aviso naranja/rojo...)
    sat = None
    if not demo or os.environ.get("SATELITE_DEMO"):
        try:
            from . import satelite
            toca, motivo = satelite.merece_satelite(hoy, fen)
            if toca:
                sat, info_sat = satelite.preparar(hoy)
                log.info("Satélite en el vídeo (%s): %s", motivo, info_sat)
                g.GANCHO_TEXTO += (f" HOY SE VE EL SATÉLITE ({motivo}): justo después de la intro aparece la foto de "
                                   "satélite con el viento animado; en la primera frase del primer bloque regional "
                                   "invita a mirarlo con naturalidad ('mira el satélite: así entra...').")
        except Exception as e:  # noqa: BLE001
            log.warning("Sin satélite hoy: %s", e)
            sat = None

    from .config import voz_para
    tipo_voz = os.environ.get("VOZ_TIPO") or voz_para("parte", hoy)   # diario: siempre femenina (aunque haya aviso)
    voz.elegir_voz(VOCES[tipo_voz])
    log.info("Voz del día: %s (%s)", tipo_voz, VOCES[tipo_voz]["edge"])
    plan, motor = None, "edge-tts"
    if not demo and eleven.disponible(tipo_voz):
        try:
            guion, bloques, wav, dur, lim, pal = generar_eleven(prev, hoy, texto_aemet, trabajo, tipo_voz)
            plan, total, wav = plan_eleven(bloques, wav, dur, lim, pal)
            trozos, motor = [(wav, INICIO)], f"elevenlabs ({eleven.modelo()})"
        except Exception as e:  # noqa: BLE001
            log.warning("ElevenLabs no disponible (%s): se usa la voz gratuita", e)
            avisar_voz_gratuita(str(e)[:200], "Parte diario")
            plan = None
    if plan is None:
        guion, bloques, wavs, durs = generar_locucion(prev, hoy, texto_aemet, trabajo, demo, tipo_voz)
        try:
            plan, total = planificar(bloques, wavs, durs)
        except RuntimeError as e:
            if not os.environ.get("PERMITIR_PLANTILLA"):
                raise
            log.warning("%s → se usa la plantilla", e)  # red de seguridad: el parte sale igual
            guion, bloques, wavs, durs = generar_locucion(prev, hoy, texto_aemet, trabajo, demo, tipo_voz,
                                                          plantilla=True)
            plan, total = planificar(bloques, wavs, durs)
        trozos = [(p["wav"], p["inicio"]) for p in plan]
    for p in plan:
        p["texto"] = guion["segmentos"][p["seg"]]
    log.info("Voz: %s · orden: %s", motor, " → ".join(p["seg"] for p in plan))

    audio = trabajo / "pista.wav"
    voz.montar_pista(trozos, total, musica.generar(total, hoy), audio)

    extremos = EXTREMOS_PUEBLOS[0] or {"calor": max(prev, key=lambda c: c["tmax"]),
                                       "frio": min(prev, key=lambda c: c["tmin"])}
    prev_mapa = g.prev_para_mapa(prev, guion["segmentos"])   # las ciudades que se nombran son las que se ven
    capa_t = None
    if not demo:
        try:   # «general»: temperaturas en colores con las cifras encima (sin pastillas)
            from . import campos, rotacion
            from .guion import SIEMPRE_EN_MAPA
            orden_t = sorted(prev_mapa + [c for c in prev if c not in prev_mapa],
                             key=lambda c: (c["nombre"] not in SIEMPRE_EN_MAPA, not rotacion.es_capital(c["nombre"])))
            capa_t = campos.capa_temperaturas(hoy, orden_t)
        except Exception as e:  # noqa: BLE001
            log.warning("Sin mapa de temperaturas: %s", e)
    comp = Compositor(prev_mapa, plan, total, g.fecha_larga(hoy).upper(), extremos, guion.get("titular", ""), fecha=hoy,
                      gancho=fen, satelite=sat,
                      capas_fondo={**(_capas_parte(avisos) or {}), **({"general": MAPA_EXTRA[0][0]} if MAPA_EXTRA[0] else {}),
                                   **({"general": capa_t} if capa_t else {})},
                      capas_encima=_capas_encima(MAR_NIEVE_HOY, avisos, prev_mapa),
                      **_kwargs_juntos(_kwargs_juntos(
                          _kwargs_aviso(AVISO_GRAVE[0] if "aviso" in guion["segmentos"] else None,
                                        guion["segmentos"]),
                          {"pills": {"general": MAPA_EXTRA[0][1]}} if MAPA_EXTRA[0] else {}),
                          _kwargs_juntos(_kwargs_sistema() if "sistema" in guion["segmentos"] else {},
                                         {"sin_marcadores": ("general",), "pills": {"general": "MÁXIMAS (°C)"}}
                                         if capa_t else {})))
    video = salida / f"tiempo_{hoy.isoformat()}.mp4"
    log.info("Renderizando %.2f s de vídeo…", total)
    renderizar(comp, audio, video, total)

    real = voz.duracion(video)
    if not DURACION_MIN <= real <= DURACION_MAX:
        raise RuntimeError(f"El vídeo final dura {real:.2f} s (debe estar entre 65 y 70)")
    general = next((p for p in plan if p["seg"] == "general"), plan[0])
    caption = descripcion.construir(prev, hoy, guion["caption"] if guion.get("origen") in ("claude", "manual") else None)
    meta = {"fecha": hoy.isoformat(), "duracion": round(real, 2), "video": str(video), "caption": caption,
            "portada_ms": 0,  # el primer fotograma es la portada con la fecha
            "origen_guion": guion.get("origen"),
            "motor_voz": motor,
            "titular": guion.get("titular"),
            "voz": tipo_voz,
            "guion": {p["seg"]: p["texto"] for p in plan}}
    (salida / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Vídeo listo: %s (%.2f s)", video, real)
    return meta


def publicar_youtube(meta: dict, hoy: date):
    """YouTube Shorts: público y automático. Un fallo aquí no afecta a TikTok."""
    from . import youtube
    if not youtube.hay_credenciales():
        log.info("YouTube sin configurar: no se sube")
        return
    try:
        titulo, desc, tags = youtube.textos(meta["caption"], meta.get("titular"), g.fecha_larga(hoy),
                                            meta.get("tipo_youtube") or ("manana" if os.environ.get("VISPERA") else "hoy"))
        meta["youtube"] = youtube.subir_con_reintentos(Path(meta["video"]), titulo, desc, tags)
    except Exception as e:  # noqa: BLE001
        log.error("No se pudo subir a YouTube: %s", e)
        meta["youtube_error"] = str(e)[:300]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="datos inventados, sin claves y sin voz")
    ap.add_argument("--publicar", action="store_true", help="subir a TikTok")
    ap.add_argument("--esperar", action="store_true", help="esperar a las 7:30 (Madrid) antes de publicar")
    ap.add_argument("--vispera", action="store_true",
                    help="el parte de MAÑANA, publicado esta noche a las 20:30 (el de mañana a las 7:30 ya no sale)")
    ap.add_argument("--prueba", action="store_true",
                    help="prueba real: genera el vídeo y lo sube a YouTube como PRIVADO; ni TikTok ni historial")
    ap.add_argument("--salida", default=str(RAIZ / "salida"))
    ap.add_argument("--fecha", help="AAAA-MM-DD (por defecto, hoy en Madrid)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hoy = date.fromisoformat(a.fecha) if a.fecha else ahora().date()
    if a.vispera:
        from datetime import timedelta as _td
        os.environ["VISPERA"] = "1"
        hoy = ahora().date() + _td(days=1)
        if (RAIZ / "historial" / f"{hoy.isoformat()}.json").exists():
            log.info("El parte de mañana ya está publicado")
            return
    meta = construir(hoy, Path(a.salida), demo=a.demo)
    if a.prueba:
        # "prueba youtube publico": se sube público a YouTube (sin TikTok ni historial)
        os.environ["YT_PRIVACIDAD"] = "public" if os.environ.get("PRUEBA_PUBLICA") else "private"
        publicar_youtube(meta, hoy)
        (Path(a.salida) / "meta.json").write_text(json.dumps({k: v for k, v in meta.items()}, ensure_ascii=False,
                                                             indent=1), encoding="utf-8")
        log.info("Prueba terminada: %s", {k: meta.get(k) for k in ("motor_voz", "youtube", "youtube_error")})
        return
    if not a.demo:
        # Página del móvil con la descripción lista para copiar (docs/hoy.html la lee). Se sube YA, antes de
        # esperar a la hora de publicación, para que el texto esté listo a la vez que el borrador.
        try:
            previo = json.loads((RAIZ / "docs" / "hoy.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            previo = {}
        extras = previo.get("extras", []) if previo.get("fecha") == hoy.isoformat() else []
        (RAIZ / "docs" / "hoy.json").write_text(json.dumps(
            {"fecha": hoy.isoformat(), "caption": meta["caption"], "voz": meta.get("voz"),
             "duracion": meta["duracion"], "extras": extras}, ensure_ascii=False, indent=1), encoding="utf-8")
        from .repo import subir
        subir([RAIZ / "docs" / "hoy.json"], f"Texto del parte del {hoy.isoformat()}")

    if not a.demo:   # control de calidad antes de publicar: con un fallo grave el parte no sale (y se avisa)
        try:
            from . import control
            res_ = control.revisar(Path(meta["video"]), dur_max=DURACION_MAX + 50)
            meta["control"] = res_
            if control.bloquea(res_):
                log.error("NO se publica: %s", "; ".join(res_["graves"]))
                meta["no_publicado"] = "; ".join(res_["graves"])
                a.publicar = False
        except Exception as e:  # noqa: BLE001
            log.warning("Control de calidad no disponible: %s", e)
    from . import uploadpost
    from .tiktok import hay_credenciales
    faltan = hay_credenciales() if a.publicar else []
    if a.publicar and uploadpost.disponible():
        # Publicación pública y automática (Upload-Post); si falla, borrador como siempre
        if a.esperar:
            esperar_hasta_publicacion()
        try:
            meta["primer_comentario"] = uploadpost.comentario_pueblo(hoy)
            meta["tiktok"] = uploadpost.publicar_tiktok(Path(meta["video"]), meta["caption"], "tiempo",
                                                        primer_comentario=meta["primer_comentario"])
            from .config import registrar_voz
            registrar_voz(meta.get("voz", ""), hoy)
        except Exception as e:  # noqa: BLE001
            log.error("Upload-Post falló (%s): se envía como borrador", e)
            from .tiktok import publicar_con_reintentos
            if not faltan:
                meta["tiktok"] = publicar_con_reintentos(Path(meta["video"]), meta["caption"], meta["portada_ms"])
    elif a.publicar and faltan:
        log.warning("No se publica: faltan los secretos %s. El vídeo queda como artefacto de la ejecución.",
                    ", ".join(faltan))
    elif a.publicar:
        from .tiktok import publicar_con_reintentos
        if a.esperar:
            esperar_hasta_publicacion()
        res = publicar_con_reintentos(Path(meta["video"]), meta["caption"], meta["portada_ms"])
        meta["tiktok"] = res
        log.info("Publicado en TikTok: %s", res)
    if a.publicar:
        publicar_youtube(meta, hoy)
        uploadpost.instagram_seguro(meta)   # también como Reel en Instagram
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## Parte del {hoy.isoformat()} ({meta['duracion']} s)\n\n"
                    f"**Texto para el post de TikTok** (cópialo al publicar):\n\n```\n{meta['caption']}\n```\n\n"
                    f"Guion: {meta.get('origen_guion')}\n")
    hist = RAIZ / "historial" / f"{hoy.isoformat()}.json"
    if not a.demo and a.publicar:   # un borrador sin publicar no cuenta como hecho
        hist.parent.mkdir(exist_ok=True)
        hist.write_text(json.dumps({k: v for k, v in meta.items() if k != "video"}, ensure_ascii=False, indent=1),
                        encoding="utf-8")


def publicar_revisado(meta: dict):
    """Publica un parte ya generado y revisado (flujo publicar-hecho.yml con tipo «parte»)."""
    from . import uploadpost
    from .config import registrar_voz
    hoy = date.fromisoformat(meta["fecha"])
    meta["primer_comentario"] = uploadpost.comentario_pueblo(hoy)
    meta["tiktok"] = uploadpost.publicar_tiktok(Path(meta["video"]), meta["caption"], "tiempo",
                                                primer_comentario=meta["primer_comentario"])
    registrar_voz(meta.get("voz", ""), hoy)
    publicar_youtube(meta, hoy)
    uploadpost.instagram_seguro(meta)
    hist = RAIZ / "historial" / f"{hoy.isoformat()}.json"
    hist.parent.mkdir(exist_ok=True)
    hist.write_text(json.dumps({k: v for k, v in meta.items() if k != "video"}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return meta


if __name__ == "__main__":
    main()
