"""Comprobación real: nieve prevista en la montaña los próximos días (sin filtros) y avisos de nieve de AEMET."""
import logging
from datetime import date, timedelta
from pathlib import Path
logging.basicConfig(level=logging.WARNING)
from tiempo.fuentes import nieve
from tiempo import especiales as e
out = Path("prueba"); out.mkdir(exist_ok=True)
hoy = date.today()
for k in range(1, 5):
    d = hoy + timedelta(days=k)
    todo = nieve(d, cota_max=4000, cm_min=0.1)
    print(d, "NIEVE (sin filtros):", [(x["zona"], x["cota"], x["cm"]) for x in todo] or "ninguna")
av = e.avisos_por_dia({str(hoy + timedelta(days=k)): hoy + timedelta(days=k) for k in range(1, 4)})
for k, v in av.items():
    print(k, "AVISOS:", [(g["nivel"], g["fenomeno"], g["zonas"][:3]) for g in v])
print("OK")
