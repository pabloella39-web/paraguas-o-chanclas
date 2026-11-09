"""Reloj: lanza las tareas cuyo «cron» coincide con el minuto actual (UTC), mientras dure (minutos en argv[1]).
Las líneas cron se leen de los propios archivos de .github/workflows para no tener dos horarios distintos."""
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# tarea -> argumentos para el lanzamiento a mano (el parte y los especiales reciben la línea cron que toca)
TAREAS = {
    "respuestas.yml": lambda c: ["-f", "comprobar=false"],
    "especiales.yml": lambda c: ["-f", f"reloj={c}"],
    "parte-diario.yml": lambda c: ["-f", f"reloj={c}"],
    "comprobar-redes.yml": lambda c: [],
    "festivos.yml": lambda c: [],
}


def campo(expr: str, valor: int, lo: int, hi: int) -> bool:
    for parte in expr.split(","):
        paso = 1
        if "/" in parte:
            parte, p = parte.split("/")
            paso = int(p)
        if parte == "*":
            a, b = lo, hi
        elif "-" in parte:
            a, b = map(int, parte.split("-"))
        else:
            a = b = int(parte)
            if paso > 1:
                b = hi
        if a <= valor <= b and (valor - a) % paso == 0:
            return True
    return False


def coincide(cron: str, t: datetime) -> bool:
    mi, h, dm, me, ds = cron.split()[:5]
    dow = (t.weekday() + 1) % 7   # cron: 0 = domingo
    return (campo(mi, t.minute, 0, 59) and campo(h, t.hour, 0, 23) and campo(dm, t.day, 1, 31)
            and campo(me, t.month, 1, 12) and campo(ds, dow, 0, 6))


def horarios():
    out = []
    for nombre in TAREAS:
        f = Path(".github/workflows") / nombre
        if not f.exists():
            continue
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        on = d.get(True) or d.get("on") or {}
        for s in (on.get("schedule") or []):
            out.append((nombre, s["cron"].strip()))
    return out


def lanzar(nombre, cron):
    args = ["gh", "workflow", "run", nombre, "--ref", "main"] + TAREAS[nombre](cron)
    r = subprocess.run(args, capture_output=True, text=True)
    print(f"{datetime.now(timezone.utc):%H:%M} {nombre} ({cron}) -> {'ok' if r.returncode == 0 else r.stderr.strip()}",
          flush=True)


def main():
    fin = time.time() + int(sys.argv[1] if len(sys.argv) > 1 else 325) * 60
    lista = horarios()
    print("Horarios:", lista, flush=True)
    hecho = set()
    while time.time() < fin:
        t = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        for nombre, cron in lista:
            if (nombre, cron, t) not in hecho and coincide(cron, t):
                hecho.add((nombre, cron, t))
                lanzar(nombre, cron)
        time.sleep(max(1, 60 - datetime.now(timezone.utc).second + 1))


if __name__ == "__main__":
    main()
