"""Prueba: zoom a todas las Canarias y mapa de lluvia acumulada «de modelo» con su escala."""
import logging
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

logging.basicConfig(level=logging.INFO)
from tiempo import campos, mapa
from tiempo import especiales as e
from tiempo.config import ANCHO
from tiempo.video import MAPA_H, MAPA_Y0

Path("prueba").mkdir(exist_ok=True)
hoy = date.today()
lons, lats, v = campos.lluvia(hoy, campos.CANARIAS_FINA, hoy + timedelta(days=1))
print("max por isla", campos.maximos(lons, lats, v, e.CAJA_ISLA))
def caja(a, b, c, d): return [(a, c), (b, c), (b, d), (a, d)]
gr = [{"nivel": "naranja", "fenomeno": "lluvias", "zonas": ["Tenerife", "La Palma", "La Gomera", "El Hierro", "Gran Canaria"],
       "poligonos": [caja(*e.CAJA_ISLA[i]) for i in ("Tenerife", "La Palma", "La Gomera", "El Hierro", "Gran Canaria")]}]
zona = e._zona_zoom(gr)
nuc = e.nucleos_afectados(gr)
capa_ll = campos.capa_lluvia_fuerte([(lons, lats, v, True)], "LLUVIA ACUMULADA PREVISTA (L/M²)")
for nombre, capa_f in (("zonas", e._juntar_capas(e._capa_poligonos(gr, con_lista=True), e._capa_nucleos(nuc))),
                       ("lluvia", e._juntar_capas(capa_ll, e._capa_nucleos(nuc)))):
    pr = mapa.Proyeccion(zona, ANCHO, MAPA_H)
    img = Image.new("RGBA", (ANCHO, MAPA_Y0 + MAPA_H), (10, 30, 60, 255))
    img.alpha_composite(mapa.dibujar_mapa(zona, ANCHO, MAPA_H).convert("RGBA"), (0, MAPA_Y0))
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    capa_f(capa, pr, 5.0)
    img.alpha_composite(capa)
    img.crop((0, MAPA_Y0, ANCHO, MAPA_Y0 + MAPA_H)).convert("RGB").resize((540, MAPA_H // 2)).save(f"prueba/{nombre}.png")
    print("ok", nombre)
