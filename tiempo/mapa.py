"""Mapa de España, iconos del tiempo y marcadores de ciudad (dibujo vectorial propio con Pillow)."""
from __future__ import annotations

import json
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import (ASSETS, DESPLAZAMIENTO_CANARIAS, FUENTES_TIPO, PROVINCIAS_CANARIAS, RECUADRO_CANARIAS,
                     REGIONES)

K = math.cos(math.radians(40))  # corrección de longitud (proyección equirectangular)

# Paleta
MAR_ARRIBA = (10, 28, 61)
MAR_ABAJO = (18, 52, 102)
TIERRA = (232, 222, 200)
TIERRA_APAGADA = (150, 158, 170)
TIERRA_FOCO = (246, 236, 212)
VECINOS = (78, 92, 118)          # Portugal, Francia, norte de África...: presentes pero apagados
BORDE_VECINOS = (150, 165, 190, 110)
BORDE = (255, 255, 255, 110)
BLANCO = (255, 255, 255)
AZUL_MIN = (140, 205, 255)


@lru_cache(maxsize=None)
def fuente(peso: str, tam: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FUENTES_TIPO / f"Inter-{peso}.otf"), tam)


@lru_cache(maxsize=1)
def vecinos():
    """Siluetas de países vecinos (Natural Earth, dominio público), recortadas y simplificadas."""
    ruta = ASSETS / "vecinos.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []


@lru_cache(maxsize=1)
def provincias():
    return json.loads((ASSETS / "espana.json").read_text(encoding="utf-8"))


def lonlat_mapa(lon, lat, provincia_canaria=False):
    """Las Canarias se desplazan al recuadro inferior izquierdo."""
    if provincia_canaria:
        return lon + DESPLAZAMIENTO_CANARIAS[0], lat + DESPLAZAMIENTO_CANARIAS[1]
    return lon, lat


def es_canaria(lat):
    return lat < 30


class Proyeccion:
    def __init__(self, vista, ancho, alto, margen=40):
        lon0, lon1, lat0, lat1 = vista
        self.vista = vista
        dx, dy = (lon1 - lon0) * K, (lat1 - lat0)
        self.s = min((ancho - 2 * margen) / dx, (alto - 2 * margen) / dy)
        self.cx, self.cy = (lon0 + lon1) / 2, (lat0 + lat1) / 2
        self.ancho, self.alto = ancho, alto

    def __call__(self, lon, lat):
        return (self.ancho / 2 + (lon - self.cx) * K * self.s, self.alto / 2 - (lat - self.cy) * self.s)

    def ciudad(self, c):
        lon, lat = lonlat_mapa(c["lon"], c["lat"], es_canaria(c["lat"]))
        return self(lon, lat)

    @property
    def muestra_canarias(self):
        return self.vista[0] < -10


def interpolar_vista(a, b, t):
    """Interpolación suave entre dos vistas (centro lineal, zoom geométrico)."""
    t = t * t * (3 - 2 * t)
    ca = ((a[0] + a[1]) / 2, (a[2] + a[3]) / 2)
    cb = ((b[0] + b[1]) / 2, (b[2] + b[3]) / 2)
    sa, sb = (a[1] - a[0], a[3] - a[2]), (b[1] - b[0], b[3] - b[2])
    c = (ca[0] + (cb[0] - ca[0]) * t, ca[1] + (cb[1] - ca[1]) * t)
    s = (sa[0] * (sb[0] / sa[0]) ** t, sa[1] * (sb[1] / sa[1]) ** t)
    return (c[0] - s[0] / 2, c[0] + s[0] / 2, c[1] - s[1] / 2, c[1] + s[1] / 2)


_TIERRA = {}


def mascara_tierra(pr: "Proyeccion") -> Image.Image:
    """Máscara (L, 255 = tierra) con la misma proyección que el mapa, para saber qué es mar."""
    clave = (tuple(pr.vista), pr.ancho, pr.alto)
    if clave not in _TIERRA:
        m = Image.new("L", (int(pr.ancho), int(pr.alto)), 0)
        d = ImageDraw.Draw(m)
        for pais in vecinos():
            for anillo in pais["anillos"]:
                d.polygon([pr(x, y) for x, y in anillo], fill=255)
        for p in provincias():
            canaria = p["nombre"] in PROVINCIAS_CANARIAS
            if canaria and not pr.muestra_canarias:
                continue
            for anillo in p["anillos"]:
                d.polygon([pr(*lonlat_mapa(x, y, canaria)) for x, y in anillo], fill=255)
        _TIERRA[clave] = m.filter(ImageFilter.MaxFilter(9))   # un poco de margen con la costa
    return _TIERRA[clave]


