"""Prueba: evolución de la lluvia hora a hora en Canarias (datos reales de hoy y mañana)."""
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
lons, lats, horas, cubo = campos.lluvia_horaria(hoy, campos.CANARIAS_FINA, hoy + timedelta(days=1))
print("horas", len(horas), "max", float(cubo.max()))
print("picos", campos.picos(lons, lats, horas, cubo, e.CAJA_ISLA))
capa = campos.capa_evolucion(lons, lats, horas, cubo, True)
print("duracion", capa.duracion)
def caja(a, b, c, d): return [(a, c), (b, c), (b, d), (a, d)]
gr = [{"poligonos": [caja(*e.CAJA_ISLA["Tenerife"]), caja(*e.CAJA_ISLA["Lanzarote"])], "zonas": []}]
zona = e._zona_zoom(gr)
pr = mapa.Proyeccion(zona, ANCHO, MAPA_H)
base = Image.new("RGBA", (ANCHO, MAPA_Y0 + MAPA_H), (10, 30, 60, 255))
base.alpha_composite(mapa.dibujar_mapa(zona, ANCHO, MAPA_H).convert("RGBA"), (0, MAPA_Y0))
tiras = []
for t in (0.7, 2.6, 4.6, 6.6, 8.6):
    img = base.copy()
    c = Image.new("RGBA", img.size, (0, 0, 0, 0))
    capa(c, pr, t)
    img.alpha_composite(c)
    tiras.append(img.crop((0, MAPA_Y0, ANCHO, MAPA_Y0 + MAPA_H)).convert("RGB").resize((360, MAPA_H // 3)))
W = Image.new("RGB", (370 * len(tiras), tiras[0].height), (255, 255, 255))
for i, t in enumerate(tiras):
    W.paste(t, (i * 370, 0))
W.save("prueba/evolucion.png")
print("ok")
