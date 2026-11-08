"""Prueba: mapa de lluvia en colores e isobaras (general y zoom a Canarias)."""
import logging
from datetime import date
from pathlib import Path

from PIL import Image

logging.basicConfig(level=logging.INFO)
from tiempo import campos, mapa
from tiempo.config import ANCHO, VISTA_GENERAL
from tiempo.video import MAPA_H, MAPA_Y0

Path("prueba").mkdir(exist_ok=True)
hoy = date.today()
lluvia = campos.capa_lluvia(hoy)
iso, centros, pmin, pmax = campos.capa_isobaras(hoy)
print("centros", centros, pmin, pmax)
CANARIAS_ZOOM = (-20.9, -17.9, 33.3, 35.6)
for nombre, vista, capa_f in (("lluvia_general", VISTA_GENERAL, lluvia), ("lluvia_canarias", None, lluvia),
                              ("isobaras_general", VISTA_GENERAL, iso)):
    if vista is None:
        lo, la = mapa.lonlat_mapa(-15.9, 28.3, True)
        vista = (lo - 3.2, lo + 3.2, la - 1.6, la + 1.6)
    pr = mapa.Proyeccion(vista, ANCHO, MAPA_H)
    img = Image.new("RGBA", (ANCHO, MAPA_Y0 + MAPA_H), (10, 30, 60, 255))
    img.alpha_composite(mapa.dibujar_mapa(vista, ANCHO, MAPA_H).convert("RGBA"), (0, MAPA_Y0))
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    capa_f(capa, pr, 3.0)
    img.alpha_composite(capa)
    img.crop((0, MAPA_Y0, ANCHO, MAPA_Y0 + MAPA_H)).convert("RGB").resize((540, MAPA_H // 2)).save(f"prueba/{nombre}.png")
    print("ok", nombre)
