"""Descarga los festivos nacionales y autonómicos de España de un año (Nager.Date, API pública) a
assets/festivos/AAAA.json. Uso: python scripts/festivos.py 2026 2027"""
import json
import sys
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
for anio in sys.argv[1:]:
    try:
        r = requests.get(f"https://date.nager.at/api/v3/PublicHolidays/{anio}/ES", timeout=60)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"::warning::Festivos {anio}: {e}")
        continue
    datos = [{"fecha": x["date"], "nombre": x["localName"], "nacional": x.get("global", False),
              "comunidades": x.get("counties") or []} for x in r.json()]
    destino = RAIZ / "assets" / "festivos" / f"{anio}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(anio, len(datos), "festivos")
