"""Composición del vídeo vertical del resumen económico: tarjetas, gráficos, agenda y subtítulos."""
from __future__ import annotations

import math
import re
from datetime import date
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from tiempo.config import ALTO, ANCHO
from tiempo.mapa import fuente
from tiempo.video import _ajustar, _ease_back, _trocear_subtitulos

from .config import AVISO, LEMA, NOMBRE_CANAL
from .guion import DIAS, fnum, fpct, precio_pantalla

ACENTO = (255, 196, 45)
VERDE = (38, 222, 129)
ROJO = (255, 86, 86)
BLANCO = (255, 255, 255)
SUAVE = (160, 176, 206)
OSCURO = (12, 20, 40)
TARJETA = (255, 255, 255, 18)
BORDE = (255, 255, 255, 38)
Y0, Y1 = 385, 1350          # zona de contenido
XD = 930                    # por debajo de y≈860 no se pasa de aquí (botones de TikTok)
SUB_Y = 1515
TICKER_Y = 1362
PORTADA_FIJA, PORTADA_FIN = 0.5, 0.9

PILLS = {"intro": None, "bolsas": "BOLSAS", "cripto": "CRIPTO", "materias": "MATERIAS PRIMAS",
         "agenda": "AGENDA DE HOY", "noticias": "NOTICIAS", "cierre": "¡HASTA MAÑANA!"}


def color_cambio(x):
    return VERDE if (x or 0) >= 0 else ROJO


