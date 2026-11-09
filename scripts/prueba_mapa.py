"""Prueba: detección de borrascas/DANAs y el tramo «sistema» (trayectoria → lluvia → rachas)."""
import logging
from datetime import date, timedelta
from pathlib import Path
from PIL import Image
from tiempo import mapa, sistemas
from tiempo.config import ANCHO, ALTO
from tiempo.video import MAPA_Y0, MAPA_H
logging.basicConfig(level=logging.INFO)
out = Path("prueba"); out.mkdir(exist_ok=True)
print("Nombre AEMET:", sistemas.nombre_aemet(date.today()))
for d in range(0, 4):
    dia = date.today() + timedelta(days=d)
    s = sistemas.detectar(dia)
    if not s:
        print(dia, "nada"); continue
    print(dia, s["tipo"], s.get("nombre"), round(s["minimo"]), round(s["distancia"], 1),
          [(h[5:13], round(lo, 1), round(la, 1), round(v)) for h, lo, la, v in s["trayectoria"]])
    print(sistemas.texto_guion(s, "mañana"))
    if d > 1:
        continue
    capa, notas = sistemas.preparar(s, dia)
    print("notas:", notas, "duración:", round(capa.duracion, 1))
    vista = sistemas.VISTA_SISTEMA
    pr = mapa.Proyeccion(vista, ANCHO, MAPA_H)
    base = Image.new("RGBA", (ANCHO, ALTO), (10, 30, 60, 255))
    base.alpha_composite(mapa.dibujar_mapa(vista, ANCHO, MAPA_H).convert("RGBA"), (0, MAPA_Y0))
    fr = []
    for t in (1.5, 3.5, capa.duracion * 0.45, capa.duracion * 0.6, capa.duracion * 0.85, capa.duracion - 0.3):
        im = base.copy(); capa(im, pr, t); fr.append(im.convert("RGB").resize((360, 640)))
    tira = Image.new("RGB", (360 * len(fr), 640))
    for i, im in enumerate(fr):
        tira.paste(im, (i * 360, 0))
    tira.save(out / f"sistema_{d}.png")
print("ok")
