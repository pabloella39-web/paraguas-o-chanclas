"""Prueba visual del aviso: zoom, núcleos (naranja/amarillo/referencia), lluvia acumulada y evolución (4 modelos)."""
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image
from tiempo import campos, especiales as e, mapa
from tiempo.config import ANCHO, ALTO
from tiempo.video import MAPA_Y0, MAPA_H
logging.basicConfig(level=logging.INFO)
tz = ZoneInfo("Europe/Madrid")
man = date.today() + timedelta(days=1)
ini = datetime(man.year, man.month, man.day, 0, tzinfo=tz).isoformat()
fin = datetime(man.year, man.month, man.day, 23, tzinfo=tz).isoformat()
P = {p["nombre"]: [a for a in p["anillos"] if a] for p in mapa.provincias()}
naranja = {"fenomeno": "Lluvias", "nivel": "naranja", "zonas": ["Ávila", "Segovia"], "inicio": ini, "fin": fin,
           "poligonos": P["Ávila"] + P["Segovia"],
           "zona_poligono": [("Ávila", P["Ávila"][0]), ("Segovia", P["Segovia"][0])]}
amar = [{"fenomeno": "Lluvias", "nivel": "amarillo", "poligono": P[n][0], "zona": n, "inicio": ini, "fin": fin}
        for n in ("Madrid", "Salamanca", "Toledo", "Valladolid")]
grupos = [naranja]
e.AMARILLOS[:] = amar
zona = e._zona_zoom(grupos)
nuc = e.nucleos_afectados(grupos, n=10) + e.ciudades_zoom(grupos, amar)
print("núcleos:", [(c["nombre"], c.get("nivel", "naranja")) for c in nuc])
campo = e._campo_aviso(grupos, date.today())
pr = mapa.Proyeccion(zona, ANCHO, MAPA_H)
base = Image.new("RGBA", (ANCHO, ALTO), (10, 30, 60, 255))
base.alpha_composite(mapa.dibujar_mapa(zona, ANCHO, MAPA_H).convert("RGBA"), (0, MAPA_Y0))
out = Path("prueba"); out.mkdir(exist_ok=True)
capas = {"zonas": e._juntar_capas(e._capa_poligonos(grupos + amar, con_lista=True), e._capa_nucleos(nuc))}
if campo:
    capas["lluvia"] = e._juntar_capas(campos.capa_lluvia_fuerte(campo[0], "LLUVIA ACUMULADA PREVISTA (L/M²)"),
                                      e._capa_nucleos(nuc))
    h = campo[2]
    ev = campos.capa_evolucion(h["lons"], h["lats"], h["horas"], h["cubo"], h["canaria"])
    if ev:
        capas["evolucion"] = e._juntar_capas(ev, e._capa_nucleos(nuc))
    print("máximos:", campo[1])
for k, f in capas.items():
    im = base.copy()
    f(im, pr, 8.0)
    im.convert("RGB").resize((540, 960)).save(out / f"{k}.png")
print("ok")
