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


def secuencia(guion: dict) -> list[str]:
    """Gancho, regiones de más a menos relevantes, la 'recompensa' (más calor y más frío) y la despedida."""
    orden = guion.get("orden") or [s for s in SEGMENTOS if s not in ("intro", "general", "cierre")]
    return [s for s in ("intro", *orden, "general", "cierre") if str(guion["segmentos"].get(s, "")).strip()]


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


def plan_eleven(bloques, wav, dur, lim, pal):
    """Encaja la toma en 65-70 s: ajuste fino con atempo (sin cambiar el tono) y cola al final."""
    max_habla = DURACION_MAX - 0.6 - INICIO - COLA_ELEVEN
    min_habla = DURACION_MIN + 0.4 - INICIO - 4.0   # como mucho 4 s de tarjeta final
    tempo = 1.0
    if dur > max_habla:
        tempo = dur / max_habla
    elif dur < min_habla:
        tempo = max(dur / min_habla, 0.92)
    if tempo > 1.15:
        raise RuntimeError(f"La locución dura {dur:.1f} s: demasiado larga")
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


def construir(hoy: date, salida: Path, demo: bool = False) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "trabajo"
    trabajo.mkdir(exist_ok=True)
    prev, texto_aemet = previsiones_demo() if demo else obtener_previsiones(hoy)
    (salida / "datos.json").write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    # Gancho de los primeros segundos: fenómeno del día con datos reales (avisos de AEMET, rachas, lluvia...)
    from . import gancho as gancho_mod
    avisos = [] if demo else gancho_mod.avisos_de_hoy(hoy)
    fen = gancho_mod.fenomeno_del_dia(prev, avisos)
    g.GANCHO, g.GANCHO_TEXTO = fen, gancho_mod.para_guion(fen)
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
    tipo_voz = os.environ.get("VOZ_TIPO") or voz_para("parte", hoy, importante=bool(fen.get("nivel")))
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

    extremos = {"calor": max(prev, key=lambda c: c["tmax"]), "frio": min(prev, key=lambda c: c["tmin"])}
    comp = Compositor(prev, plan, total, g.fecha_larga(hoy).upper(), extremos, guion.get("titular", ""), fecha=hoy,
                      gancho=fen, satelite=sat)
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
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## Parte del {hoy.isoformat()} ({meta['duracion']} s)\n\n"
                    f"**Texto para el post de TikTok** (cópialo al publicar):\n\n```\n{meta['caption']}\n```\n\n"
                    f"Guion: {meta.get('origen_guion')}\n")
    hist = RAIZ / "historial" / f"{hoy.isoformat()}.json"
    if not a.demo:
        hist.parent.mkdir(exist_ok=True)
        hist.write_text(json.dumps({k: v for k, v in meta.items() if k != "video"}, ensure_ascii=False, indent=1),
                        encoding="utf-8")


if __name__ == "__main__":
    main()