_ETIQ = {}


def etiquetas_provincias(pr: "Proyeccion"):
    """(array con el índice+1 de la provincia en cada píxel, lista de nombres, máscara de costa) para esta vista."""
    import numpy as np
    clave = (tuple(pr.vista), pr.ancho, pr.alto)
    if clave not in _ETIQ:
        lab = Image.new("I", (int(pr.ancho), int(pr.alto)), 0)
        d = ImageDraw.Draw(lab)
        nombres = []
        for k, p in enumerate(provincias()):
            canaria = p["nombre"] in PROVINCIAS_CANARIAS
            nombres.append(p["nombre"])
            if canaria and not pr.muestra_canarias:
                continue
            for anillo in p["anillos"]:
                d.polygon([pr(*lonlat_mapa(x, y, canaria)) for x, y in anillo], fill=k + 1)
        arr = np.array(lab, dtype=np.int32)
        tierra = Image.fromarray(((arr > 0) * 255).astype(np.uint8))
        costa = np.array(tierra.filter(ImageFilter.MaxFilter(5))) & ~np.array(tierra)   # borde tierra-mar
        _ETIQ[clave] = (arr, nombres, costa > 0)
    return _ETIQ[clave]


def dibujar_mapa(vista, ancho, alto, foco: str | None = None, ss: int = 2) -> Image.Image:
    """Renderiza el mapa (con antialiasing por supermuestreo)."""
    W, H = ancho * ss, alto * ss
    pr = Proyeccion(vista, W, H, margen=40 * ss)
    img = Image.new("RGB", (W, H))
    # Mar con degradado vertical
    grad = Image.linear_gradient("L").resize((W, H))
    img = Image.composite(Image.new("RGB", (W, H), MAR_ABAJO), Image.new("RGB", (W, H), MAR_ARRIBA), grad)
    d = ImageDraw.Draw(img, "RGBA")
    # Rejilla de meridianos y paralelos
    for lon in range(-20, 8, 2):
        x, _ = pr(lon, 0)
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 14), width=ss)
    for lat in range(26, 48, 2):
        _, y = pr(0, lat)
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 14), width=ss)

    # Países vecinos (debajo de todo): así Ceuta y Melilla no flotan en medio del mar
    for pais in vecinos():
        for anillo in pais["anillos"]:
            pts = [pr(x, y) for x, y in anillo]
            d.polygon(pts, fill=VECINOS)
            d.line(pts + [pts[0]], fill=BORDE_VECINOS, width=max(1, int(1.2 * ss)), joint="curve")

    provs_foco = set(REGIONES[foco]["provincias"]) if foco and foco in REGIONES else None
    poligonos = []
    for p in provincias():
        canaria = p["nombre"] in PROVINCIAS_CANARIAS
        if canaria and not pr.muestra_canarias:
            continue
        for anillo in p["anillos"]:
            pts = [pr(*lonlat_mapa(x, y, canaria)) for x, y in anillo]
            poligonos.append((p["nombre"], pts))

    # Sombra de la tierra
    sombra = Image.new("L", (W, H), 0)
    ds = ImageDraw.Draw(sombra)
    for _, pts in poligonos:
        ds.polygon([(x + 6 * ss, y + 10 * ss) for x, y in pts], fill=150)
    sombra = sombra.filter(ImageFilter.GaussianBlur(10 * ss))
    img.paste((3, 10, 25), (0, 0), sombra)

    # Recuadro de Canarias
    if pr.muestra_canarias:
        x0, y1 = pr(RECUADRO_CANARIAS[0], RECUADRO_CANARIAS[2])
        x1, y0 = pr(RECUADRO_CANARIAS[1], RECUADRO_CANARIAS[3])
        d.rounded_rectangle([x0, y0, x1, y1], radius=18 * ss, fill=(255, 255, 255, 18),
                            outline=(255, 255, 255, 90), width=2 * ss)

    for nombre, pts in poligonos:
        if provs_foco is None:
            color = TIERRA
        else:
            color = TIERRA_FOCO if nombre in provs_foco else TIERRA_APAGADA
        d.polygon(pts, fill=color)
    for nombre, pts in poligonos:
        d.line(pts + [pts[0]], fill=(120, 110, 95, 120), width=max(1, int(1.2 * ss)), joint="curve")
    return img.resize((ancho, alto), Image.LANCZOS)


