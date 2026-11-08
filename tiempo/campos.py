"""Mapas de campo para dar más información de vez en cuando: lluvia acumulada en escala de colores y mapa de isobaras.

Los datos son una rejilla de Open-Meteo (consenso del modelo «best_match»). El campo se dibuja una vez en coordenadas
del mapa (lon/lat, con Canarias desplazada a su recuadro) y en cada fotograma se coloca con la proyección del momento,
así funciona igual con el zoom.
"""
from __future__ import annotations

import logging
import math
from datetime import date

import numpy as np
import requests
from PIL import Image, ImageDraw

from .mapa import lonlat_mapa

log = logging.getLogger(__name__)
URL = "https://api.open-meteo.com/v1/forecast"

# Rejillas (lon0, lon1, lat0, lat1, paso)
PENINSULA = (-11.2, 5.2, 34.8, 44.8, 0.4)
CANARIAS = (-18.6, -13.0, 27.3, 29.7, 0.25)
ISOBARAS = (-30.0, 12.0, 28.0, 55.0, 1.0)   # más amplia: las borrascas vienen de lejos

# Escala de lluvia (l/m² en el día) — de celeste a morado
ESCALA = [(1, (154, 215, 245)), (3, (79, 179, 232)), (7, (43, 123, 217)), (15, (47, 191, 113)),
          (30, (242, 208, 53)), (50, (242, 138, 46)), (80, (224, 54, 44)), (120, (176, 43, 209))]


def _rejilla(caja):
    lon0, lon1, lat0, lat1, paso = caja
    lons = np.arange(lon0, lon1 + 1e-6, paso)
    lats = np.arange(lat0, lat1 + 1e-6, paso)
    return lons, lats


def _pedir(puntos, params) -> list[dict]:
    """Open-Meteo admite varias ubicaciones por petición: se piden en tandas."""
    import time
    out = []
    for i in range(0, len(puntos), 100):
        if i:
            time.sleep(11)   # Open-Meteo cuenta cada punto como una consulta (máx. 600 por minuto)
        tanda = puntos[i:i + 100]
        q = {**params, "latitude": ",".join(f"{la:.2f}" for la, _ in tanda),
             "longitude": ",".join(f"{lo:.2f}" for _, lo in tanda), "timezone": "Europe/Madrid"}
        for intento in range(3):
            try:
                r = requests.get(URL, params=q, timeout=120)
            except requests.RequestException:
                time.sleep(15)
                continue
            if r.status_code == 429:
                time.sleep(30 * (intento + 1))
                continue
            r.raise_for_status()
            j = r.json()
            out += j if isinstance(j, list) else [j]
            break
        else:
            raise RuntimeError("Open-Meteo: demasiadas peticiones")
    return out


CANARIAS_FINA = (-18.4, -13.2, 27.5, 29.5, 0.1)   # las islas son pequeñas: rejilla fina para el aviso


