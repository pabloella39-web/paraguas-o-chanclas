"""Horario de Madrid: decide qué ejecución programada vale (verano/invierno) y espera hasta las 7:30.

GitHub Actions solo entiende UTC y puede retrasar o saltarse ejecuciones, así que hay varios intentos
programados; aquí se deja pasar el primero que cae en la ventana de la mañana si el parte de hoy no existe.
Uso:  python -m tiempo.horario "<github.event_name>" "<github.event.schedule>"
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import HORA_PUBLICACION, RAIZ, ZONA_HORARIA

log = logging.getLogger(__name__)
TZ = ZoneInfo(ZONA_HORARIA)



def ahora():
    return datetime.now(TZ)


def debe_ejecutarse(evento: str, cron: str = "") -> bool:
    """Las ejecuciones programadas solo trabajan entre las 6:00 y las 8:45 de Madrid y si hoy aún no hay parte."""
    if evento != "schedule":
        return True
    t = ahora()
    if not ((6, 0) <= (t.hour, t.minute) <= (8, 45)):
        print(f"Fuera de la ventana de publicación ({t:%H:%M} en Madrid)")
        return False
    hecho = RAIZ / "historial" / f"{t.date().isoformat()}.json"
    if hecho.exists():
        print(f"El parte de hoy ya está hecho ({hecho.name})")
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
    ok = debe_ejecutarse(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else "")
    print(f"Hora en Madrid: {ahora():%Y-%m-%d %H:%M %Z} → ejecutar={ok}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"ejecutar={'true' if ok else 'false'}\n")
