"""Ediciones del canal económico (hora de Madrid): mañana (8:00) y noche (21:30, de lunes a viernes).

Uso:  python -m economia.horario "<github.event_name>"
Escribe en GITHUB_OUTPUT: ejecutar=true|false y edicion=manana|noche
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import timedelta

from tiempo.horario import ahora

from .config import HISTORIAL, HORA_PUBLICACION, RAIZ, VENTANAS

log = logging.getLogger(__name__)


def edicion_actual(t=None) -> str | None:
    t = t or ahora()
    for edicion, (a, b) in VENTANAS.items():
        if a <= (t.hour, t.minute) <= b:
            if edicion == "noche" and t.weekday() >= 5:
                return None  # fin de semana: sin edición de noche (bolsas cerradas)
            return edicion
    return None


def archivo_historial(fecha, edicion: str):
    return HISTORIAL / f"{fecha.isoformat()}{'-noche' if edicion == 'noche' else ''}.json"


def debe_ejecutarse(evento: str) -> tuple[bool, str]:
    t = ahora()
    if evento != "schedule":
        lanzar = (RAIZ / "economia" / "lanzar.txt")
        manual_noche = evento == "push" and lanzar.exists() and "noche" in lanzar.read_text().lower()
        return True, "noche" if manual_noche or os.environ.get("EDICION") == "noche" else "manana"
    edicion = edicion_actual(t)
    if not edicion:
        print(f"Fuera de las ventanas de publicación ({t:%a %H:%M} en Madrid)")
        return False, "manana"
    if archivo_historial(t.date(), edicion).exists():
        print(f"La edición de {edicion} de hoy ya está hecha")
        return False, edicion
    return True, edicion


def esperar_hasta_publicacion(edicion: str = "manana"):
    h, m = HORA_PUBLICACION[edicion]
    # Se empieza a subir unos minutos antes: TikTok tarda ~2-3 min en procesar y el borrador debe estar a la hora
    objetivo = ahora().replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(minutes=4)
    falta = (objetivo - ahora()).total_seconds()
    if falta <= 0:
        log.info("Ya son más de las %02d:%02d, se publica ahora", h, m)
        return
    if falta > 3 * 3600:
        log.warning("Faltan %.0f min; no se espera tanto (¿ejecución manual?)", falta / 60)
        return
    log.info("Esperando %.1f minutos hasta las %02d:%02d…", falta / 60, h, m)
    time.sleep(falta)


if __name__ == "__main__":
    ok, edicion = debe_ejecutarse(sys.argv[1] if len(sys.argv) > 1 else "")
    print(f"Hora en Madrid: {ahora():%Y-%m-%d %H:%M %Z} → ejecutar={ok}, edición={edicion}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"ejecutar={'true' if ok else 'false'}\nedicion={edicion}\n")
