"""Composición del vídeo vertical: mapa animado, tarjetas, subtítulos y atribuciones."""
from __future__ import annotations

import logging
import math
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import mapa
from .config import (ALTO, ANCHO, ATRIBUCION_AEMET, ATRIBUCION_GOOGLE, FPS, NOMBRE_CANAL, REGIONES,
                     VISTA_GENERAL)
from .mapa import fuente

log = logging.getLogger(__name__)

MAPA_Y0, MAPA_Y1 = 360, 1400
MAPA_H = MAPA_Y1 - MAPA_Y0
AREA_MARCADORES = (24, 20, 930, MAPA_H - 10)  # relativo al mapa; x<930 deja libre la columna de botones de TikTok
SUB_Y = 1490
TRANSICION = 0.6
ACENTO = (255, 196, 45)

PILLS = {"intro": None, "general": "HOY EN ESPAÑA", "cierre": "¡HASTA MAÑANA!"}


def vista_de(seg):
    if seg in REGIONES and REGIONES[seg]["vista"]:
        return REGIONES[seg]["vista"]
    return VISTA_GENERAL


def foco_de(seg):
    return seg if seg in REGIONES else None


# ---------------------------------------------------------------- utilidades de dibujo
def _ease_back(t):
    t = min(max(t, 0), 1)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _ajustar(txt, peso, tam, ancho):
    f = fuente(peso, tam)
    while f.getlength(txt) > ancho and tam > 20:
        tam -= 2
        f = fuente(peso, tam)
    return f


def _fondo():
    img = Image.new("RGB", (ANCHO, ALTO), mapa.MAR_ARRIBA)
    img.paste(mapa.MAR_ABAJO, (0, MAPA_Y1, ANCHO, ALTO))
    return img


def _fundido_bordes(img_mapa: Image.Image) -> Image.Image:
    """Difumina el borde superior e inferior del mapa con el color de fondo."""
    im = img_mapa.convert("RGBA")
    h = 120
    for color, y0, invert in ((mapa.MAR_ARRIBA, 0, False), (mapa.MAR_ABAJO, MAPA_H - h, True)):
        alfa = np.linspace(255, 0, h) if not invert else np.linspace(0, 255, h)
        capa = Image.new("RGBA", (ANCHO, h), color + (0,))
        capa.putalpha(Image.fromarray(np.repeat(alfa[:, None], ANCHO, axis=1).astype(np.uint8)))
        im.alpha_composite(capa, (0, y0))
    return im.convert("RGB")


def _trocear_subtitulos(texto: str, max_car=30):
    palabras = texto.split()
    trozos, actual = [], []
    for p in palabras:
        prueba = " ".join(actual + [p])
        if actual and (len(prueba) > max_car or re.search(r"[.,;:!?]$", actual[-1]) and len(" ".join(actual)) > 12):
            trozos.append(" ".join(actual))
            actual = [p]
        else:
            actual.append(p)
    if actual:
        trozos.append(" ".join(actual))
    return trozos


