"""Resumen económico: datos → guion → voz → vídeo (65–70 s) → espera a las 7:30 (o 21:00) → TikTok.

  python -m economia.main --demo                 # vídeo de prueba con datos inventados y sin voz
  python -m economia.main                        # vídeo real (datos de internet), sin publicar
  python -m economia.main --publicar --esperar   # lo que hace GitHub Actions cada mañana
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path

from tiempo import musica, voz
from tiempo.main import VEL_MAX, VEL_MIN, _habla_objetivo, planificar
from tiempo.horario import ahora
from tiempo.video import renderizar
from tiempo.config import DURACION_MAX, DURACION_MIN, DURACION_OBJETIVO, FPS

from . import descripcion, locucion
from . import guion as g
from .agenda import agenda_demo, obtener_agenda
from .config import HISTORIAL, RAIZ, SEGMENTOS, VOCES, tipo_de_dia, voz_del_dia
from .horario import esperar_hasta_publicacion
from .mercados import mercados_demo, obtener_mercados
from .noticias import obtener_titulares
from .video import Compositor

log = logging.getLogger("economia")


def generar_locucion(merc, agenda, titulares, hoy, modo, trabajo: Path, demo: bool, tipo_voz: str):
    factor, mejor = 1.0, None
    for intento in range(3):
        guion = (g.guion_plantilla(merc, agenda, hoy, modo, factor) if demo else
                 g.escribir_guion(merc, agenda, titulares, hoy, modo, factor, VOCES[tipo_voz]["presenta"]))
        bloques = [s for s in SEGMENTOS if str(guion["segmentos"].get(s, "")).strip()]
        objetivo = _habla_objetivo(len(bloques))
        vel = voz.velocidad_base()
        for ajuste in range(3):
            wavs = [voz.sintetizar(guion["segmentos"][s], trabajo / f"{intento}_{ajuste}_{s}.mp3", demo, vel)
                    for s in bloques]
            durs = [voz.duracion(w) for w in wavs]
            habla = sum(durs)
            log.info("Guion %d (%s), velocidad %+d%%: %d palabras, %.1f s de voz (objetivo %.1f s)", intento + 1,
                     guion.get("origen", "plantilla"), vel,
                     sum(len(guion["segmentos"][s].split()) for s in bloques), habla, objetivo)
            mejor = (guion, bloques, wavs, durs)
            # Hasta 3 s por debajo del objetivo también vale: el vídeo sigue pasando de 65 s
            if abs(habla - objetivo) <= 1.0 or objetivo - 3.0 <= habla <= objetivo:
                return mejor
            nueva = round((1 + vel / 100) * habla / objetivo * 100 - 100)
            if not VEL_MIN <= nueva <= VEL_MAX:
                limite = min(max(nueva, VEL_MIN), VEL_MAX)
                if limite == vel:
                    break
                vel = limite  # se prueba con la velocidad máxima/mínima permitida antes de cambiar el guion
                continue
            vel = nueva
        if guion.get("origen") == "plantilla" and habla < objetivo:
            return mejor  # la plantilla no se alarga: el tiempo sobrante queda en la tarjeta final
        factor *= objetivo * (1 + vel / 100) / (habla * (1 + voz.velocidad_base() / 100))
    return mejor


INICIO_C, COLA_C = 0.45, 1.4   # toma continua: arranque tras la portada y cola con la tarjeta final
VEL_BASE = 20                  # un poco más rápida que el canal del tiempo: suena más activa


def generar_continua(merc, agenda, titulares, hoy, modo, trabajo: Path, tipo_voz: str, plantilla=False):
    """Guion + una sola toma de voz ajustada (velocidad y longitud) para que el vídeo dure 65-70 s."""
    voz_edge = os.environ.get("VOZ_EDGE") or VOCES[tipo_voz]["edge"]
    objetivo = DURACION_OBJETIVO - INICIO_C - COLA_C - 0.2
    factor, mejor = 1.0, None
    for intento in range(3):
        guion = (g.guion_plantilla(merc, agenda, hoy, modo, factor) if plantilla else
                 g.escribir_guion(merc, agenda, titulares, hoy, modo, factor, VOCES[tipo_voz]["presenta"]))
        if plantilla:
            guion["origen"] = "plantilla"
        bloques = [s for s in SEGMENTOS if str(guion["segmentos"].get(s, "")).strip()]
        vel = VEL_BASE
        for ajuste in range(3):
            wav, dur, lim = locucion.toma_completa(guion, bloques, voz_edge, vel, trabajo, f"{intento}{ajuste}")
            log.info("Guion %d (%s), toma continua a %+d%%: %d palabras, %.1f s (objetivo %.1f s)", intento + 1,
                     guion.get("origen"), vel, g._contar(guion), dur, objetivo)
            mejor = (guion, bloques, wav, dur, lim)
            if objetivo - 3.0 <= dur <= objetivo + 0.8:
                return mejor
            nueva = min(max(round((1 + vel / 100) * dur / objetivo * 100 - 100), VEL_MIN), VEL_MAX)
            if nueva == vel:
                break
            vel = nueva
        if plantilla and dur < objetivo:
            return mejor
        factor *= objetivo * (1 + vel / 100) / (dur * (1 + VEL_BASE / 100))
    return mejor


def plan_continuo(bloques, wav, dur, lim):
    limite = DURACION_MAX - 0.8
    if INICIO_C + dur + COLA_C > limite:
        tempo = dur / (limite - INICIO_C - COLA_C)
        if tempo > 1.12:
            raise RuntimeError(f"La locución dura {dur:.1f} s: demasiado larga")
        log.info("Acelerando la toma x%.3f", tempo)
        wav = voz.acelerar(wav, tempo)
        lim = [(a / tempo, b / tempo) for a, b in lim]
        dur = voz.duracion(wav)
    plan = [{"seg": s, "inicio": INICIO_C + a, "fin": INICIO_C + b, "wav": None} for s, (a, b) in zip(bloques, lim)]
    plan[-1]["fin"] = INICIO_C + dur
    total = round(max(INICIO_C + dur + COLA_C, DURACION_MIN + 0.5) * FPS) / FPS
    if not DURACION_MIN + 0.2 <= total <= DURACION_MAX - 0.2:
        raise RuntimeError(f"Duración fuera de rango: {total:.2f} s")
    return plan, total, wav


def _plantilla(merc, agenda, hoy, modo, trabajo, tipo_voz):
    guion = g.guion_plantilla(merc, agenda, hoy, modo)
    guion["origen"] = "plantilla"
    bloques = [s for s in SEGMENTOS if str(guion["segmentos"].get(s, "")).strip()]
    objetivo = _habla_objetivo(len(bloques))
    vel = voz.velocidad_base()
    for ajuste in range(3):
        wavs = [voz.sintetizar(guion["segmentos"][s], trabajo / f"p{ajuste}_{s}.mp3", False, vel) for s in bloques]
        durs = [voz.duracion(w) for w in wavs]
        nueva = min(max(round((1 + vel / 100) * sum(durs) / objetivo * 100 - 100), VEL_MIN), VEL_MAX)
        if abs(sum(durs) - objetivo) <= 1.0 or nueva == vel:
            break
        vel = nueva
    return guion, bloques, wavs, durs


def _fuentes_txt(merc, agenda, titulares) -> str:
    usadas = []
    for a in merc.values():
        if a["fuente"] not in usadas and a["fuente"] != "demo":
            usadas.append(a["fuente"])
    if agenda.get("fuente") == "Forex Factory":
        usadas.append("Forex Factory")
    if titulares:
        usadas.append("prensa económica")
    return "Datos: " + (" · ".join(usadas) if usadas else "demo") + " · pueden llevar retraso"


def construir(hoy: date, salida: Path, demo: bool = False) -> dict:
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "trabajo"
    trabajo.mkdir(exist_ok=True)
    modo = os.environ.get("MODO_DIA") or tipo_de_dia(hoy)
    merc = mercados_demo(hoy) if demo else obtener_mercados()
    agenda = agenda_demo(hoy, modo) if demo else obtener_agenda(hoy, modo)
    if modo == "noche":
        agenda["hoy"] = agenda_demo(hoy)["eventos"] if demo else obtener_agenda(hoy, "diario")["eventos"]
    horas = {"diario": 20, "noche": 14}.get(modo, 40)
    titulares = [] if demo else obtener_titulares(horas=horas)
    (salida / "datos.json").write_text(json.dumps({"mercados": merc, "agenda": agenda, "titulares": titulares},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")

    tipo_voz = os.environ.get("VOZ_TIPO") or voz_del_dia(hoy)
    voz.elegir_voz(VOCES[tipo_voz])
    log.info("Día %s (%s), voz %s", hoy, modo, tipo_voz)
    plan = None
    if not demo:
        # 1) Toma continua (suena seguida y natural)
        for plantilla in (False, True):
            try:
                guion, bloques, wav, dur, lim = generar_continua(merc, agenda, titulares, hoy, modo, trabajo,
                                                                 tipo_voz, plantilla)
                plan, total, wav = plan_continuo(bloques, wav, dur, lim)
                trozos = [(wav, INICIO_C)]
                break
            except Exception as e:  # noqa: BLE001
                log.warning("Toma continua falló (%s): %s", "plantilla" if plantilla else "guion", e)
    if plan is None:
        # 2) Método por bloques (también es el del modo demo y el respaldo si edge-tts falla)
        guion, bloques, wavs, durs = generar_locucion(merc, agenda, titulares, hoy, modo, trabajo, demo, tipo_voz)
        try:
            plan, total = planificar(bloques, wavs, durs)
        except RuntimeError as e:
            log.warning("%s → se usa la plantilla", e)
            guion, bloques, wavs, durs = generar_locucion(merc, agenda, titulares, hoy, modo, trabajo, True,
                                                          tipo_voz) if demo else \
                _plantilla(merc, agenda, hoy, modo, trabajo, tipo_voz)
            plan, total = planificar(bloques, wavs, durs)
        trozos = [(p["wav"], p["inicio"]) for p in plan]
    for p in plan:
        p["texto"] = guion["segmentos"][p["seg"]]

    audio = trabajo / "pista.wav"
    voz.montar_pista(trozos, total, musica.generar(total), audio)
    comp = Compositor(merc, agenda, guion, plan, total, hoy, modo, _fuentes_txt(merc, agenda, titulares))
    video = salida / f"economia_{hoy.isoformat()}{'_noche' if modo == 'noche' else ''}.mp4"
    log.info("Renderizando %.2f s de vídeo…", total)
    renderizar(comp, audio, video, total)
    real = voz.duracion(video)
    if not DURACION_MIN <= real <= DURACION_MAX:
        raise RuntimeError(f"El vídeo final dura {real:.2f} s (debe estar entre 65 y 70)")
    caption = descripcion.construir(merc, agenda, hoy, modo, guion.get("caption") if guion.get("origen") == "claude"
                                    else None)
    meta = {"fecha": hoy.isoformat(), "modo": modo, "duracion": round(real, 2), "video": str(video),
            "caption": caption, "portada_ms": 0, "origen_guion": guion.get("origen"), "voz": tipo_voz,
            "titulares": guion.get("titulares"), "guion": {p["seg"]: p["texto"] for p in plan}}
    (salida / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Vídeo listo: %s (%.2f s, guion %s)", video, real, guion.get("origen"))
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--publicar", action="store_true")
    ap.add_argument("--esperar", action="store_true", help="esperar a la hora de la edición (7:30 o 21:00, Madrid)")
    ap.add_argument("--salida", default=str(RAIZ / "salida_economia"))
    ap.add_argument("--fecha", help="AAAA-MM-DD (por defecto, hoy en Madrid)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hoy = date.fromisoformat(a.fecha) if a.fecha else ahora().date()
    meta = construir(hoy, Path(a.salida), demo=a.demo)
    if not a.demo:
        _guardar_textos(hoy, meta)  # el texto queda en la web antes de la hora, a la vez que el borrador

    from tiempo.tiktok import ESTADO, hay_credenciales
    faltan = hay_credenciales() if a.publicar else []
    if a.publicar and faltan:
        log.warning("No se publica: falta %s. El vídeo queda como artefacto.", ", ".join(faltan))
    elif a.publicar:
        from tiempo.tiktok import publicar_con_reintentos
        log.info("Publicando con la autorización de %s", ESTADO.name)
        if a.esperar:
            esperar_hasta_publicacion("noche" if meta["modo"] == "noche" else "manana")
        meta["tiktok"] = publicar_con_reintentos(Path(meta["video"]), meta["caption"], meta["portada_ms"])
        log.info("Publicado en TikTok: %s", meta["tiktok"])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## Resumen económico del {hoy.isoformat()} ({meta['duracion']} s)\n\n"
                    f"**Texto para el post** (cópialo al publicar):\n\n```\n{meta['caption']}\n```\n\n"
                    f"Guion: {meta.get('origen_guion')}\n")
    if not a.demo:
        edicion = "noche" if meta["modo"] == "noche" else "manana"
        HISTORIAL.mkdir(exist_ok=True)
        (HISTORIAL / f"{hoy.isoformat()}{'-noche' if edicion == 'noche' else ''}.json").write_text(
            json.dumps({k: v for k, v in meta.items() if k != "video"}, ensure_ascii=False, indent=1), encoding="utf-8")


def _guardar_textos(hoy: date, meta: dict):
    from tiempo.repo import subir
    if True:
        edicion = "noche" if meta["modo"] == "noche" else "manana"
        destino = RAIZ / "docs" / "economia" / "hoy.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            previo = json.loads(destino.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            previo = {}
        ediciones = previo.get("ediciones", {}) if previo.get("fecha") == hoy.isoformat() else {}
        ediciones[edicion] = {"caption": meta["caption"], "voz": meta.get("voz"), "duracion": meta["duracion"]}
        destino.write_text(json.dumps({"fecha": hoy.isoformat(), "caption": meta["caption"], "edicion": edicion,
                                       "ediciones": ediciones}, ensure_ascii=False, indent=1), encoding="utf-8")
        subir([destino], f"Texto del resumen económico ({edicion}) del {hoy.isoformat()}")


if __name__ == "__main__":
    main()
