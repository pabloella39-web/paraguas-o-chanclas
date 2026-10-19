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

from . import guion as g
from . import musica, voz
from .config import DURACION_MAX, DURACION_MIN, DURACION_OBJETIVO, FPS, RAIZ, SEGMENTOS
from .fuentes import obtener_previsiones, previsiones_demo
from .horario import ahora, esperar_hasta_publicacion
from .video import Compositor, renderizar

log = logging.getLogger("tiempo")

INICIO = 0.45      # la voz arranca tras el golpe de título
PAUSA = 0.30       # silencio entre bloques
COLA = 1.2         # tras la despedida (tarjeta de "sígueme")
TEMPO_MAX = 1.22   # aceleración máxima de la voz que sigue sonando natural
HABLA_MIN, HABLA_MAX = 55.0, 64.0


def generar_locucion(prev, hoy, texto_aemet, trabajo: Path, demo: bool):
    factor, mejor = 1.0, None
    for intento in range(3):
        guion = g.guion_plantilla(prev, hoy, factor) if demo else g.escribir_guion(prev, hoy, texto_aemet, factor)
        bloques = [s for s in SEGMENTOS if guion["segmentos"].get(s, "").strip()]
        wavs = [voz.sintetizar(guion["segmentos"][s], trabajo / f"{intento}_{s}.mp3", demo) for s in bloques]
        durs = [voz.duracion(w) for w in wavs]
        habla = sum(durs)
        log.info("Intento %d (%s): %d palabras, %.1f s de voz", intento + 1, guion.get("origen", "plantilla"),
                 sum(len(guion["segmentos"][s].split()) for s in bloques), habla)
        mejor = (guion, bloques, wavs, durs)
        if HABLA_MIN <= habla <= HABLA_MAX:
            break
        factor *= ((HABLA_MIN + HABLA_MAX) / 2) / habla  # pide un guion más corto/largo
    return mejor


def planificar(bloques, wavs, durs):
    """Calcula tiempos para que el total quede SIEMPRE entre 65 y 70 segundos."""
    n = len(bloques)
    fijo = INICIO + PAUSA * (n - 1) + COLA
    habla = sum(durs)
    limite = DURACION_MAX - 0.8
    if habla + fijo > limite:
        tempo = habla / (limite - fijo)
        if tempo > TEMPO_MAX:
            raise RuntimeError(f"La locución dura {habla:.1f} s: demasiado larga incluso acelerada")
        log.info("Acelerando la voz x%.3f para no pasar de %.0f s", tempo, DURACION_MAX)
        wavs = [voz.acelerar(w, tempo) for w in wavs]
        durs = [voz.duracion(w) for w in wavs]
        habla = sum(durs)
    pausa, cola = PAUSA, COLA
    falta = DURACION_OBJETIVO - (habla + fijo)
    if falta > 0:
        extra_pausa = min(0.45, falta * 0.6 / max(1, n - 1))
        pausa += extra_pausa
        cola += falta - extra_pausa * (n - 1)
    plan, t = [], INICIO
    for s, w, d in zip(bloques, wavs, durs):
        plan.append({"seg": s, "inicio": t, "fin": t + d, "wav": w})
        t += d + pausa
    total = plan[-1]["fin"] + cola
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

    guion, bloques, wavs, durs = generar_locucion(prev, hoy, texto_aemet, trabajo, demo)
    plan, total = planificar(bloques, wavs, durs)
    for p in plan:
        p["texto"] = guion["segmentos"][p["seg"]]

    audio = trabajo / "pista.wav"
    voz.montar_pista([(p["wav"], p["inicio"]) for p in plan], total, musica.generar(total), audio)

    extremos = {"calor": max(prev, key=lambda c: c["tmax"]), "frio": min(prev, key=lambda c: c["tmin"])}
    comp = Compositor(prev, plan, total, g.fecha_larga(hoy).upper(), extremos)
    video = salida / f"tiempo_{hoy.isoformat()}.mp4"
    log.info("Renderizando %.2f s de vídeo…", total)
    renderizar(comp, audio, video, total)

    real = voz.duracion(video)
    if not DURACION_MIN <= real <= DURACION_MAX:
        raise RuntimeError(f"El vídeo final dura {real:.2f} s (debe estar entre 65 y 70)")
    general = next((p for p in plan if p["seg"] == "general"), plan[0])
    caption = guion["caption"].strip()
    if "AEMET" not in caption:
        caption += " #AEMET"
    meta = {"fecha": hoy.isoformat(), "duracion": round(real, 2), "video": str(video), "caption": caption,
            "portada_ms": int((general["inicio"] + 2.5) * 1000), "origen_guion": guion.get("origen"),
            "guion": {p["seg"]: p["texto"] for p in plan}}
    (salida / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Vídeo listo: %s (%.2f s)", video, real)
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="datos inventados, sin claves y sin voz")
    ap.add_argument("--publicar", action="store_true", help="subir a TikTok")
    ap.add_argument("--esperar", action="store_true", help="esperar a las 7:30 (Madrid) antes de publicar")
    ap.add_argument("--salida", default=str(RAIZ / "salida"))
    ap.add_argument("--fecha", help="AAAA-MM-DD (por defecto, hoy en Madrid)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    hoy = date.fromisoformat(a.fecha) if a.fecha else ahora().date()
    meta = construir(hoy, Path(a.salida), demo=a.demo)

    faltan = [v for v in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN") if not os.environ.get(v)]
    if a.publicar and faltan:
        log.warning("No se publica: faltan los secretos %s. El vídeo queda como artefacto de la ejecución.",
                    ", ".join(faltan))
    elif a.publicar:
        from .tiktok import publicar
        if a.esperar:
            esperar_hasta_publicacion()
        res = publicar(Path(meta["video"]), meta["caption"], meta["portada_ms"])
        meta["tiktok"] = res
        log.info("Publicado en TikTok: %s", res)
    hist = RAIZ / "historial" / f"{hoy.isoformat()}.json"
    if not a.demo:
        hist.parent.mkdir(exist_ok=True)
        hist.write_text(json.dumps({k: v for k, v in meta.items() if k != "video"}, ensure_ascii=False, indent=1),
                        encoding="utf-8")


if __name__ == "__main__":
    main()
