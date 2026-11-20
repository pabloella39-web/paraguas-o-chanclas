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
    """Desde el 20/11/2026 el parte vuelve a la MAÑANA (el de hoy, a las 7:30): las ejecuciones programadas trabajan
    entre las 5:30 y las 7:15 de Madrid si el parte de hoy aún no existe (hay varios intentos por los retrasos de
    GitHub). Lunes, jueves y sábado no hay parte: lo cubre el especial de la tarde anterior (semana, resto, finde)."""
    if evento != "schedule":
        return True
    t = ahora()
    hoy = RAIZ / "historial" / f"{t.date().isoformat()}.json"
    if not ((5, 30) <= (t.hour, t.minute) <= (7, 15)):
        print(f"Fuera de la ventana de la mañana ({t:%H:%M} en Madrid)")
        return False
    if t.weekday() in (0, 3, 5):  # lunes, jueves y sábado: el especial de la víspera hace de parte
        print("Lunes/jueves/sábado: el parte de hoy fue el especial de ayer por la tarde")
        return False
    if hoy.exists():
        print(f"El parte de hoy ya está hecho ({hoy.name})")
        return False
    return True


def esperar_hasta_publicacion():
    import os
    h, m = (20, 30) if os.environ.get("VISPERA") else HORA_PUBLICACION
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
    ok = debe_ejecutarse(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else "")
    print(f"Hora en Madrid: {ahora():%Y-%m-%d %H:%M %Z} → ejecutar={ok}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"ejecutar={'true' if ok else 'false'}\n")