# ---------------------------------------------------------------- piezas gráficas
@lru_cache(maxsize=1)
def fondo() -> Image.Image:
    y = np.linspace(0, 1, ALTO)[:, None]
    x = np.linspace(0, 1, ANCHO)[None, :]
    arriba, abajo = np.array([6, 12, 30]), np.array([13, 27, 56])
    base = arriba + (abajo - arriba) * y[..., None]
    brillo = np.exp(-(((x - 0.85) ** 2) / 0.12 + ((y - 0.18) ** 2) / 0.05))[..., None] * np.array([20, 30, 55])
    img = Image.fromarray(np.clip(base + brillo, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    rejilla = Image.new("RGBA", (ANCHO, ALTO), (0, 0, 0, 0))
    d = ImageDraw.Draw(rejilla)
    for gx in range(0, ANCHO, 90):
        d.line([(gx, 0), (gx, ALTO)], fill=(255, 255, 255, 9), width=1)
    for gy in range(0, ALTO, 90):
        d.line([(0, gy), (ANCHO, gy)], fill=(255, 255, 255, 9), width=1)
    img.alpha_composite(rejilla)
    return img.convert("RGB")


def _redondear(im: Image.Image, r: int) -> Image.Image:
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=r, fill=255)
    out = im.convert("RGBA")
    out.putalpha(Image.fromarray(np.minimum(np.array(out.getchannel("A")), np.array(m))))
    return out


@lru_cache(maxsize=64)
def bandera(cod: str, w: int = 72, h: int = 48) -> Image.Image:
    s = 3
    W, H = w * s, h * s
    im = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(im)
    if cod == "es":
        d.rectangle([0, 0, W, H], fill=(198, 11, 30))
        d.rectangle([0, H // 4, W, 3 * H // 4], fill=(255, 196, 0))
    elif cod == "eu":
        d.rectangle([0, 0, W, H], fill=(0, 51, 153))
        for k in range(12):
            a = k * math.pi / 6
            cx, cy = W / 2 + math.cos(a) * H * 0.33, H / 2 + math.sin(a) * H * 0.33
            d.ellipse([cx - H * 0.05, cy - H * 0.05, cx + H * 0.05, cy + H * 0.05], fill=(255, 204, 0))
    elif cod == "de":
        for i, c in enumerate(((0, 0, 0), (221, 0, 0), (255, 206, 0))):
            d.rectangle([0, i * H / 3, W, (i + 1) * H / 3], fill=c)
    elif cod == "us":
        for i in range(13):
            d.rectangle([0, i * H / 13, W, (i + 1) * H / 13], fill=(178, 34, 52) if i % 2 == 0 else (255, 255, 255))
        d.rectangle([0, 0, W * 0.42, H * 7 / 13], fill=(60, 59, 110))
        for fy in range(4):
            for fx in range(5):
                cx, cy = W * 0.05 + fx * W * 0.08, H * 0.07 + fy * H * 0.12
                d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 255, 255))
    elif cod == "jp":
        d.ellipse([W / 2 - H * 0.3, H * 0.2, W / 2 + H * 0.3, H * 0.8], fill=(188, 0, 45))
    elif cod == "gb":
        d.rectangle([0, 0, W, H], fill=(1, 33, 105))
        d.line([(0, 0), (W, H)], fill=BLANCO, width=H // 5)
        d.line([(0, H), (W, 0)], fill=BLANCO, width=H // 5)
        d.line([(0, 0), (W, H)], fill=(200, 16, 46), width=H // 14)
        d.line([(0, H), (W, 0)], fill=(200, 16, 46), width=H // 14)
        d.rectangle([W / 2 - H / 6, 0, W / 2 + H / 6, H], fill=BLANCO)
        d.rectangle([0, H / 2 - H / 6, W, H / 2 + H / 6], fill=BLANCO)
        d.rectangle([W / 2 - H / 10, 0, W / 2 + H / 10, H], fill=(200, 16, 46))
        d.rectangle([0, H / 2 - H / 10, W, H / 2 + H / 10], fill=(200, 16, 46))
    elif cod in ("fr", "it"):
        cols = ((0, 35, 149), (255, 255, 255), (237, 41, 57)) if cod == "fr" else \
            ((0, 146, 70), (255, 255, 255), (206, 43, 55))
        for i, c in enumerate(cols):
            d.rectangle([i * W / 3, 0, (i + 1) * W / 3, H], fill=c)
    elif cod == "cn":
        d.rectangle([0, 0, W, H], fill=(222, 41, 16))
        _estrella(d, W * 0.2, H * 0.3, H * 0.18, (255, 222, 0))
    else:  # mundo
        d.rectangle([0, 0, W, H], fill=(30, 70, 140))
        r = H * 0.38
        d.ellipse([W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r], outline=BLANCO, width=s * 2)
        d.ellipse([W / 2 - r * 0.45, H / 2 - r, W / 2 + r * 0.45, H / 2 + r], outline=BLANCO, width=s * 2)
        d.line([(W / 2 - r, H / 2), (W / 2 + r, H / 2)], fill=BLANCO, width=s * 2)
    im = im.resize((w, h), Image.LANCZOS)
    return _redondear(im, max(4, h // 6))


def _estrella(d, cx, cy, r, color):
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.42
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    d.polygon(pts, fill=color)


@lru_cache(maxsize=32)
def icono(cod: str, tam: int = 96) -> Image.Image:
    if cod in ("es", "eu", "de", "us", "jp", "gb", "fr", "it", "cn", "mundo"):
        return bandera(cod, tam, int(tam * 2 / 3))
    s = 3
    T = tam * s
    im = Image.new("RGBA", (T, T), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if cod in ("oro", "plata"):
        claro, medio, oscuro = (((255, 226, 120), (240, 180, 40), (176, 120, 20)) if cod == "oro"
                                else ((240, 244, 250), (190, 198, 212), (120, 130, 150)))
        for k, (dx, dy) in enumerate(((0.12, 0.52), (0.5, 0.52), (0.31, 0.22))):
            x, y, w, h = T * dx, T * dy, T * 0.38, T * 0.26
            d.polygon([(x, y + h), (x + w, y + h), (x + w * 0.82, y), (x + w * 0.18, y)], fill=medio)
            d.polygon([(x + w * 0.18, y), (x + w * 0.82, y), (x + w * 0.72, y + h * 0.3), (x + w * 0.28, y + h * 0.3)],
                      fill=claro)
            d.line([(x, y + h), (x + w, y + h)], fill=oscuro, width=s * 3)
    elif cod == "petroleo":
        cx = T / 2
        d.polygon([(cx, T * 0.08), (cx - T * 0.3, T * 0.58), (cx + T * 0.3, T * 0.58)], fill=(40, 44, 60))
        d.ellipse([cx - T * 0.3, T * 0.36, cx + T * 0.3, T * 0.92], fill=(40, 44, 60))
        d.ellipse([cx - T * 0.16, T * 0.5, cx - T * 0.04, T * 0.7], fill=(120, 130, 160))
        d.ellipse([cx - T * 0.3, T * 0.36, cx + T * 0.3, T * 0.92], outline=(255, 255, 255, 90), width=s * 3)
    elif cod == "gas":
        cx = T / 2
        d.polygon([(cx, T * 0.05), (cx - T * 0.32, T * 0.6), (cx + T * 0.32, T * 0.6)], fill=(60, 140, 255))
        d.ellipse([cx - T * 0.32, T * 0.35, cx + T * 0.32, T * 0.95], fill=(60, 140, 255))
        d.polygon([(cx, T * 0.38), (cx - T * 0.16, T * 0.7), (cx + T * 0.16, T * 0.7)], fill=(170, 215, 255))
        d.ellipse([cx - T * 0.16, T * 0.58, cx + T * 0.16, T * 0.9], fill=(170, 215, 255))
    elif cod == "btc":
        d.ellipse([0, 0, T - 1, T - 1], fill=(247, 147, 26))
        f = fuente("Black", int(T * 0.62))
        d.text((T / 2, T / 2 + T * 0.02), "B", font=f, fill=BLANCO, anchor="mm")
        for dx in (-0.07, 0.05):
            d.rectangle([T * (0.5 + dx) - s * 3, T * 0.13, T * (0.5 + dx) + s * 3, T * 0.87], fill=BLANCO)
        d.text((T / 2, T / 2 + T * 0.02), "B", font=f, fill=BLANCO, anchor="mm")
    elif cod == "eth":
        d.ellipse([0, 0, T - 1, T - 1], fill=(98, 126, 234))
        cx = T / 2
        d.polygon([(cx, T * 0.12), (cx - T * 0.22, T * 0.52), (cx, T * 0.64)], fill=(255, 255, 255, 230))
        d.polygon([(cx, T * 0.12), (cx + T * 0.22, T * 0.52), (cx, T * 0.64)], fill=(220, 225, 255, 255))
        d.polygon([(cx, T * 0.7), (cx - T * 0.22, T * 0.57), (cx, T * 0.9)], fill=(255, 255, 255, 230))
        d.polygon([(cx, T * 0.7), (cx + T * 0.22, T * 0.57), (cx, T * 0.9)], fill=(220, 225, 255, 255))
    elif cod == "eurusd":
        d.ellipse([0, 0, T - 1, T - 1], fill=(36, 70, 140))
        f = fuente("Black", int(T * 0.42))
        d.text((T * 0.36, T * 0.5), "€", font=f, fill=ACENTO, anchor="mm")
        d.text((T * 0.66, T * 0.52), "$", font=f, fill=(150, 230, 170), anchor="mm")
    return im.resize((tam, tam), Image.LANCZOS)


def triangulo(d, x, y, tam, sube: bool, color):
    if sube:
        d.polygon([(x, y + tam), (x + tam, y + tam), (x + tam / 2, y)], fill=color)
    else:
        d.polygon([(x, y), (x + tam, y), (x + tam / 2, y + tam)], fill=color)


def pastilla(x: float | None, tam: int = 40) -> Image.Image:
    """Píldora de color con ▲/▼ y el porcentaje."""
    f = fuente("Black", tam)
    txt = fpct(x).replace("+", "").replace("−", "")
    col = color_cambio(x)
    tri = int(tam * 0.55)
    w = int(f.getlength(txt) + tri + tam * 1.3)
    h = int(tam * 1.55)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=col + (255,))
    triangulo(d, tam * 0.55, (h - tri) / 2, tri, (x or 0) >= 0, OSCURO)
    d.text((tam * 0.55 + tri + tam * 0.3, h / 2), txt, font=f, fill=OSCURO, anchor="lm")
    return im


def grafico(serie: list[float], w: int, h: int, color, grosor: int = 6, relleno: bool = True) -> Image.Image:
    s = 2
    W, H = w * s, h * s
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if len(serie) < 2:
        return im.resize((w, h))
    lo, hi = min(serie), max(serie)
    rango = (hi - lo) or abs(hi) * 0.01 or 1
    pad = grosor * s
    pts = [(pad + i * (W - 2 * pad) / (len(serie) - 1), pad + (1 - (v - lo) / rango) * (H - 2 * pad - 4 * s))
           for i, v in enumerate(serie)]
    if relleno:
        grad = np.linspace(110, 0, H)[:, None].repeat(W, axis=1).astype(np.uint8)
        capa = Image.new("RGBA", (W, H), color + (0,))
        capa.putalpha(Image.fromarray(grad))
        mascara = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mascara).polygon(pts + [(pts[-1][0], H), (pts[0][0], H)], fill=255)
        im.paste(capa, (0, 0), mascara)
    d = ImageDraw.Draw(im)
    d.line(pts, fill=color + (255,), width=grosor * s, joint="curve")
    x, y = pts[-1]
    r = grosor * s * 1.4
    d.ellipse([x - r, y - r, x + r, y + r], fill=BLANCO, outline=color, width=s * 3)
    return im.resize((w, h), Image.LANCZOS)


def tarjeta(w: int, h: int, color=TARJETA, borde=BORDE, radio=30) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radio, fill=color, outline=borde, width=2)
    return im


def envolver(txt: str, f, ancho: int) -> list[str]:
    lineas, actual = [], ""
    for p in txt.split():
        prueba = (actual + " " + p).strip()
        if f.getlength(prueba) <= ancho or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas


# ---------------------------------------------------------------- compositor
class Compositor:
    def __init__(self, merc, agenda, guion, plan, total, hoy: date, modo: str, fuentes_txt: str):
        self.merc, self.agenda, self.guion = merc, agenda, guion
        self.plan, self.total, self.hoy, self.modo = plan, total, hoy, modo
        self.sem = modo in ("semanal", "previa")
        self.fecha_txt = f"{DIAS[hoy.weekday()]} {hoy.day} de {['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'][hoy.month - 1]}".upper()
        self.fuentes_txt = fuentes_txt
        if self.sem:
            PILLS["agenda"] = "LA SEMANA QUE VIENE"
            PILLS["bolsas"] = "BOLSAS · LA SEMANA"
        if modo == "noche":
            PILLS["agenda"] = "AGENDA DE MAÑANA"
        self._subs = []
        for p in plan:
            trozos = _trocear_subtitulos(p["texto"])
            pesos = [len(t) + 4 for t in trozos]
            t, dur = p["inicio"], p["fin"] - p["inicio"]
            for tr, w in zip(trozos, pesos):
                d = dur * w / sum(pesos)
                self._subs.append((t, t + d, tr))
                t += d
        self.ventanas = []
        for i, p in enumerate(plan):
            ini = 0 if i == 0 else max(plan[i - 1]["fin"], p["inicio"] - 0.35)
            fin = total if i == len(plan) - 1 else max(p["fin"], plan[i + 1]["inicio"] - 0.35)
            self.ventanas.append((ini, fin, p["seg"]))
        self._elems = {}
        self.base = self._base()
        self.ticker = self._ticker()

    def cambio(self, a):
        return a.get("semana") if self.sem else a["cambio"]

    # ------------------------------------------------ capas fijas
    def _base(self):
        im = fondo().convert("RGBA")
        d = ImageDraw.Draw(im)
        d.text((ANCHO / 2, 150), NOMBRE_CANAL, font=fuente("ExtraBold", 34), fill=ACENTO, anchor="ma")
        f2 = _ajustar(self.fecha_txt, "Black", 72, 960)
        d.text((ANCHO / 2 + 3, 200), self.fecha_txt, font=f2, fill=(0, 0, 0, 120), anchor="ma")
        d.text((ANCHO / 2, 196), self.fecha_txt, font=f2, fill=BLANCO, anchor="ma")
        d.text((ANCHO / 2, 1418), AVISO.upper(), font=fuente("ExtraBold", 24), fill=(255, 214, 120), anchor="ma")
        d.text((ANCHO / 2, 1450), self.fuentes_txt, font=_ajustar(self.fuentes_txt, "SemiBold", 22, 980),
               fill=SUAVE, anchor="ma")
        return im

    def _ticker(self):
        f, fb = fuente("ExtraBold", 28), fuente("Black", 28)
        piezas = []
        for k in ("ibex", "stoxx", "dax", "sp500", "nasdaq", "dow", "nikkei", "oro", "plata", "brent", "wti", "gas",
                  "eurusd", "btc", "eth"):
            if k in self.merc:
                a = self.merc[k]
                piezas.append((a["nombre"].upper(), precio_pantalla(a), self.cambio(a)))
        ancho = sum(f.getlength(n + "  ") + fb.getlength(p + "  ") + fb.getlength(fpct(c)) + 90 for n, p, c in piezas)
        ancho = int(ancho) + 10
        im = Image.new("RGBA", (ancho * 2, 44), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for rep in range(2):
            x = rep * ancho
            for n, p, c in piezas:
                d.text((x, 22), n, font=f, fill=SUAVE, anchor="lm")
                x += f.getlength(n + "  ")
                d.text((x, 22), p, font=fb, fill=BLANCO, anchor="lm")
                x += fb.getlength(p + "  ")
                triangulo(d, x, 13, 18, (c or 0) >= 0, color_cambio(c))
                x += 26
                d.text((x, 22), fpct(c).replace("+", ""), font=fb, fill=color_cambio(c), anchor="lm")
                x += fb.getlength(fpct(c)) + 64
        self._ancho_ticker = ancho
        return im

    # ------------------------------------------------ elementos por bloque
    def elementos(self, seg):
        if seg not in self._elems:
            fn = getattr(self, f"_e_{seg}", None)
            self._elems[seg] = fn() if fn else []
        return self._elems[seg]

    def _fila(self, a, w=890, h=90, etiqueta=None):
        im = tarjeta(w, h, radio=24)
        d = ImageDraw.Draw(im)
        ic = icono(a["icono"], 60) if a["grupo"] != "bolsa" else bandera(a["icono"], 60, 40)
        im.alpha_composite(ic, (20, (h - ic.height) // 2))
        d.text((100, h / 2), etiqueta or a["nombre"], font=_ajustar(etiqueta or a["nombre"], "ExtraBold", 38, 270),
               fill=BLANCO, anchor="lm")
        d.text((560, h / 2), precio_pantalla(a), font=_ajustar(precio_pantalla(a), "Black", 40, 200), fill=BLANCO,
               anchor="rm")
        sp = grafico(a.get("serie", [])[-12:], 110, 56, color_cambio(self.cambio(a)), grosor=3, relleno=False)
        im.alpha_composite(sp, (585, (h - 56) // 2))
        p = pastilla(self.cambio(a), 30)
        im.alpha_composite(p, (w - p.width - 18, (h - p.height) // 2))
        return im

    def _heroe(self, a, w, h, subtitulo, chart_h):
        im = tarjeta(w, h, radio=36)
        d = ImageDraw.Draw(im)
        ic = icono(a["icono"], 84) if a["grupo"] != "bolsa" else bandera(a["icono"], 84, 56)
        im.alpha_composite(ic, (34, 34))
        d.text((140, 30), a["nombre"].upper(), font=fuente("Black", 50), fill=BLANCO)
        d.text((142, 88), subtitulo, font=fuente("SemiBold", 28), fill=SUAVE)
        valor = precio_pantalla(a) + {"puntos": "", "$": " $"}.get(a["unidad"], " $")
        fv = _ajustar(valor, "Black", 104, w - 340)
        d.text((34, 128), valor, font=fv, fill=BLANCO)
        p = pastilla(self.cambio(a), 46)
        im.alpha_composite(p, (w - p.width - 34, 150))
        return im, grafico(a.get("serie", []), w - 60, chart_h, color_cambio(self.cambio(a)))

    def _cuando_txt(self, a):
        if self.sem:
            return "En la semana"
        d = date.fromisoformat(a["fecha"])
        if a["grupo"] in ("cripto", "materia", "divisa"):
            return "Ahora mismo · últimas 24 h" if a["grupo"] == "cripto" else "Ahora mismo"
        if (self.hoy - d).days == 1:
            return "Cierre de ayer"
        if d == self.hoy:
            return "Cierre de hoy"
        return f"Cierre del {DIAS[d.weekday()]} {d.day}"

    def _e_intro(self):
        el = []
        lineas = {"diario": ("¿QUÉ PASA HOY", "CON TU DINERO?"), "noche": ("ASÍ HA IDO", "EL DÍA"), "semanal": ("ASÍ HA IDO", "LA SEMANA"),
                  "previa": ("LO QUE VIENE", "ESTA SEMANA")}[self.modo]
        for k, txt in enumerate(lineas):
            f = _ajustar(txt, "Black", 112, 980)
            im = Image.new("RGBA", (1000, 140), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.text((504, 76), txt, font=f, fill=(0, 0, 0, 140), anchor="mm")
            d.text((500, 70), txt, font=f, fill=BLANCO if k == 0 else ACENTO, anchor="mm")
            el.append({"img": im, "x": 40, "y": 500 + k * 135, "delay": 0.1 + k * 0.15, "tipo": "pop"})
        claves = [k for k in ("ibex", "btc", "oro") if k in self.merc]
        for i, k in enumerate(claves):
            a = self.merc[k]
            im = tarjeta(280, 300, radio=32)
            d = ImageDraw.Draw(im)
            ic = icono(a["icono"], 80) if a["grupo"] != "bolsa" else bandera(a["icono"], 84, 56)
            im.alpha_composite(ic, ((280 - ic.width) // 2, 26))
            d.text((140, 136), a["nombre"].upper(), font=_ajustar(a["nombre"].upper(), "ExtraBold", 34, 250),
                   fill=SUAVE, anchor="mm")
            pv = precio_pantalla(a)
            d.text((140, 190), pv, font=_ajustar(pv, "Black", 54, 250), fill=BLANCO, anchor="mm")
            p = pastilla(self.cambio(a), 32)
            im.alpha_composite(p, ((280 - p.width) // 2, 230))
            el.append({"img": im, "x": 40 + i * 305, "y": 900, "delay": 0.55 + i * 0.15, "tipo": "pop"})
        return el

    def _e_bolsas(self):
        el = []
        if "ibex" in self.merc:
            a = self.merc["ibex"]
            im, g = self._heroe(a, 1000, 370, self._cuando_txt(a), 120)
            el.append({"img": im, "x": 40, "y": Y0, "delay": 0.0, "tipo": "pop"})
            el.append({"img": g, "x": 70, "y": Y0 + 240, "delay": 0.35, "tipo": "wipe", "dur": 0.9})
        filas = [k for k in ("stoxx", "dax", "sp500", "nasdaq", "dow", "nikkei") if k in self.merc]
        for i, k in enumerate(filas):
            el.append({"img": self._fila(self.merc[k]), "x": 40, "y": 768 + i * 94, "delay": 0.6 + i * 0.12,
                       "tipo": "slide"})
        return el

    def _e_cripto(self):
        el = []
        if "btc" in self.merc:
            a = self.merc["btc"]
            im, g = self._heroe(a, 1000, 620, self._cuando_txt(a), 330)
            el.append({"img": im, "x": 40, "y": Y0, "delay": 0.0, "tipo": "pop"})
            el.append({"img": g, "x": 70, "y": Y0 + 260, "delay": 0.35, "tipo": "wipe", "dur": 1.1})
            chips = [("7 DÍAS", a.get("semana")), ("30 DÍAS", a.get("mes"))]
            for i, (etq, v) in enumerate(chips):
                if v is None:
                    continue
                im = tarjeta(435, 86, radio=24)
                d = ImageDraw.Draw(im)
                d.text((24, 43), etq, font=fuente("ExtraBold", 32), fill=SUAVE, anchor="lm")
                p = pastilla(v, 30)
                im.alpha_composite(p, (435 - p.width - 18, (86 - p.height) // 2))
                el.append({"img": im, "x": 40 + i * 455, "y": Y0 + 645, "delay": 0.9 + i * 0.12, "tipo": "slide"})
        if "eth" in self.merc:
            el.append({"img": self._fila(self.merc["eth"]), "x": 40, "y": Y0 + 750, "delay": 1.2, "tipo": "slide"})
        return el

    def _tarjeta_materia(self, a, w=435, h=290):
        im = tarjeta(w, h, radio=30)
        d = ImageDraw.Draw(im)
        im.alpha_composite(icono(a["icono"], 72), (24, 22))
        d.text((112, 30), a["nombre"].upper(), font=_ajustar(a["nombre"].upper(), "Black", 38, w - 130), fill=BLANCO)
        d.text((113, 74), a["unidad"], font=fuente("SemiBold", 24), fill=SUAVE)
        pv = precio_pantalla(a)
        d.text((24, 112), pv, font=_ajustar(pv, "Black", 66, w - 48), fill=BLANCO)
        p = pastilla(self.cambio(a), 30)
        im.alpha_composite(p, (24, 196))
        sp = grafico(a.get("serie", []), w - p.width - 70, 70, color_cambio(self.cambio(a)), grosor=3, relleno=False)
        im.alpha_composite(sp, (p.width + 46, 190))
        return im

    def _e_materias(self):
        el = []
        rejilla = [k for k in ("oro", "brent", "plata", "gas") if k in self.merc][:4]
        for i, k in enumerate(rejilla):
            x, y = 40 + (i % 2) * 455, Y0 + (i // 2) * 310
            el.append({"img": self._tarjeta_materia(self.merc[k]), "x": x, "y": y, "delay": 0.05 + i * 0.13,
                       "tipo": "pop"})
        filas = [k for k in ("eurusd", "wti") if k in self.merc]
        for i, k in enumerate(filas):
            etq = "Euro / dólar" if k == "eurusd" else "Petróleo WTI"
            el.append({"img": self._fila(self.merc[k], etiqueta=etq), "x": 40, "y": Y0 + 640 + i * 100,
                       "delay": 0.7 + i * 0.12, "tipo": "slide"})
        return el

    def _e_agenda(self):
        el = []
        trad = self.guion.get("agenda_es") or {}
        evs = self.agenda.get("pantalla", [])[:5]
        if not evs:
            im = tarjeta(890, 300, radio=36)
            d = ImageDraw.Draw(im)
            d.text((445, 110), "AGENDA TRANQUILA", font=fuente("Black", 64), fill=ACENTO, anchor="mm")
            d.text((445, 190), "Hoy no hay citas de las gordas", font=fuente("ExtraBold", 38), fill=BLANCO, anchor="mm")
            el.append({"img": im, "x": 40, "y": Y0 + 120, "delay": 0.1, "tipo": "pop"})
        alto = 150 if len(evs) <= 4 else 132
        for i, e in enumerate(evs):
            im = tarjeta(890, alto - 14, radio=26)
            d = ImageDraw.Draw(im)
            h = alto - 14
            d.rounded_rectangle([12, 12, 190, h - 12], radius=20, fill=ACENTO)
            if self.sem:
                dd = date.fromisoformat(e["fecha"])
                d.text((101, h / 2 - 20), f"{DIAS[dd.weekday()][:3].upper()} {dd.day}", font=fuente("Black", 40),
                       fill=OSCURO, anchor="mm")
                d.text((101, h / 2 + 24), e.get("hora") or "", font=fuente("ExtraBold", 30), fill=OSCURO, anchor="mm")
            else:
                hora = e.get("hora") or "TODO EL DÍA"
                d.text((101, h / 2), hora, font=_ajustar(hora, "Black", 50, 160), fill=OSCURO, anchor="mm")
            b = bandera(e.get("bandera", "mundo"), 66, 44)
            im.alpha_composite(b, (214, int(h / 2 - 22)))
            titulo = trad.get(e.get("original", ""), e["titulo"]) if not e.get("traducido", True) else e["titulo"]
            f = fuente("ExtraBold", 38)
            lineas = envolver(titulo, f, 535)
            if len(lineas) > 2:
                f = fuente("ExtraBold", 32)
                lineas = envolver(titulo, f, 535)[:2]
            y = h / 2 - (len(lineas) * (f.size + 6)) / 2
            for l in lineas:
                d.text((304, y), l, font=f, fill=BLANCO)
                y += f.size + 6
            nivel = {"High": 3, "Medium": 2}.get(e.get("impacto"), 1)
            for k in range(3):
                col = (ROJO if nivel == 3 else ACENTO) if k < nivel else (255, 255, 255, 40)
                d.rounded_rectangle([868, h / 2 + 18 - k * 16, 878, h / 2 + 28 - k * 16], radius=3, fill=col)
            el.append({"img": im, "x": 40, "y": Y0 + i * alto, "delay": 0.05 + i * 0.14, "tipo": "slide"})
        # Próximas reuniones de bancos centrales
        y = Y0 + max(len(evs), 2) * alto + 18
        for i, p in enumerate(self.agenda.get("proximas", [])[:2]):
            if y > Y1 - 90:
                break
            dd = date.fromisoformat(p["fecha"])
            txt = f"{'HOY' if p['dias'] == 0 else DIAS[dd.weekday()][:3].upper() + ' ' + str(dd.day)}"
            im = tarjeta(435, 86, color=(255, 196, 45, 30), borde=ACENTO + (160,), radio=24)
            d = ImageDraw.Draw(im)
            im.alpha_composite(bandera("us" if p["banco"] == "FED" else "eu", 54, 36), (20, 25))
            d.text((90, 43), f"{p['banco']}", font=fuente("Black", 36), fill=BLANCO, anchor="lm")
            d.text((415, 43), txt, font=fuente("Black", 34), fill=ACENTO, anchor="rm")
            el.append({"img": im, "x": 40 + i * 455, "y": int(y), "delay": 0.8 + i * 0.12, "tipo": "pop"})
        return el

    def _e_noticias(self):
        el = []
        tits = (self.guion.get("titulares") or [])[:3]
        alto = 300 if len(tits) <= 2 else 260
        for i, t in enumerate(tits):
            im = tarjeta(890, alto - 20, radio=32)
            d = ImageDraw.Draw(im)
            d.ellipse([26, 26, 96, 96], fill=ACENTO)
            d.text((61, 62), str(i + 1), font=fuente("Black", 46), fill=OSCURO, anchor="mm")
            fuente_txt = (t.get("fuente") or "").upper()
            d.text((120, 46), fuente_txt, font=fuente("ExtraBold", 28), fill=SUAVE)
            f = fuente("Black", 50)
            lineas = envolver(t.get("titulo", ""), f, 820)
            if len(lineas) > 3:
                f = fuente("Black", 42)
                lineas = envolver(t.get("titulo", ""), f, 830)[:3]
            y = 116
            for l in lineas:
                d.text((30, y), l, font=f, fill=BLANCO)
                y += f.size + 10
            el.append({"img": im, "x": 40, "y": Y0 + 20 + i * alto, "delay": 0.1 + i * 0.25, "tipo": "slide"})
        return el

    def _e_cierre(self):
        el = []
        for i, (txt, col, sube) in enumerate((("TORO · SUBE", VERDE, True), ("OSO · BAJA", ROJO, False))):
            im = Image.new("RGBA", (430, 120), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle([0, 0, 429, 119], radius=60, fill=col)
            triangulo(d, 36, 38, 44, sube, OSCURO)
            d.text((100, 60), txt, font=_ajustar(txt, "Black", 52, 310), fill=OSCURO, anchor="lm")
            el.append({"img": im, "x": 75 + i * 500, "y": 470, "delay": 0.15 + i * 0.15, "tipo": "pop"})
        im = Image.new("RGBA", (840, 340), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, 839, 339], radius=40, fill=ACENTO)
        d.text((420, 76), LEMA, font=fuente("Black", 70), fill=OSCURO, anchor="mm")
        d.text((420, 150), "¡Dímelo en comentarios!", font=fuente("ExtraBold", 44), fill=OSCURO, anchor="mm")
        d.line([(110, 200), (730, 200)], fill=(15, 25, 50, 90), width=3)
        d.text((420, 256), "Sígueme · información actualizada cada día",
               font=_ajustar("Sígueme · información actualizada cada día", "ExtraBold", 40, 780), fill=OSCURO,
               anchor="mm")
        el.append({"img": im, "x": 120, "y": 660, "delay": 0.5, "tipo": "pop"})
        return el

    # ------------------------------------------------ fotograma
    def ventana(self, t):
        for i, (a, b, seg) in enumerate(self.ventanas):
            if a <= t < b or i == len(self.ventanas) - 1:
                return i, a, seg
        return 0, 0, self.ventanas[0][2]

    def fotograma(self, t) -> Image.Image:
        i, ini, seg = self.ventana(t)
        dt = t - ini
        img = self.base.copy()
        d = ImageDraw.Draw(img)
        self._pill(d, seg, dt)
        for e in self.elementos(seg):
            p = dt - e["delay"]
            if p <= 0:
                continue
            im = e["img"]
            if e["tipo"] == "pop":
                s = _ease_back(p / 0.4)
                if s < 0.02:
                    continue
                w, h = max(1, int(im.width * s)), max(1, int(im.height * s))
                imr = im if (w, h) == im.size else im.resize((w, h), Image.BILINEAR)
                img.alpha_composite(imr, (int(e["x"] + (im.width - w) / 2), int(e["y"] + (im.height - h) / 2)))
            elif e["tipo"] == "slide":
                s = min(1.0, p / 0.35)
                s = 1 - (1 - s) ** 3
                x = int(e["x"] + (1 - s) * 260)
                if s < 1:
                    im = im.copy()
                    im.putalpha(im.getchannel("A").point(lambda v, s=s: int(v * s)))
                img.alpha_composite(im, (x, e["y"]))
            elif e["tipo"] == "wipe":
                s = min(1.0, p / e.get("dur", 0.8))
                s = 1 - (1 - s) ** 2
                w = max(1, int(im.width * s))
                img.alpha_composite(im.crop((0, 0, w, im.height)), (e["x"], e["y"]))
        # Cinta de cotizaciones que se desplaza
        off = int((t * 90) % self._ancho_ticker)
        img.alpha_composite(self.ticker.crop((off, 0, off + ANCHO, 44)), (0, TICKER_Y - 22))
        self._subtitulo(img, ImageDraw.Draw(img), t)
        if t < PORTADA_FIN:
            alfa = 1.0 if t < PORTADA_FIJA else 1 - (t - PORTADA_FIJA) / (PORTADA_FIN - PORTADA_FIJA)
            portada = self.portada()
            if alfa < 1:
                portada = portada.copy()
                portada.putalpha(portada.getchannel("A").point(lambda a: int(a * alfa)))
            img.alpha_composite(portada)
        return img.convert("RGB")

    def _pill(self, d, seg, dt):
        txt = PILLS.get(seg)
        if not txt:
            return
        f = fuente("Black", 40)
        w = f.getlength(txt) + 60
        s = _ease_back(dt / 0.3)
        d.rounded_rectangle([ANCHO / 2 - w / 2 * s, 286, ANCHO / 2 + w / 2 * s, 344], radius=29, fill=ACENTO)
        if s > 0.7:
            d.text((ANCHO / 2, 316), txt, font=f, fill=OSCURO, anchor="mm")

    def portada(self) -> Image.Image:
        """Primer fotograma = miniatura del perfil (recorte 3:4: todo en la franja central)."""
        if getattr(self, "_portada", None) is not None:
            return self._portada
        im = Image.new("RGBA", (ANCHO, ALTO), (6, 12, 30, 246))
        d = ImageDraw.Draw(im)
        cy = ALTO / 2
        marca = {"diario": "RESUMEN ECONÓMICO", "noche": "RESUMEN DEL DÍA", "semanal": "LA SEMANA EN BOLSA", "previa": "LO QUE VIENE"}[self.modo]
        d.text((ANCHO / 2, cy - 520), marca, font=fuente("ExtraBold", 52), fill=ACENTO, anchor="mm")
        dia_sem, resto = (self.fecha_txt.split(" ", 1) + [""])[:2]
        f1 = _ajustar(dia_sem, "Black", 190, 980)
        d.text((ANCHO / 2 + 5, cy - 332), dia_sem, font=f1, fill=(0, 0, 0, 150), anchor="mm")
        d.text((ANCHO / 2, cy - 340), dia_sem, font=f1, fill=BLANCO, anchor="mm")
        d.text((ANCHO / 2, cy - 180), resto, font=_ajustar(resto, "Black", 104, 980), fill=BLANCO, anchor="mm")
        claves = [k for k in ("ibex", "btc", "oro") if k in self.merc]
        for i, k in enumerate(claves):
            a = self.merc[k]
            y = cy - 50 + i * 150
            fila = tarjeta(900, 128, radio=34)
            fd = ImageDraw.Draw(fila)
            ic = icono(a["icono"], 76) if a["grupo"] != "bolsa" else bandera(a["icono"], 84, 56)
            fila.alpha_composite(ic, (26, (128 - ic.height) // 2))
            fd.text((130, 64), a["nombre"].upper(), font=_ajustar(a["nombre"].upper(), "Black", 58, 380), fill=BLANCO,
                    anchor="lm")
            p = pastilla(self.cambio(a), 54)
            fila.alpha_composite(p, (900 - p.width - 22, (128 - p.height) // 2))
            im.alpha_composite(fila, (90, int(y)))
        f3 = fuente("Black", 56)
        w = f3.getlength(LEMA) + 80
        d.rounded_rectangle([ANCHO / 2 - w / 2, cy + 440, ANCHO / 2 + w / 2, cy + 534], radius=47, fill=ACENTO)
        d.text((ANCHO / 2, cy + 487), LEMA, font=f3, fill=OSCURO, anchor="mm")
        self._portada = im
        return im

    def _subtitulo(self, img, d, t):
        txt = next((s for a, b, s in self._subs if a <= t < b), None)
        if not txt:
            return
        f = _ajustar(txt, "Black", 56, 880)
        lineas = [txt]
        if f.size < 46 and len(txt.split()) > 2:
            pal = txt.split()
            mitad = len(pal) // 2
            lineas = [" ".join(pal[:mitad]), " ".join(pal[mitad:])]
            f = _ajustar(max(lineas, key=len), "Black", 56, 880)
        alto = len(lineas) * (f.size + 14)
        anchomax = max(f.getlength(l) for l in lineas)
        d.rounded_rectangle([ANCHO / 2 - anchomax / 2 - 28, SUB_Y - 18, ANCHO / 2 + anchomax / 2 + 28,
                             SUB_Y + alto + 8], radius=26, fill=(0, 0, 0, 170))
        for k, l in enumerate(lineas):
            x = ANCHO / 2 - f.getlength(l) / 2
            y = SUB_Y + k * (f.size + 14)
            for palabra in l.split(" "):
                if re.search(r"\bsub|\bgan|alza", palabra, re.I):
                    color = VERDE
                elif re.search(r"\bbaj|\bpierd|\bcaíd|\bcae", palabra, re.I):
                    color = ROJO
                elif re.search(r"\d", palabra):
                    color = ACENTO
                else:
                    color = BLANCO
                d.text((x, y), palabra, font=f, fill=color)
                x += f.getlength(palabra + " ")