# ---------------------------------------------------------------- Iconos
AMARILLO = (255, 200, 40)
NUBE_CLARA = (250, 252, 255)
NUBE_OSCURA = (150, 162, 182)
GOTA = (70, 160, 255)


FASES = 16          # fotogramas del bucle de cada icono animado
FPS_ICONO = 12      # el bucle dura FASES / FPS_ICONO ≈ 1,3 s


def fase_de(t: float, desfase: float = 0.0) -> int:
    return int((t + desfase) * FPS_ICONO) % FASES


def _sol(d, cx, cy, r, s, giro=0.0, pulso=1.0):
    for i in range(8):
        a = i * math.pi / 4 + giro
        d.line([(cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35),
                (cx + math.cos(a) * r * (1.35 + 0.40 * pulso), cy + math.sin(a) * r * (1.35 + 0.40 * pulso))],
               fill=AMARILLO, width=int(s * 0.06))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMARILLO)


def _nube(d, cx, cy, w, color):
    h = w * 0.42
    d.rounded_rectangle([cx - w / 2, cy, cx + w / 2, cy + h], radius=h / 2, fill=color)
    d.ellipse([cx - w * 0.38, cy - w * 0.14, cx + w * 0.02, cy + w * 0.26], fill=color)
    d.ellipse([cx - w * 0.12, cy - w * 0.30, cx + w * 0.34, cy + w * 0.16], fill=color)


def _gotas(d, s, f, n, x0=0.30, paso=0.20):
    """Gotas que caen en bucle desde la nube."""
    for i in range(n):
        k = (f + i * 0.37) % 1.0
        x = s * (x0 + i * paso) - s * 0.06 * k
        y = s * (0.64 + 0.26 * k)
        largo = s * 0.12
        alfa = int(255 * (1 - max(0, k - 0.75) / 0.25))
        d.line([(x, y), (x - s * 0.04, y + largo)], fill=GOTA + (alfa,), width=int(s * 0.05))


