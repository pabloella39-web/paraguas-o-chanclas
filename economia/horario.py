"""Ventana horaria del canal económico (Madrid) y espera hasta las 8:30.

Uso:  python -m economia.horario "<github.event_name>"
"""
from __future__ import annotations

import logging
import os
import sys
import time

from tiempo.horario import ahora

from .config import HISTORIAL, HORA_PUBLICACION, VENTANA

log = logging.getLogger(__name__)


def debe_ejecutarse(evento: str) -> bool:
    if evento != "schedule":
        return True
    t = ahora()
    if not (VENTANA[0] <= (t.hour, t.minute) <= VENTANA[1]):
        print(f"Fuera de la ventana de publicación ({t:%H:%M} en Madrid)")
        return False
    if (HISTORIAL / f"{t.date().isoformat()}.json").exists():
        print("El resumen de hoy ya está hecho")
        return False
    return True


def esperar_hasta_publicacion():
    h, m = HORA_PUBLICACION
    objetivo = ahora().replace(hour=h, minute=m, second=0, microsecond=0)
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
    ok = debe_ejecutarse(sys.argv[1] if len(sys.argv) > 1 else "")
    print(f"Hora en Madrid: {ahora():%Y-%m-%d %H:%M %Z} → ejecutar={ok}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"ejecutar={'true' if ok else 'false'}\n")
