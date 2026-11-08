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
PENINSULA = (-9.8, 4.6, 35.6, 44.0, 0.25)
CANARIAS = (-18.3, -13.3, 27.5, 29.5, 0.2)
ISOBARAS = (-24.0, 12.0, 29.0, 50.0, 0.75)   # más amplia: las borrascas vienen de lejos

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
    out = []
    for i in range(0, len(puntos), 200):
        tanda = puntos[i:i + 200]
        q = {**params, "latitude": ",".join(f"{la:.2f}" for la, _ in tanda),
             "longitude": ",".join(f"{lo:.2f}" for _, lo in tanda), "timezone": "Europe/Madrid"}
        for intento in range(3):
            r = requests.get(URL, params=q, timeout=60)
            if r.status_code == 429:
                import time
                time.sleep(20 * (intento + 1))
                continue
            r.raise_for_status()
            j = r.json()
            out += j if isinstance(j, list) else [j]
            break
        else:
            raise RuntimeError("Open-Meteo: demasiadas peticiones")
    return out


def lluvia(dia: date, caja=PENINSULA) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lons, lats = _rejilla(caja)
    puntos = [(la, lo) for la in lats for lo in lons]
    js = _pedir(puntos, {"daily": "precipitation_sum", "start_date": dia.isoformat(), "end_date": dia.isoformat()})
    v = np.array([(j.get("daily") or {}).get("precipitation_sum", [0])[0] or 0 for j in js], dtype=float)
    return lons, lats, v.reshape(len(lats), len(lons))


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
    cs = ax.contour(lons, lats, v, levels=niveles, colors="white", linewidths=2.2, alpha=0.9)
    ax.clabel(cs, fmt="%d", fontsize=13, colors="white", inline=True)
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
    for tipo, filtro, cond in (("A", maximum_filter, lambda x: x >= 1022), ("B", minimum_filter, lambda x: x <= 1008)):
        m = (filtro(s, size=9) == s)
        for i, j in zip(*np.nonzero(m)):
            if 2 <= i < s.shape[0] - 2 and 2 <= j < s.shape[1] - 2 and cond(s[i, j]):
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