@lru_cache(maxsize=None)
def icono(tipo: str, tam: int, fase: int = 0) -> Image.Image:
    """Icono del tiempo; `fase` (0..FASES-1) da el fotograma de su animación en bucle."""
    f = (fase % FASES) / FASES
    onda = math.sin(2 * math.pi * f)
    s = tam * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if tipo == "sol":
        _sol(d, s / 2, s / 2, s * 0.22, s, giro=f * math.pi / 4, pulso=1 + 0.18 * onda)
    elif tipo == "sol_nubes":
        _sol(d, s * 0.62, s * 0.36, s * 0.17, s, giro=f * math.pi / 4, pulso=1 + 0.15 * onda)
        _nube(d, s * (0.44 + 0.025 * onda), s * 0.48, s * 0.66, NUBE_CLARA)
    elif tipo == "nubes":
        _nube(d, s * (0.60 - 0.03 * onda), s * 0.32, s * 0.50, NUBE_OSCURA)
        _nube(d, s * (0.44 + 0.03 * onda), s * 0.46, s * 0.70, NUBE_CLARA)
    elif tipo in ("lluvia", "chubascos", "tormenta", "nieve"):
        if tipo == "chubascos":
            _sol(d, s * 0.64, s * 0.30, s * 0.15, s, giro=f * math.pi / 4)
        if tipo == "nieve":
            for i, cx in enumerate((0.32, 0.52, 0.72)):
                k = (f + i * 0.33) % 1.0
                x, y = s * cx + s * 0.03 * math.sin(2 * math.pi * (k + i * 0.2)), s * (0.66 + 0.24 * k)
                for j in range(3):
                    a = j * math.pi / 3 + k * math.pi
                    r = s * 0.06
                    d.line([(x - math.cos(a) * r, y - math.sin(a) * r), (x + math.cos(a) * r, y + math.sin(a) * r)],
                           fill=BLANCO, width=int(s * 0.03))
        else:
            _gotas(d, s, f, 2 if tipo == "chubascos" else 3)
        _nube(d, s * (0.48 + 0.015 * onda), s * 0.30, s * 0.72,
              NUBE_CLARA if tipo in ("chubascos", "nieve") else NUBE_OSCURA)
        if tipo == "tormenta" and (f < 0.12 or 0.25 <= f < 0.31):   # el rayo destella dos veces por bucle
            d.polygon([(s * 0.52, s * 0.56), (s * 0.40, s * 0.78), (s * 0.50, s * 0.78), (s * 0.44, s * 0.96),
                       (s * 0.64, s * 0.70), (s * 0.54, s * 0.70), (s * 0.60, s * 0.56)], fill=AMARILLO)
    elif tipo == "calor":      # sol que late con ondas de calor subiendo
        _sol(d, s * 0.5, s * 0.38, s * 0.17, s, giro=f * math.pi / 2, pulso=1 + 0.22 * onda)
        for i, x0 in enumerate((0.28, 0.5, 0.72)):
            k = (f + i * 0.33) % 1.0
            pts = [(s * x0 + s * 0.035 * math.sin(2 * math.pi * (j / 10 * 1.5 + f * 2)), s * (0.95 - 0.28 * j / 10 - 0.08 * k))
                   for j in range(11)]
            d.line(pts, fill=(255, 140, 60, int(255 * (1 - k * 0.5))), width=int(s * 0.035), joint="curve")
    elif tipo == "helada":     # cristal de hielo girando con destellos
        cx, cy, r = s * 0.5, s * 0.5, s * 0.36
        giro = f * math.pi / 3
        col = (200, 235, 255)
        for j in range(6):
            a = giro + j * math.pi / 3
            x1, y1 = cx + math.cos(a) * r, cy + math.sin(a) * r
            d.line([(cx, cy), (x1, y1)], fill=col, width=int(s * 0.05))
            for fr in (0.45, 0.7):
                bx, by = cx + math.cos(a) * r * fr, cy + math.sin(a) * r * fr
                for da in (0.7, -0.7):
                    d.line([(bx, by), (bx + math.cos(a + da) * r * 0.25, by + math.sin(a + da) * r * 0.25)],
                           fill=col, width=int(s * 0.035))
        for j in range(3):     # destellos
            k = (f * 2 + j / 3) % 1.0
            a = j * 2.1
            x, y = cx + math.cos(a) * r * 1.05, cy + math.sin(a) * r * 1.05
            t_ = s * 0.06 * math.sin(math.pi * k)
            d.line([(x - t_, y), (x + t_, y)], fill=(255, 255, 255), width=int(s * 0.02))
            d.line([(x, y - t_), (x, y + t_)], fill=(255, 255, 255), width=int(s * 0.02))
    elif tipo == "granizo":    # nube oscura que tiembla y suelta bolas de granizo que caen y rebotan
        tiembla = s * 0.012 * math.sin(2 * math.pi * f * 6)
        for i, cx in enumerate((0.28, 0.44, 0.60, 0.76, 0.36, 0.68)):
            k = (f * 1.5 + i * 0.19) % 1.0
            if k < 0.75:                       # cae
                y = s * (0.52 + 0.42 * (k / 0.75) ** 1.6)
            else:                              # rebota en el suelo
                b = (k - 0.75) / 0.25
                y = s * (0.94 - 0.10 * math.sin(math.pi * b))
            r = s * (0.07 if i < 4 else 0.055)
            x = s * cx + (s * 0.03 * (k - 0.75) * 4 if k >= 0.75 else 0)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(240, 248, 255), outline=(120, 170, 225), width=int(s * 0.018))
            d.ellipse([x - r * 0.45, y - r * 0.55, x - r * 0.05, y - r * 0.15], fill=(255, 255, 255))
        _nube(d, s * 0.48 + tiembla, s * 0.28, s * 0.74, NUBE_OSCURA)
    elif tipo == "niebla":
        _nube(d, s * 0.50, s * 0.22, s * 0.66, (220, 226, 236))
        for i, w in enumerate((0.70, 0.56, 0.66)):
            y = s * (0.62 + i * 0.11)
            dx = s * 0.06 * math.sin(2 * math.pi * (f + i * 0.3))
            d.rounded_rectangle([s * (0.5 - w / 2) + dx, y, s * (0.5 + w / 2) + dx, y + s * 0.05], radius=s * 0.025,
                                fill=(230, 235, 242))
    elif tipo == "viento":
        for i, (y, w) in enumerate(((0.36, 0.62), (0.52, 0.74), (0.68, 0.52))):
            k = (f + i * 0.3) % 1.0
            x0 = s * (0.12 + 0.10 * k)
            d.line([(x0, s * y), (x0 + s * w, s * y)], fill=BLANCO + (int(255 * (1 - k * 0.4)),), width=int(s * 0.075))
            d.arc([x0 + s * w - s * 0.12, s * y - s * 0.12, x0 + s * w + s * 0.08, s * y + s * 0.04], 270, 120,
                  fill=BLANCO + (int(255 * (1 - k * 0.4)),), width=int(s * 0.075))
    sombra = im.split()[3].filter(ImageFilter.GaussianBlur(s * 0.03))
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    base.paste((0, 0, 0, 90), (int(s * 0.01), int(s * 0.025)), sombra)
    base.alpha_composite(im)
    return base.resize((tam, tam), Image.LANCZOS)