def lluvia(dia: date, caja=PENINSULA, hasta: date | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lluvia acumulada (l/m²) del día, o de varios días seguidos si se da «hasta»."""
    lons, lats = _rejilla(caja)
    puntos = [(la, lo) for la in lats for lo in lons]
    fin = hasta or dia
    js = _pedir(puntos, {"daily": "precipitation_sum", "start_date": dia.isoformat(), "end_date": fin.isoformat()})
    v = np.array([sum(x or 0 for x in (j.get("daily") or {}).get("precipitation_sum", [0])) for j in js], dtype=float)
    return lons, lats, v.reshape(len(lats), len(lons))


def maximos(lons, lats, v, cajas: dict) -> dict:
    """Lluvia máxima prevista dentro de cada caja {nombre: (lon0, lon1, lat0, lat1)}."""
    out = {}
    for n, (a, b, c, d) in cajas.items():
        mi = (lons >= a - 0.05) & (lons <= b + 0.05)
        mj = (lats >= c - 0.05) & (lats <= d + 0.05)
        sub = v[np.ix_(mj, mi)]
        if sub.size:
            out[n] = int(round(float(sub.max())))
    return out


# Escala «de mapa de modelo» (como Meteologix/ECMWF): del azul al morado pasando por verde, amarillo y rojo
ESCALA_FUERTE = [(0.2, (198, 225, 245)), (1, (150, 200, 240)), (2, (100, 170, 235)), (3, (60, 135, 225)),
                 (5, (35, 100, 210)), (7, (25, 150, 140)), (10, (40, 170, 80)), (15, (100, 200, 50)),
                 (20, (170, 220, 40)), (25, (235, 230, 40)), (30, (250, 200, 30)), (40, (250, 160, 20)),
                 (50, (245, 115, 20)), (60, (235, 70, 25)), (70, (215, 30, 30)), (80, (185, 15, 50)),
                 (100, (200, 40, 140)), (125, (210, 80, 210)), (150, (175, 120, 235)), (200, (230, 190, 245))]


def _imagen_lluvia_fuerte(lons, lats, v, canaria=False) -> tuple[Image.Image, tuple]:
    """Campo continuo y opaco (también sobre el mar), interpolado entre colores de la escala."""
    from scipy.ndimage import zoom
    from PIL import ImageFilter
    f = PX_GRADO * (lons[1] - lons[0])
    fino = np.clip(zoom(v, f, order=3), 0, None)
    umbrales = np.array([u for u, _ in ESCALA_FUERTE])
    cols = np.array([c for _, c in ESCALA_FUERTE], dtype=float)
    idx = np.clip(np.searchsorted(umbrales, fino, side="right") - 1, 0, len(umbrales) - 1)
    sig = np.clip(idx + 1, 0, len(umbrales) - 1)
    t = np.clip((fino - umbrales[idx]) / np.maximum(umbrales[sig] - umbrales[idx], 1e-6), 0, 1)[..., None]
    rgb = cols[idx] * (1 - t) + cols[sig] * t
    alfa = np.where(fino >= umbrales[0], 225, 0).astype(float)
    h, w = fino.shape
    borde = max(8, int(0.6 * PX_GRADO * (lons[1] - lons[0])))
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.minimum.reduce([xx, w - 1 - xx, yy, h - 1 - yy]).astype(float)
    alfa *= np.clip(dist / borde, 0, 1)
    rgba = np.dstack([rgb, alfa]).astype(np.uint8)
    img = Image.fromarray(rgba[::-1], "RGBA").filter(ImageFilter.GaussianBlur(1.2))
    lon0, lat0 = lonlat_mapa(float(lons[0]), float(lats[0]), canaria)
    lon1, lat1 = lonlat_mapa(float(lons[-1]), float(lats[-1]), canaria)
    return img, (lon0, lon1, lat0, lat1)


def _leyenda_horizontal(capa, y, titulo, f, fpeq):
    """Barra de colores horizontal con sus cifras, como en los mapas de los modelos."""
    from .config import ANCHO
    d = ImageDraw.Draw(capa)
    x0, x1 = 40, ANCHO - 40
    n = len(ESCALA_FUERTE)
    paso = (x1 - x0) / n
    d.rounded_rectangle([x0 - 16, y - 46, x1 + 16, y + 64], radius=18, fill=(8, 20, 45, 215))
    d.text((x0, y - 24), titulo, font=f, fill=(255, 255, 255, 255), anchor="lm")
    for k, (u, col) in enumerate(ESCALA_FUERTE):
        d.rectangle([x0 + k * paso, y, x0 + (k + 1) * paso, y + 24], fill=col + (255,))
        if k % 2 == 1 or k == 0:
            d.text((x0 + k * paso, y + 42), f"{u:g}".replace(".", ","), font=fpeq, fill=(230, 236, 245, 255),
                   anchor="mm")


def capa_lluvia_fuerte(campos_: list, titulo: str):
    """Capa con el campo de lluvia «de modelo» (opaco, escala completa) y la leyenda horizontal abajo.
    campos_: lista de (lons, lats, v, canaria)."""
    from .video import MAPA_Y0, MAPA_H
    from .especiales import fuente
    imgs = [_imagen_lluvia_fuerte(lo, la, v, can) for lo, la, v, can in campos_]
    cache: dict = {}
    f, fpeq = fuente("ExtraBold", 26), fuente("Bold", 20)

    def dibujar(capa, pr, dt):
        for n, (img, caja) in enumerate(imgs):
            _pegar(capa, img, caja, pr, MAPA_Y0, cache, f"f{n}")
        _leyenda_horizontal(capa, MAPA_Y0 + MAPA_H - 86, titulo, f, fpeq)
    return dibujar


def presion(dia: date, hora: int = 12, caja=ISOBARAS) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lons, lats = _rejilla(caja)
    puntos = [(la, lo) for la in lats for lo in lons]
    js = _pedir(puntos, {"hourly": "pressure_msl", "start_date": dia.isoformat(), "end_date": dia.isoformat()})
    v = np.array([((j.get("hourly") or {}).get("pressure_msl") or [1013] * 24)[hora] or 1013 for j in js], dtype=float)
    return lons, lats, v.reshape(len(lats), len(lons))


# ------------------------------------------------------------------ dibujo en coordenadas del mapa
PX_GRADO = 90   # resolución de la imagen del campo (píxeles por grado)


def _imagen_lluvia(lons, lats, v, canaria=False) -> tuple[Image.Image, tuple]:
    """Imagen RGBA del campo de lluvia y su caja (lon0, lon1, lat0, lat1) en coordenadas del mapa."""
    from scipy.ndimage import zoom
    f = PX_GRADO * (lons[1] - lons[0])
    fino = np.clip(zoom(v, f, order=1), 0, None)
    h, w = fino.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for umbral, col in ESCALA:
        m = fino >= umbral
        rgba[m, :3] = col
        rgba[m, 3] = 175
    # sin cortes rectos en los bordes de la rejilla: el campo se desvanece hacia fuera
    borde = max(8, int(0.9 * PX_GRADO * (lons[1] - lons[0])))
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.minimum.reduce([xx, w - 1 - xx, yy, h - 1 - yy]).astype(float)
    rgba[..., 3] = (rgba[..., 3] * np.clip(dist / borde, 0, 1)).astype(np.uint8)
    # bordes suaves entre colores
    img = Image.fromarray(rgba[::-1], "RGBA")   # filas de norte a sur
    from PIL import ImageFilter
    img = img.filter(ImageFilter.GaussianBlur(2))
    lon0, lat0 = lonlat_mapa(float(lons[0]), float(lats[0]), canaria)
    lon1, lat1 = lonlat_mapa(float(lons[-1]), float(lats[-1]), canaria)
    return img, (lon0, lon1, lat0, lat1)


def _imagen_isobaras(lons, lats, v) -> tuple[Image.Image, tuple]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.ndimage import gaussian_filter
    v = gaussian_filter(v, 1.0)
    w = int((lons[-1] - lons[0]) * PX_GRADO * 0.6)
    h = int((lats[-1] - lats[0]) * PX_GRADO * 0.6)
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(lons[0], lons[-1])
    ax.set_ylim(lats[0], lats[-1])
    ax.axis("off")
    niveles = np.arange(math.floor(v.min() / 4) * 4, v.max() + 4, 4)
    # fondo suave: azul donde la presión es baja, rojo donde es alta (como en los mapas de la tele)
    ax.contourf(lons, lats, v, levels=np.arange(960, 1050, 2), cmap="RdBu_r", alpha=0.32, vmin=990, vmax=1035)
    cs = ax.contour(lons, lats, v, levels=niveles, colors="white", linewidths=4.5, alpha=0.95)
    ax.clabel(cs, fmt="%d", fontsize=24, colors="white", inline=True, inline_spacing=12)
    fig.patch.set_alpha(0)
    fig.canvas.draw()
    img = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba()).copy()
    plt.close(fig)
    return img, (float(lons[0]), float(lons[-1]), float(lats[0]), float(lats[-1]))


def centros(lons, lats, v) -> list[tuple[str, float, float, float]]:
    """Altas (A) y bajas (B) relevantes: extremos locales claros dentro de la rejilla."""
    from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter
    s = gaussian_filter(v, 1.5)
    out = []
    for tipo, filtro, cond in (("A", maximum_filter, lambda x: x >= 1020), ("B", minimum_filter, lambda x: x <= 1010)):
        m = (filtro(s, size=11) == s)
        for i, j in zip(*np.nonzero(m)):
            if 1 <= i < s.shape[0] - 1 and 1 <= j < s.shape[1] - 1 and cond(s[i, j]):
                out.append((tipo, float(lons[j]), float(lats[i]), float(s[i, j])))
    return out


def _pegar(capa: Image.Image, img: Image.Image, caja, pr, y0: int, cache: dict, clave):
    lon0, lon1, lat0, lat1 = caja
    x0, ya = pr(lon0, lat1)
    x1, yb = pr(lon1, lat0)
    w, h = int(round(x1 - x0)), int(round(yb - ya))
    if w < 2 or h < 2 or w > 9000 or h > 9000:
        return
    k = (clave, w, h)
    if k not in cache:
        if len(cache) > 6:
            cache.clear()
        cache[k] = img.resize((w, h), Image.BILINEAR)
    capa.alpha_composite(cache[k], (int(round(x0)), int(round(ya)) + y0)) if x0 >= 0 and ya + y0 >= 0 else \
        capa.paste(cache[k], (int(round(x0)), int(round(ya)) + y0), cache[k])


def capa_lluvia(dia: date, con_canarias: bool = True):
    """Capa (para capas_fondo) con la lluvia del día en escala de colores y su leyenda. None si no hay datos."""
    from .video import MAPA_Y0, MAPA_H
    from .config import ANCHO
    from .especiales import fuente
    imgs = []
    try:
        imgs.append(_imagen_lluvia(*lluvia(dia, PENINSULA)))
        if con_canarias:
            lo, la, v = lluvia(dia, CANARIAS)
            imgs.append(_imagen_lluvia(lo, la, v, canaria=True))
    except Exception as e:  # noqa: BLE001
        log.warning("Mapa de lluvia no disponible: %s", e)
        return None
    cache: dict = {}
    f = fuente("ExtraBold", 22)

    def dibujar(capa, pr, dt):
        for n, (img, caja) in enumerate(imgs):
            _pegar(capa, img, caja, pr, MAPA_Y0, cache, n)
        # leyenda: abajo a la derecha
        d = ImageDraw.Draw(capa)
        x, y = ANCHO - 150, MAPA_Y0 + MAPA_H - 30 - 34 * len(ESCALA)
        d.rounded_rectangle([x - 14, y - 52, ANCHO - 18, MAPA_Y0 + MAPA_H - 18], radius=16, fill=(8, 20, 45, 200))
        d.text((x - 2, y - 30), "l/m²", font=f, fill=(255, 255, 255, 255), anchor="lm")
        for k, (u, col) in enumerate(reversed(ESCALA)):
            yy = y + 34 * k
            d.rounded_rectangle([x, yy, x + 34, yy + 26], radius=6, fill=col + (255,))
            d.text((x + 46, yy + 13), f"{u}+", font=f, fill=(255, 255, 255, 255), anchor="lm")
    return dibujar


def capa_isobaras(dia: date):
    """Capa con las isobaras del mediodía y las altas (A) y bajas (B). None si no hay datos."""
    from .video import MAPA_Y0
    from .especiales import fuente
    try:
        lons, lats, v = presion(dia)
    except Exception as e:  # noqa: BLE001
        log.warning("Mapa de isobaras no disponible: %s", e)
        return None
    img, caja = _imagen_isobaras(lons, lats, v)
    cs = centros(lons, lats, v)
    cache: dict = {}
    f = fuente("Black", 64)
    f2 = fuente("ExtraBold", 22)

    def dibujar(capa, pr, dt):
        _pegar(capa, img, caja, pr, MAPA_Y0, cache, "iso")
        d = ImageDraw.Draw(capa)
        for tipo, lo, la, p in cs:
            x, y = pr(lo, la)
            y += MAPA_Y0
            if not (0 < x < capa.width and MAPA_Y0 < y < capa.height):
                continue
            col = (60, 140, 255) if tipo == "A" else (235, 60, 60)
            d.ellipse([x - 42, y - 42, x + 42, y + 42], fill=(255, 255, 255, 230), outline=col + (255,), width=6)
            d.text((x, y - 2), tipo, font=f, fill=col + (255,), anchor="mm")
            d.text((x, y + 60), f"{p:.0f} hPa", font=f2, fill=(255, 255, 255, 255), anchor="mm",
                   stroke_width=3, stroke_fill=(8, 20, 45, 255))
    return dibujar, cs, float(v.min()), float(v.max())