class Compositor:
    def __init__(self, prev, plan, total, fecha_txt, extremos):
        self.prev = prev
        self.plan = plan  # [{seg, inicio, fin, texto}]
        self.total = total
        self.fecha_txt = fecha_txt.upper()
        self.extremos = extremos
        self._cache_mapa = {}
        self._cache_marc = {}
        self._subs = []
        for p in plan:
            trozos = _trocear_subtitulos(p["texto"])
            pesos = [len(t) + 4 for t in trozos]
            dur = p["fin"] - p["inicio"]
            t = p["inicio"]
            for tr, w in zip(trozos, pesos):
                d = dur * w / sum(pesos)
                self._subs.append((t, t + d, tr))
                t += d
        # Ventanas visuales: cada bloque empieza un poco antes que su voz
        self.ventanas = []
        for i, p in enumerate(plan):
            ini = 0 if i == 0 else max(plan[i - 1]["fin"], p["inicio"] - 0.35)
            fin = total if i == len(plan) - 1 else max(p["fin"], plan[i + 1]["inicio"] - 0.35)
            self.ventanas.append((ini, fin, p["seg"]))
        self.cabecera = self._cabecera()

    # ------------------------------------------------ capas estáticas
    def _cabecera(self):
        im = Image.new("RGBA", (ANCHO, MAPA_Y0), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        f1 = fuente("ExtraBold", 34)
        d.text((ANCHO / 2, 150), NOMBRE_CANAL, font=f1, fill=ACENTO, anchor="ma")
        f2 = _ajustar(self.fecha_txt, "Black", 72, 960)
        d.text((ANCHO / 2 + 3, 196 + 4), self.fecha_txt, font=f2, fill=(0, 0, 0, 120), anchor="ma")
        d.text((ANCHO / 2, 196), self.fecha_txt, font=f2, fill=(255, 255, 255), anchor="ma")
        return im

    def _atribucion(self, d):
        f = fuente("SemiBold", 24)
        for i, txt in enumerate((ATRIBUCION_AEMET, ATRIBUCION_GOOGLE)):
            d.text((ANCHO / 2, MAPA_Y1 + 12 + i * 32), txt, font=f, fill=(225, 232, 245), anchor="ma")

    def mapa_estatico(self, seg):
        clave = (vista_de(seg), foco_de(seg))
        if clave not in self._cache_mapa:
            self._cache_mapa[clave] = _fundido_bordes(mapa.dibujar_mapa(clave[0], ANCHO, MAPA_H, foco=clave[1]))
        return self._cache_mapa[clave]

    def marcadores(self, seg):
        if seg not in self._cache_marc:
            vista = vista_de(seg)
            pr = mapa.Proyeccion(vista, ANCHO, MAPA_H)
            if seg in ("general", "cierre"):
                lista, estilo = self.prev, "mini"
            elif seg in REGIONES:
                lista, estilo = [c for c in self.prev if c["region"] == seg], "tarjeta"
            else:
                lista, estilo = [], "mini"
            self._cache_marc[seg] = (estilo, mapa.marcadores(lista, pr, estilo, AREA_MARCADORES))
        return self._cache_marc[seg]

    # ------------------------------------------------ fotograma
    def ventana(self, t):
        for i, (a, b, seg) in enumerate(self.ventanas):
            if a <= t < b or i == len(self.ventanas) - 1:
                return i, a, seg
        return 0, 0, self.ventanas[0][2]

    def fotograma(self, t) -> Image.Image:
        i, ini, seg = self.ventana(t)
        prev_seg = self.ventanas[i - 1][2] if i > 0 else seg
        img = _fondo()
        dt = t - ini
        en_trans = vista_de(prev_seg) != vista_de(seg) and dt < TRANSICION
        if en_trans:
            vista = mapa.interpolar_vista(vista_de(prev_seg), vista_de(seg), dt / TRANSICION)
            m = _fundido_bordes(mapa.dibujar_mapa(vista, ANCHO, MAPA_H, foco=foco_de(seg), ss=1))
        else:
            m = self.mapa_estatico(seg)
        img.paste(m, (0, MAPA_Y0))
        capa = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
        d = ImageDraw.Draw(capa)

        # Marcadores con animación de entrada escalonada
        if not en_trans:
            t_marc = dt - (TRANSICION if vista_de(prev_seg) != vista_de(seg) else 0.1)
            estilo, items = self.marcadores(seg)
            for k, (im, (x, y), (px, py)) in enumerate(items):
                s = _ease_back((t_marc - k * (0.06 if estilo == "mini" else 0.15)) / 0.35)
                if s <= 0.02:
                    continue
                if estilo == "tarjeta":
                    cx, cy = x + im.width / 2, y + im.height
                    d.line([(cx, MAPA_Y0 + cy), (px, MAPA_Y0 + py)], fill=(255, 255, 255, int(200 * min(s, 1))), width=3)
                    d.ellipse([px - 9, MAPA_Y0 + py - 9, px + 9, MAPA_Y0 + py + 9], fill=(255, 255, 255),
                              outline=(8, 20, 45), width=3)
                w, h = max(1, int(im.width * s)), max(1, int(im.height * s))
                imr = im.resize((w, h), Image.BILINEAR) if (w, h) != im.size else im
                capa.alpha_composite(imr, (int(x + (im.width - w) / 2), int(MAPA_Y0 + y + (im.height - h) / 2)))

        # Extremos del día en el bloque general
        if seg == "general" and not en_trans:
            self._chips_extremos(capa, d, dt)

        img = img.convert("RGBA")
        img.alpha_composite(self.cabecera)
        img.alpha_composite(capa)
        d = ImageDraw.Draw(img)
        self._pill(img, d, seg, dt)
        if seg == "intro":
            self._intro(img, d, t)
        if seg == "cierre":
            self._cierre(img, d, dt)
        self._atribucion(d)
        self._subtitulo(img, d, t)
        return img.convert("RGB")

    def _pill(self, img, d, seg, dt):
        txt = PILLS.get(seg, REGIONES.get(seg, {}).get("titulo"))
        if not txt:
            return
        f = fuente("Black", 40)
        w = f.getlength(txt) + 60
        s = _ease_back(dt / 0.3)
        x0 = ANCHO / 2 - w / 2 * s
        d.rounded_rectangle([x0, 286, ANCHO / 2 + w / 2 * s, 344], radius=29, fill=ACENTO)
        if s > 0.7:
            d.text((ANCHO / 2, 316), txt, font=f, fill=(15, 25, 50), anchor="mm")

    def _chips_extremos(self, capa, d, dt):
        a = min(1, max(0, (dt - 1.2) / 0.4))
        if a <= 0:
            return
        f1, f2 = fuente("ExtraBold", 26), fuente("Black", 34)
        for i, (etq, c, valor, col) in enumerate((
                ("MÁS CALOR", self.extremos["calor"]["nombre"], f"{self.extremos['calor']['tmax']}°", (255, 140, 60)),
                ("MÁS FRÍO", self.extremos["frio"]["nombre"], f"{self.extremos['frio']['tmin']}°", (120, 190, 255)))):
            x0 = 40 + i * 450
            y0 = MAPA_Y0 + 8
            d.rounded_rectangle([x0, y0, x0 + 420, y0 + 64], radius=20, fill=(8, 20, 45, int(220 * a)),
                                outline=col + (int(255 * a),), width=3)
            d.text((x0 + 20, y0 + 32), etq, font=f1, fill=col + (int(255 * a),), anchor="lm")
            d.text((x0 + 400, y0 + 32), f"{c} {valor}", font=_ajustar(f"{c} {valor}", "Black", 34, 230),
                   fill=(255, 255, 255, int(255 * a)), anchor="rm")

    def _intro(self, img, d, t):
        velo = Image.new("RGBA", (ANCHO, MAPA_H), (5, 14, 34, 150))
        img.alpha_composite(velo, (0, MAPA_Y0))
        d = ImageDraw.Draw(img)
        for k, (txt, tam) in enumerate((("¿QUÉ TIEMPO", 110), ("HACE HOY?", 110))):
            s = _ease_back((t - 0.1 - k * 0.15) / 0.45)
            if s <= 0.02:
                continue
            f = fuente("Black", max(10, int(tam * s)))
            y = MAPA_Y0 + 300 + k * 130
            d.text((ANCHO / 2 + 4, y + 6), txt, font=f, fill=(0, 0, 0, 140), anchor="mm")
            d.text((ANCHO / 2, y), txt, font=f, fill=(255, 255, 255) if k == 0 else ACENTO, anchor="mm")
        for k, ic in enumerate(("sol", "sol_nubes", "lluvia", "nieve")):
            s = _ease_back((t - 0.5 - k * 0.12) / 0.4)
            if s <= 0.02:
                continue
            tam = int(130 * s)
            bote = math.sin((t - k * 0.3) * 4) * 10
            img.alpha_composite(mapa.icono(ic, 130).resize((max(1, tam), max(1, tam))),
                                (int(130 + k * 210 + (130 - tam) / 2), int(MAPA_Y0 + 560 + bote)))

    def _cierre(self, img, d, dt):
        s = _ease_back((dt - 0.4) / 0.4)
        if s <= 0.02:
            return
        w, h = 760 * s, 230 * s
        cx, cy = ANCHO / 2, MAPA_Y0 + MAPA_H - 190
        d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=36 * s, fill=ACENTO)
        if s > 0.8:
            d.text((cx, cy - 40), "¡SÍGUEME!", font=fuente("Black", 84), fill=(15, 25, 50), anchor="mm")
            d.text((cx, cy + 52), "Cada mañana a las 7:30", font=fuente("ExtraBold", 40), fill=(15, 25, 50),
                   anchor="mm")

    def _subtitulo(self, img, d, t):
        txt = next((s for a, b, s in self._subs if a <= t < b), None)
        if not txt:
            return
        f = _ajustar(txt, "Black", 56, 880)
        lineas = [txt]
        if f.size < 46 and len(txt.split()) > 2:  # en dos líneas si no cabe grande
            pal = txt.split()
            mitad = len(pal) // 2
            lineas = [" ".join(pal[:mitad]), " ".join(pal[mitad:])]
            f = _ajustar(max(lineas, key=len), "Black", 56, 880)
        alto = len(lineas) * (f.size + 14)
        anchomax = max(f.getlength(l) for l in lineas)
        d.rounded_rectangle([ANCHO / 2 - anchomax / 2 - 28, SUB_Y - 18, ANCHO / 2 + anchomax / 2 + 28,
                             SUB_Y + alto + 8], radius=26, fill=(0, 0, 0, 165))
        for k, l in enumerate(lineas):
            x = ANCHO / 2 - f.getlength(l) / 2
            y = SUB_Y + k * (f.size + 14)
            for palabra in l.split(" "):
                color = ACENTO if re.search(r"\d", palabra) else (255, 255, 255)
                d.text((x, y), palabra, font=f, fill=color)
                x += f.getlength(palabra + " ")


def renderizar(comp: Compositor, audio: Path, salida: Path, total: float):
    n = round(total * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ANCHO}x{ALTO}",
           "-r", str(FPS), "-i", "-", "-i", str(audio),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
           "-t", f"{total:.3f}", "-movflags", "+faststart", str(salida)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(n):
        proc.stdin.write(comp.fotograma(k / FPS).tobytes())
        if k % (FPS * 10) == 0:
            log.info("Render %d/%d", k, n)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg falló al codificar el vídeo")