def color_temp(t: int):
    if t is None:
        return BLANCO
    escala = [(0, (150, 210, 255)), (10, (190, 235, 255)), (17, (255, 255, 255)), (22, (255, 226, 120)),
              (28, (255, 160, 60)), (34, (255, 90, 70))]
    if t <= escala[0][0]:
        return escala[0][1]
    for (t0, c0), (t1, c1) in zip(escala, escala[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(int(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
    return escala[-1][1]


# ---------------------------------------------------------------- Marcadores
def _texto(d, xy, txt, f, color, sombra=True, anchor="la"):
    if sombra:
        d.text((xy[0] + 2, xy[1] + 3), txt, font=f, fill=(0, 0, 0, 130), anchor=anchor)
    d.text(xy, txt, font=f, fill=color, anchor=anchor)


@lru_cache(maxsize=None)
def _marcador_mini(nombre, tmax, ic, fase=0) -> Image.Image:
    # algo más compacta que antes: caben más ciudades y el mapa no se queda con huecos
    f = fuente("Black", 35)
    txt = f"{tmax}°"
    tw = int(f.getlength(txt))
    w, h = 54 + tw + 18, 58
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 5, w - 1, h - 5], radius=24, fill=(8, 20, 45, 190))
    im.alpha_composite(icono(ic, 52, fase), (3, 3))
    _texto(d, (54, h / 2), txt, f, color_temp(tmax), anchor="lm")
    return im


@lru_cache(maxsize=None)
def _marcador_tarjeta(nombre, tmax, tmin, lluvia, ic, fase=0, racha=None) -> Image.Image:
    fn, fx, fm = fuente("Bold", 30), fuente("Black", 62), fuente("Bold", 32)
    w, h = 300, 150
    w = max(w, int(fn.getlength(nombre)) + 40)
    if racha is not None and racha >= 50:
        w = max(w, 112 + int(fuente("SemiBold", 24).getlength(f"Rachas {int(racha)} km/h")) + 16)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=28, fill=(8, 20, 45, 215), outline=(255, 255, 255, 60), width=2)
    _texto(d, (w / 2, 12), nombre, fn, BLANCO, anchor="ma")
    im.alpha_composite(icono(ic, 96, fase), (8, 46))
    _texto(d, (112, 104), f"{tmax}°", fx, color_temp(tmax), anchor="ls")
    x = 112 + fx.getlength(f"{tmax}°") + 10
    _texto(d, (x, 104), f"{tmin}°", fm, AZUL_MIN, anchor="ls")
    if racha is not None and racha >= 50:   # rachas fuertes: tienen prioridad en la tarjeta
        _texto(d, (112, 140), f"Rachas {int(racha)} km/h", fuente("SemiBold", 24), (255, 200, 120), anchor="ls")
    elif lluvia is not None and lluvia >= 20:
        _texto(d, (112, 140), f"Lluvia {lluvia}%", fuente("SemiBold", 24),
               (150, 205, 255), anchor="ls")
    return im


def colocar(cajas, area, iter_=300):
    """Separa cajas solapadas (repulsión simple). cajas: lista de [x, y, w, h] (x,y = esquina sup. izq.)."""
    ax0, ay0, ax1, ay1 = area
    for _ in range(iter_):
        movido = False
        for i in range(len(cajas)):
            for j in range(i + 1, len(cajas)):
                a, b = cajas[i], cajas[j]
                ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) + 8
                oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) + 8
                if ox > 0 and oy > 0:
                    movido = True
                    if oy < ox:
                        sgn = -1 if a[1] + a[3] / 2 < b[1] + b[3] / 2 else 1
                        a[1] += sgn * oy / 2
                        b[1] -= sgn * oy / 2
                    else:
                        sgn = -1 if a[0] + a[2] / 2 < b[0] + b[2] / 2 else 1
                        a[0] += sgn * ox / 2
                        b[0] -= sgn * ox / 2
        for c in cajas:
            c[0] = min(max(c[0], ax0), ax1 - c[2])
            c[1] = min(max(c[1], ay0), ay1 - c[3])
        if not movido:
            break
    return cajas


