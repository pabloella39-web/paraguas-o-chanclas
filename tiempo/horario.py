"""Horario de Madrid: decide qué ejecución programada vale (verano/invierno) y espera hasta las 7:30.

GitHub Actions solo entiende UTC, así que el workflow se programa dos veces (04:45 y 05:45 UTC) y aquí
se descarta la que no corresponde según el horario de verano (CEST, UTC+2) o invierno (CET, UTC+1).
Uso:  python -m tiempo.horario "<github.event_name>" "<github.event.schedule>"
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import HORA_PUBLICACION, ZONA_HORARIA

log = logging.getLogger(__name__)
TZ = ZoneInfo(ZONA_HORARIA)

CRON_VERANO = "45 4 * * *"
CRON_INVIERNO = "45 5 * * *"


def ahora():
    return datetime.now(TZ)


def debe_ejecutarse(evento: str, cron: str) -> bool:
    if evento != "schedule":
        return True
    desfase = ahora().utcoffset() or timedelta(0)
    verano = desfase == timedelta(hours=2)
    return (cron == CRON_VERANO and verano) or (cron == CRON_INVIERNO and not verano)


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
