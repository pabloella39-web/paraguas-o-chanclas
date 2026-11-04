"""Prueba real (GitHub Actions): avisos, oleaje y nieve de los próximos días y un fotograma del mapa con todo."""
import sys, json, logging
from datetime import date, timedelta
from pathlib import Path
logging.basicConfig(level=logging.INFO)
from PIL import Image
from tiempo import mapa, especiales as e
from tiempo.config import REGIONES, ANCHO, ALTO, VISTA_GENERAL
from tiempo.video import MAPA_H, MAPA_Y0
out = Path("prueba"); out.mkdir(exist_ok=True)
hoy = date.today()
dias = {f"d{k}": hoy + timedelta(days=k) for k in (1, 2, 3)}
e._preparar_avisos(dias)
print("TEXTO PROMPT:", e.AVISOS_TXT[0][:3000])
print("AVISOS:", {k: [(g["nivel"], g["fenomeno"], len(g["poligonos"])) for g in v] for k, v in e.AVISOS_DIA.items()})
print("MAR/NIEVE:", {k: (len(o), len(n)) for k, (o, n) in e.MAR_NIEVE.items()})
fondos, encima = e._capas_dias(), e._capas_encima_dias()
for k in dias:
    for nombre, vista, foco in (("espana", VISTA_GENERAL, None), ("norte", REGIONES["norte"]["vista"], "norte"),
                                ("med", REGIONES["mediterraneo"]["vista"], "mediterraneo")):
        base = Image.new("RGBA", (ANCHO, ALTO), (10, 20, 40, 255))
        base.alpha_composite(mapa.dibujar_mapa(vista, ANCHO, MAPA_H, foco=foco).convert("RGBA"), (0, MAPA_Y0))
        pr = mapa.Proyeccion(vista, ANCHO, MAPA_H)
        capa = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
        if k in fondos: fondos[k](capa, pr, 2.0)
        if k in encima: encima[k](capa, pr, 2.0, [])
        base.alpha_composite(capa)
        base.crop((0, MAPA_Y0, ANCHO, MAPA_Y0 + MAPA_H)).convert("RGB").resize((540, 520)).save(out / f"{k}_{nombre}.png")
print("OK")