def marcador(c: dict, estilo: str, fase: int = 0) -> Image.Image:
    if estilo == "mini":
        return _marcador_mini(c["nombre"], c["tmax"], c["icono"], fase)
    racha = c.get("racha")
    return _marcador_tarjeta(c["nombre"], c["tmax"], c["tmin"], c["lluvia"], c["icono"], fase,
                             round(racha) if racha else None)


def marcadores(prev, pr: Proyeccion, estilo: str, area):
    """Devuelve [(imagen, (x, y), (px, py), ciudad)] ya colocados sin solaparse."""
    items = []
    for c in prev:
        px, py = pr.ciudad(c)
        im = marcador(c, estilo)
        if estilo == "mini":
            caja = [px - im.width / 2, py - im.height / 2, im.width, im.height]
        else:
            caja = [px - im.width / 2, py - im.height - 26, im.width, im.height]
        items.append((im, caja, (px, py), c))
    if estilo == "mini":
        # Las pastillas pequeñas no llevan nombre: si se apartan de su ciudad parecen de otra (Sevilla «encima de
        # Huelva»). Cada una va sobre su ciudad o, como mucho, un poco desplazada; si no cabe, no se pone.
        ax0, ay0, ax1, ay1 = area
        puestas, out = [], []
        try:   # si no caben todas, primero las ciudades más grandes y las más extremas del día
            from .poblaciones import GRANDES
            rango = {n: i for i, (n, *_) in enumerate(GRANDES)}
            refs = [pr.ciudad({"lat": la, "lon": lo}) + (n,) for n, la, lo in GRANDES]
        except Exception:  # noqa: BLE001
            rango, refs = {}, []
        refs += [(p_[0], p_[1], c["nombre"]) for _, _, p_, c in items]
        extremos = {max(items, key=lambda it: it[3]["tmax"])[3]["nombre"] if items else None,
                    min(items, key=lambda it: it[3].get("tmin", 99))[3]["nombre"] if items else None}
        items.sort(key=lambda it: (it[3]["nombre"] not in extremos, rango.get(it[3]["nombre"], 999)))
        offs = sorted({(dx, dy) for dx in range(-80, 81, 10) for dy in range(-60, 61, 10)},
                      key=lambda o: o[0] ** 2 + (o[1] * 1.3) ** 2)
        # orden: extremos y ciudades grandes primero; después, las que rellenan los huecos más grandes
        primeras = [it for it in items if it[3]["nombre"] in extremos or rango.get(it[3]["nombre"], 999) < 25]
        resto = [it for it in items if it not in primeras]

        def siguiente():
            if primeras:
                return primeras.pop(0)
            if not resto:
                return None
            if not out:
                return resto.pop(0)
            lejos = max(resto, key=lambda it: min(math.hypot(it[2][0] - o[2][0], it[2][1] - o[2][1]) for o in out))
            resto.remove(lejos)
            return lejos

        while True:
            it_ = siguiente()
            if it_ is None:
                break
            im, caja, (px, py), c = it_
            w, h = caja[2], caja[3]
            for dx, dy in offs:
                x0, y0 = px - w / 2 + dx, py - h / 2 + dy
                # la columna de botones de TikTok empieza más abajo: arriba se puede llegar casi al borde
                lim_x = 1080 - 15 if y0 + h < 600 else ax1
                if not (ax0 <= x0 and x0 + w <= lim_x and ay0 <= y0 and y0 + h <= ay1):
                    continue
                if any(x0 < b[0] + b[2] + 4 and x0 + w + 4 > b[0] and y0 < b[1] + b[3] + 2 and y0 + h + 2 > b[1]
                       for b in puestas):
                    continue
                cx, cy = x0 + w / 2, y0 + h / 2
                propia = math.hypot(cx - px, cy - py)
                # que la pastilla quede más cerca de su ciudad que de cualquier otra ciudad conocida
                if any(n != c["nombre"] and math.hypot(rx - px, ry - py) > 40 and math.hypot(cx - rx, cy - ry) < propia
                       for rx, ry, n in refs):   # (las ciudades pegadas a la suya, como L'Hospitalet, no cuentan)
                    continue
                puestas.append((x0, y0, w, h))
                out.append((im, (int(x0), int(y0)), (px, py), c))
                break
        return out
    cajas = colocar([it[1] for it in items], area)
    return [(im, (int(cj[0]), int(cj[1])), p, c) for (im, _, p, c), cj in zip(items, cajas)]
