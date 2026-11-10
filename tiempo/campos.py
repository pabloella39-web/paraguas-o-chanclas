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
PENINSULA_PANTALLA = (-13.8, 5.6, 31.8, 46.3, 0.6)   # todo lo que se ve en el mapa general (sin recuadro)


def sin_recuadro_canarias(lons, lats, v):
    """Lluvia de la península a cero dentro del recuadro de Canarias (ahí van las islas, con su propia rejilla)."""
    from .config import RECUADRO_CANARIAS
    v = v.copy()
    mlon = (lons >= RECUADRO_CANARIAS[0] - 0.3) & (lons <= RECUADRO_CANARIAS[1] + 0.3)
    mlat = (lats >= RECUADRO_CANARIAS[2] - 0.3) & (lats <= RECUADRO_CANARIAS[3] + 0.3)
    v[np.ix_(mlat, mlon)] = 0
    return v
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
    js = _pedir(puntos, {"daily": "precipitation_sum", "models": ",".join(MODELOS), "start_date": dia.isoformat(),
                         "end_date": fin.isoformat()})
    ndias = (fin - dia).days + 1
    v = np.array([sum(_media_modelos(j.get("daily") or {}, "precipitation_sum", ndias)) for j in js], dtype=float)
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
# Tonos oscuros y saturados: cuanto más llueve, más oscuro (rojo sangre, granate y casi negro en lo extremo), para
# que lo peligroso se vea peligroso.
ESCALA_FUERTE = [(0.1, (150, 190, 225)), (1, (105, 160, 215)), (2, (65, 130, 205)), (3, (35, 100, 190)),
                 (5, (20, 70, 165)), (7, (15, 115, 110)), (10, (25, 135, 60)), (15, (75, 160, 35)),
                 (20, (140, 180, 25)), (25, (205, 195, 25)), (30, (225, 165, 15)), (40, (225, 125, 10)),
                 (50, (215, 85, 10)), (60, (200, 45, 15)), (70, (175, 15, 20)), (80, (140, 5, 30)),
                 (100, (110, 0, 60)), (125, (85, 0, 85)), (150, (55, 0, 70)), (200, (25, 0, 30))]


def _imagen_lluvia_fuerte(lons, lats, v, canaria=False, escala=None, px=None) -> tuple[Image.Image, tuple]:
    """Campo continuo y opaco (también sobre el mar), interpolado entre colores de la escala."""
    from scipy.ndimage import zoom
    from PIL import ImageFilter
    escala = escala or ESCALA_FUERTE
    f = (px or PX_GRADO) * (lons[1] - lons[0])
    fino = np.clip(zoom(v, f, order=3), 0, None)
    umbrales = np.array([u for u, _ in escala])
    cols = np.array([c for _, c in escala], dtype=float)
    idx = np.clip(np.searchsorted(umbrales, fino, side="right") - 1, 0, len(umbrales) - 1)
    sig = np.clip(idx + 1, 0, len(umbrales) - 1)
    t = np.clip((fino - umbrales[idx]) / np.maximum(umbrales[sig] - umbrales[idx], 1e-6), 0, 1)[..., None]
    rgb = cols[idx] * (1 - t) + cols[sig] * t
    alfa = np.where(fino >= umbrales[0], 225, 0).astype(float)
    h, w = fino.shape
    borde = max(8, int(0.6 * (px or PX_GRADO) * (lons[1] - lons[0])))
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.minimum.reduce([xx, w - 1 - xx, yy, h - 1 - yy]).astype(float)
    alfa *= np.clip(dist / borde, 0, 1)
    rgba = np.dstack([rgb, alfa]).astype(np.uint8)
    img = Image.fromarray(rgba[::-1], "RGBA").filter(ImageFilter.GaussianBlur(1.2))
    lon0, lat0 = lonlat_mapa(float(lons[0]), float(lats[0]), canaria)
    lon1, lat1 = lonlat_mapa(float(lons[-1]), float(lats[-1]), canaria)
    return img, (lon0, lon1, lat0, lat1)


def _leyenda_horizontal(capa, y, titulo, f, fpeq, escala=None):
    """Barra de colores horizontal con sus cifras, como en los mapas de los modelos."""
    from .config import ANCHO
    escala = escala or ESCALA_FUERTE
    d = ImageDraw.Draw(capa)
    x0, x1 = 40, ANCHO - 40
    n = len(escala)
    paso = (x1 - x0) / n
    d.rounded_rectangle([x0 - 16, y - 46, x1 + 16, y + 64], radius=18, fill=(8, 20, 45, 215))
    d.text((x0, y - 24), titulo, font=f, fill=(255, 255, 255, 255), anchor="lm")
    for k, (u, col) in enumerate(escala):
        d.rectangle([x0 + k * paso, y, x0 + (k + 1) * paso, y + 24], fill=col + (255,))
        if k % 2 == 1 or k == 0:
            d.text((x0 + k * paso, y + 42), f"{u:g}".replace(".", ","), font=fpeq, fill=(230, 236, 245, 255),
                   anchor="mm")


def _recortado(dibujo):
    """Dibuja el campo y las costas en un lienzo del tamaño del mapa: así no se sale por encima del título ni por
    debajo, y se funde arriba igual que el mapa (sin el corte de un recuadro)."""
    from .config import ANCHO
    from .video import MAPA_H, MAPA_Y0
    rampa = np.linspace(0, 1, 110)

    def pegar(capa, pr, dt):
        lienzo = Image.new("RGBA", (ANCHO, MAPA_H), (0, 0, 0, 0))
        dibujo(lienzo, pr, dt)
        a = np.asarray(lienzo.getchannel("A"), dtype=float)
        a[:110] *= rampa[:, None]
        lienzo.putalpha(Image.fromarray(a.astype(np.uint8)))
        capa.alpha_composite(lienzo, (0, MAPA_Y0))
    return pegar


def capa_lluvia_fuerte(campos_: list, titulo: str):
    """Capa con el campo de lluvia «de modelo» (opaco, escala completa) y la leyenda horizontal abajo.
    campos_: lista de (lons, lats, v, canaria)."""
    from .video import MAPA_Y0, MAPA_H
    from .especiales import fuente
    imgs = [_imagen_lluvia_fuerte(lo, la, v, can) for lo, la, v, can in campos_]
    cache: dict = {}
    f, fpeq = fuente("ExtraBold", 26), fuente("Bold", 20)

    from . import mapa as mapa_
    provs = mapa_.provincias()

    def campo(lienzo, pr, dt):
        for n, (img, caja) in enumerate(imgs):
            _pegar(lienzo, img, caja, pr, 0, cache, f"f{n}")
        # costas y límites encima del color, para que se vea dónde cae cada cosa (como en los mapas de modelo)
        d = ImageDraw.Draw(lienzo)
        for p in provs:
            for anillo in p["anillos"]:
                pts = [pr(*lonlat_mapa(lo, la, la < 30)) for lo, la in anillo]
                d.line(pts + [pts[0]], fill=(255, 255, 255, 210), width=3)
    recortado = _recortado(campo)

    def dibujar(capa, pr, dt):
        recortado(capa, pr, dt)
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
        lo_, la_, v_ = lluvia(dia, PENINSULA_PANTALLA)
        imgs.append(_imagen_lluvia(lo_, la_, sin_recuadro_canarias(lo_, la_, v_)))
        if con_canarias:
            lo, la, v = lluvia(dia, CANARIAS)
            imgs.append(_imagen_lluvia(lo, la, v, canaria=True))
    except Exception as e:  # noqa: BLE001
        log.warning("Mapa de lluvia no disponible: %s", e)
        return None
    cache: dict = {}
    f = fuente("ExtraBold", 22)

    def campo(lienzo, pr, dt):
        for n, (img, caja) in enumerate(imgs):
            _pegar(lienzo, img, caja, pr, 0, cache, n)
    recortado = _recortado(campo)

    def dibujar(capa, pr, dt):
        recortado(capa, pr, dt)   # a pantalla completa, sin recuadro y sin salirse del mapa
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



# ------------------------------------------------------------------ evolución por horas
# Intensidad (l/m² en una hora): los mismos colores, umbrales de intensidad
ESCALA_HORA = [(0.1, ESCALA_FUERTE[0][1]), (0.3, ESCALA_FUERTE[1][1]), (0.6, ESCALA_FUERTE[2][1]),
               (1, ESCALA_FUERTE[3][1]), (1.5, ESCALA_FUERTE[4][1]), (2, ESCALA_FUERTE[5][1]),
               (3, ESCALA_FUERTE[6][1]), (4, ESCALA_FUERTE[7][1]), (5, ESCALA_FUERTE[8][1]),
               (6, ESCALA_FUERTE[9][1]), (8, ESCALA_FUERTE[10][1]), (10, ESCALA_FUERTE[11][1]),
               (12, ESCALA_FUERTE[12][1]), (15, ESCALA_FUERTE[13][1]), (20, ESCALA_FUERTE[14][1]),
               (25, ESCALA_FUERTE[15][1]), (30, ESCALA_FUERTE[16][1]), (40, ESCALA_FUERTE[17][1]),
               (50, ESCALA_FUERTE[18][1]), (60, ESCALA_FUERTE[19][1])]


# Consenso de modelos para la lluvia: media del europeo, el francés, el alemán y el americano (lo mismo que se usa para
# las cifras de las ciudades). Un solo modelo puede inventarse o perderse un núcleo de tormenta; la media es más fiable.
MODELOS = ["ecmwf_ifs025", "meteofrance_seamless", "icon_seamless", "gfs_seamless"]


def _media_modelos(bloque: dict, var: str, n: int) -> list[float]:
    series = [bloque.get(f"{var}_{m}") for m in MODELOS]
    series = [x for x in series if isinstance(x, list) and any(v is not None for v in x)]
    if not series:
        return [0.0] * n
    out = []
    for k in range(n):
        vals = [x[k] for x in series if k < len(x) and x[k] is not None]
        out.append(sum(vals) / len(vals) if vals else 0.0)
    return out


def lluvia_horaria(ini: date, caja, fin: date | None = None, modelos: bool = True):
    """Lluvia hora a hora (l/m² en cada hora) en la rejilla, media de los modelos: (lons, lats, horas, cubo)."""
    lons, lats = _rejilla(caja)
    puntos = [(la, lo) for la in lats for lo in lons]
    js = _pedir(puntos, {"hourly": "precipitation", **({"models": ",".join(MODELOS)} if modelos else {}),
                         "start_date": ini.isoformat(), "end_date": (fin or ini).isoformat()})
    horas = (js[0].get("hourly") or {}).get("time") or []
    cubo = np.array([_media_modelos(j.get("hourly") or {}, "precipitation", len(horas)) if modelos else
                     [x or 0 for x in ((j.get("hourly") or {}).get("precipitation") or [0] * len(horas))] for j in js],
                    dtype=float)   # [punto, hora]
    return lons, lats, horas, cubo.T.reshape(len(horas), len(lats), len(lons))


def picos(lons, lats, horas, cubo, cajas: dict) -> dict:
    """Para cada sitio: hora de máxima intensidad y cuánto (l/m² en una hora)."""
    out = {}
    for n, (a, b, c, d) in cajas.items():
        mi = (lons >= a - 0.05) & (lons <= b + 0.05)
        mj = (lats >= c - 0.05) & (lats <= d + 0.05)
        sub = cubo[:, mj][:, :, mi]
        if not sub.size:
            continue
        serie = sub.reshape(sub.shape[0], -1).max(axis=1)
        k = int(serie.argmax())
        if serie[k] >= 0.5:
            out[n] = {"hora": horas[k], "l_m2_en_una_hora": round(float(serie[k]), 1)}
    return out


DIAS_CORTOS = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]


def capa_evolucion(lons, lats, horas, cubo, canaria: bool, titulo: str = "LLUVIA HORA A HORA (L/M² EN 1 HORA)",
                   max_fotogramas: int = 18, seg_por_fotograma: float = 0.5):
    """Animación de la lluvia hora a hora (como un radar), con el reloj de cada fotograma y la leyenda."""
    from datetime import datetime as _dt
    from .especiales import fuente
    from .video import MAPA_H, MAPA_Y0, TRANSICION
    from .config import ANCHO
    # sin horas secas al principio ni al final
    activas = [k for k in range(len(horas)) if cubo[k].max() >= 0.2]
    if not activas:
        return None
    k0, k1 = activas[0], activas[-1]
    paso = max(1, -(-(k1 - k0 + 1) // max_fotogramas))
    idx = list(range(k0, k1 + 1, paso))
    fotos = []
    for k in idx:
        # cada fotograma es la lluvia del intervalo (si se salta horas, se suman)
        v = cubo[k:k + paso].sum(axis=0) / paso
        img, caja = _imagen_lluvia_fuerte(lons, lats, v, canaria, ESCALA_HORA, px=PX_GRADO * 0.6)
        t = _dt.fromisoformat(horas[k])
        fotos.append((img, caja, f"{DIAS_CORTOS[t.weekday()]} {t.hour:02d}:00"))
    cache: dict = {}
    from . import mapa as mapa_
    provs = mapa_.provincias()
    f, fpeq, freloj = fuente("ExtraBold", 26), fuente("Bold", 20), fuente("Black", 54)

    def dibujar(capa, pr, dt):
        n = int(max(0.0, dt - TRANSICION) / seg_por_fotograma)
        n = min(n, len(fotos) - 1)
        img, caja, reloj = fotos[n]

        def campo(lienzo, pr_, dt_):
            _pegar(lienzo, img, caja, pr_, 0, cache, f"h{n}")
            d_ = ImageDraw.Draw(lienzo)
            for p_ in provs:   # costas encima del color
                for anillo in p_["anillos"]:
                    pts = [pr_(*lonlat_mapa(lo, la, la < 30)) for lo, la in anillo]
                    d_.line(pts + [pts[0]], fill=(255, 255, 255, 210), width=3)
        _recortado(campo)(capa, pr, dt)
        if len(cache) > 4:
            for k in list(cache)[:-2]:
                cache.pop(k, None)
        d = ImageDraw.Draw(capa)
        w = freloj.getlength(reloj) + 48
        d.rounded_rectangle([ANCHO - 40 - w, MAPA_Y0 + 24, ANCHO - 40, MAPA_Y0 + 104], radius=22, fill=(8, 20, 45, 225))
        d.text((ANCHO - 40 - w / 2, MAPA_Y0 + 64), reloj, font=freloj, fill=(255, 255, 255, 255), anchor="mm")
        # barra de progreso del tiempo
        x0, x1 = ANCHO - 40 - w, ANCHO - 40
        d.rounded_rectangle([x0, MAPA_Y0 + 112, x1, MAPA_Y0 + 120], radius=4, fill=(255, 255, 255, 70))
        d.rounded_rectangle([x0, MAPA_Y0 + 112, x0 + (x1 - x0) * (n + 1) / len(fotos), MAPA_Y0 + 120], radius=4,
                            fill=(255, 201, 60, 255))
        _leyenda_horizontal(capa, MAPA_Y0 + MAPA_H - 86, titulo, f, fpeq, ESCALA_HORA)
    dibujar.duracion = len(fotos) * seg_por_fotograma
    dibujar.horas_fotos, dibujar.seg = [horas[k] for k in idx], seg_por_fotograma
    return dibujar


def color_fuerte(v: float):
    """Color de la escala de lluvia para una cifra (aclarado para leerse sobre fondo oscuro)."""
    c = ESCALA_FUERTE[0][1]
    for u, col in ESCALA_FUERTE:
        if v >= u:
            c = col
    k = 0.35 if sum(c) > 300 else 0.6   # los tonos más oscuros se aclaran más
    return tuple(int(x + (255 - x) * k) for x in c) + (255,)


def acumulado_por_zona(lons, lats, horas, cubo, cajas: dict, cortes: int = 4) -> dict:
    """Cómo va creciendo el acumulado (máximo de cada zona) según pasan las horas: {zona: {"MAR 15:00": 22, …}}."""
    from datetime import datetime as _dt
    activas = [k for k in range(len(horas)) if cubo[k].max() >= 0.2]
    if not activas or not cajas:
        return {}
    k0, k1 = activas[0], activas[-1]
    ks = sorted({k0 + round((k1 - k0) * (i + 1) / cortes) for i in range(cortes)})
    acum = np.cumsum(cubo, axis=0)
    out: dict = {}
    for k in ks:
        t = _dt.fromisoformat(horas[k])
        for z, v in maximos(lons, lats, acum[k], cajas).items():   # acumulado hasta el final de esa hora
            out.setdefault(z, {})[f"{DIAS_CORTOS[t.weekday()]} {(t.hour + 1) % 24:02d}:00"] = v
    return out


def capa_acumulado(lons, lats, horas, cubo, canaria: bool, cajas: dict,
                   titulo: str = "LLUVIA ACUMULADA (L/M²)", max_fotogramas: int = 16, seg_por_fotograma: float = 0.5):
    """La lluvia acumulada creciendo hora a hora: el mapa se va llenando de color y un marcador dice cuántos litros
    lleva ya cada zona. El último fotograma (el total) se queda fijo."""
    from datetime import datetime as _dt
    from .especiales import fuente
    from .video import MAPA_H, MAPA_Y0, TRANSICION
    from .config import ANCHO
    activas = [k for k in range(len(horas)) if cubo[k].max() >= 0.2]
    if not activas:
        return None
    k0, k1 = activas[0], activas[-1]
    paso = max(1, -(-(k1 - k0 + 1) // max_fotogramas))
    idx = list(range(k0 + paso - 1, k1 + 1, paso))
    if idx[-1] != k1:
        idx.append(k1)
    acum = np.cumsum(cubo, axis=0)
    total = maximos(lons, lats, acum[k1], cajas)
    zonas = [z for z, v in sorted(total.items(), key=lambda t: -t[1]) if v >= 1][:4]
    fotos = []
    for k in idx:
        img, caja = _imagen_lluvia_fuerte(lons, lats, acum[k], canaria)
        t = _dt.fromisoformat(horas[k])
        m = maximos(lons, lats, acum[k], cajas)
        fotos.append((img, caja, f"{DIAS_CORTOS[t.weekday()]} {(t.hour + 1) % 24:02d}:00", [(z, m.get(z, 0)) for z in zonas]))
    cache: dict = {}
    from . import mapa as mapa_
    provs = mapa_.provincias()
    f, fpeq, freloj = fuente("ExtraBold", 26), fuente("Bold", 20), fuente("Black", 54)
    fz, fn, ft = fuente("Bold", 28), fuente("Black", 34), fuente("ExtraBold", 21)
    # dónde cae el máximo de cada zona: al final se rotula sobre el mapa («90 l/m²»)
    puntos = []
    for z in zonas:
        a, b, c_, d_ = cajas[z]
        mi, mj = (lons >= a - 0.05) & (lons <= b + 0.05), (lats >= c_ - 0.05) & (lats <= d_ + 0.05)
        sub = acum[k1][np.ix_(mj, mi)]
        if sub.size:
            j, i = np.unravel_index(int(sub.argmax()), sub.shape)
            puntos.append((float(lons[mi][i]), float(lats[mj][j]), int(round(float(sub.max())))))
    fchip = fuente("Black", 32)

    ritmo = [seg_por_fotograma]

    def ajustar(dur_tramo: float):   # que quepa entero en el tramo y el total se quede al menos 1,5 s
        ritmo[0] = min(0.9, max(0.22, (dur_tramo - TRANSICION - 2.0) / len(fotos)))

    def dibujar(capa, pr, dt):
        n = min(int(max(0.0, dt - TRANSICION) / ritmo[0]), len(fotos) - 1)
        img, caja, reloj, filas = fotos[n]

        def campo(lienzo, pr_, dt_):
            _pegar(lienzo, img, caja, pr_, 0, cache, f"a{n}")
            d_ = ImageDraw.Draw(lienzo)
            for p_ in provs:
                for anillo in p_["anillos"]:
                    pts = [pr_(*lonlat_mapa(lo, la, la < 30)) for lo, la in anillo]
                    d_.line(pts + [pts[0]], fill=(255, 255, 255, 210), width=3)
        _recortado(campo)(capa, pr, dt)
        if len(cache) > 4:
            for k in list(cache)[:-2]:
                cache.pop(k, None)
        d = ImageDraw.Draw(capa)
        # reloj: hasta qué hora va el acumulado
        w = freloj.getlength(reloj) + 48
        x0, x1 = ANCHO - 40 - w, ANCHO - 40
        d.rounded_rectangle([x0, MAPA_Y0 + 24, x1, MAPA_Y0 + 104], radius=22, fill=(8, 20, 45, 225))
        d.text((ANCHO - 40 - w / 2, MAPA_Y0 + 64), reloj, font=freloj, fill=(255, 255, 255, 255), anchor="mm")
        d.rounded_rectangle([x0, MAPA_Y0 + 112, x1, MAPA_Y0 + 120], radius=4, fill=(255, 255, 255, 70))
        d.rounded_rectangle([x0, MAPA_Y0 + 112, x0 + (x1 - x0) * (n + 1) / len(fotos), MAPA_Y0 + 120], radius=4,
                            fill=(255, 201, 60, 255))
        # marcador por zonas: litros que lleva cada una hasta esa hora
        if filas:
            ancho = max(300.0, max(fz.getlength(z) for z, _ in filas) + 150)
            alto = 46 + 44 * len(filas) + 10
            px, py = 40, MAPA_Y0 + 24
            d.rounded_rectangle([px, py, px + ancho, py + alto], radius=20, fill=(8, 20, 45, 232))
            d.text((px + 18, py + 12), "ACUMULADO POR ZONAS (L/M²)" if ancho >= 360 else "ACUMULADO (L/M²)",
                   font=ft, fill=(255, 201, 60, 255))
            for i, (z, v) in enumerate(filas):
                y = py + 46 + 44 * i
                d.text((px + 18, y + 20), z, font=fz, fill=(255, 255, 255, 255), anchor="lm")
                d.text((px + ancho - 18, y + 20), str(v), font=fn, fill=color_fuerte(v), anchor="rm")
        _leyenda_horizontal(capa, MAPA_Y0 + MAPA_H - 86, titulo, f, fpeq)
    def encima(capa, pr, dt):
        """Total final: la cifra sobre el mapa, donde más cae en cada zona (se pinta lo último, sobre los nombres)."""
        if min(int(max(0.0, dt - TRANSICION) / ritmo[0]), len(fotos) - 1) == len(fotos) - 1:
            d = ImageDraw.Draw(capa)
            puestos = []
            for lo, la, v in puntos:
                x, y = pr(*lonlat_mapa(lo, la, la < 30))
                y += MAPA_Y0
                txt = f"{v} l/m²"
                w_ = fchip.getlength(txt) + 28
                if any(abs(x - px_) < 170 and abs(y - py_) < 54 for px_, py_ in puestos):
                    continue
                puestos.append((x, y))
                x = min(max(x, 30 + w_ / 2), ANCHO - 30 - w_ / 2)
                d.ellipse([x - 7, y - 7, x + 7, y + 7], fill=(255, 255, 255, 255), outline=(8, 20, 45, 255), width=3)
                d.rounded_rectangle([x - w_ / 2, y + 12, x + w_ / 2, y + 58], radius=16, fill=(255, 201, 60, 255),
                                    outline=(8, 20, 45, 255), width=3)
                d.text((x, y + 35), txt, font=fchip, fill=(8, 20, 45, 255), anchor="mm")
    dibujar.duracion = len(fotos) * seg_por_fotograma + 1.5
    dibujar.ajustar = ajustar
    dibujar.encima = encima
    if zonas:   # sitio del marcador, para que los nombres de los pueblos no se pongan encima
        dibujar.reservado = [(40, MAPA_Y0 + 24, 40 + max(300.0, max(fz.getlength(z) for z in zonas) + 150),
                              MAPA_Y0 + 24 + 56 + 44 * len(zonas))]
    return dibujar


# ------------------------------------------------------------------ temperaturas en colores (como en la tele)
ESCALA_TEMP = [(-99, (70, 120, 200)), (5, (90, 170, 220)), (10, (60, 190, 150)), (14, (60, 190, 90)),
               (18, (150, 215, 80)), (22, (235, 230, 90)), (25, (250, 200, 70)), (28, (248, 150, 55)),
               (31, (235, 85, 50)), (34, (200, 40, 45)), (37, (150, 20, 40)), (40, (95, 10, 30))]


def tmax_rejilla(dia: date, caja):
    """Máxima del día en la rejilla, media de los cuatro modelos."""
    lons, lats = _rejilla(caja)
    puntos = [(la, lo) for la in lats for lo in lons]
    js = _pedir(puntos, {"daily": "temperature_2m_max", "models": ",".join(MODELOS), "start_date": dia.isoformat(),
                         "end_date": dia.isoformat()})
    v = np.array([(_media_modelos(j.get("daily") or {}, "temperature_2m_max", 1) or [np.nan])[0] for j in js],
                 dtype=float)
    return lons, lats, v.reshape(len(lats), len(lons))


def _imagen_temp(lons, lats, v, canaria=False):
    from scipy.ndimage import zoom
    from PIL import ImageFilter
    f = PX_GRADO * (lons[1] - lons[0])
    fino = zoom(v, f, order=1)
    h, w = fino.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for u, col in ESCALA_TEMP:
        m = fino >= u
        rgba[m, :3] = col
        rgba[m, 3] = 235
    img = Image.fromarray(rgba[::-1], "RGBA").filter(ImageFilter.GaussianBlur(3))
    lon0, lat0 = lonlat_mapa(float(lons[0]), float(lats[0]), canaria)
    lon1, lat1 = lonlat_mapa(float(lons[-1]), float(lats[-1]), canaria)
    return img, (lon0, lon1, lat0, lat1)


def capa_temperaturas(dia: date, ciudades: list, titulo: str = "MÁXIMAS (°C)"):
    """España coloreada por la máxima (solo España: ni Portugal, ni Francia, ni África), límites de provincia y los
    números grandes en blanco sobre las ciudades (sin recuadros), con la leyenda de colores. Como en la tele."""
    from .video import MAPA_Y0, MAPA_H
    from .config import ANCHO
    from .especiales import fuente
    from . import mapa as mapa_
    try:
        imgs = [_imagen_temp(*tmax_rejilla(dia, PENINSULA_PANTALLA))]
        lo, la, v = tmax_rejilla(dia, CANARIAS)
        imgs.append(_imagen_temp(lo, la, v, canaria=True))
    except Exception as e:  # noqa: BLE001
        log.warning("Mapa de temperaturas no disponible: %s", e)
        return None
    provs = mapa_.provincias()
    cache: dict = {}
    fnum, fley = fuente("Black", 44), fuente("ExtraBold", 24)

    def preparar(pr):
        clave = (round(pr(0, 40)[0], 1), round(pr(0, 40)[1], 1), round(pr(1, 40)[0], 2))
        if clave in cache:
            return cache[clave]
        lienzo = Image.new("RGBA", (ANCHO, MAPA_H), (0, 0, 0, 0))
        c2: dict = {}
        for n, (img, caja) in enumerate(imgs):
            _pegar(lienzo, img, caja, pr, 0, c2, n)
        mask = Image.new("L", (ANCHO, MAPA_H), 0)
        dm = ImageDraw.Draw(mask)
        lineas = Image.new("RGBA", (ANCHO, MAPA_H), (0, 0, 0, 0))
        dl = ImageDraw.Draw(lineas)
        for p_ in provs:
            for an in p_["anillos"]:
                if not an:
                    continue
                q = [pr(*lonlat_mapa(lo_, la_, la_ < 30)) for lo_, la_ in an]
                dm.polygon(q, fill=255)
                dl.line(q + [q[0]], fill=(255, 255, 255, 120), width=2)
        a = np.asarray(lienzo.getchannel("A"), dtype=float) * np.asarray(mask, dtype=float) / 255
        lienzo.putalpha(Image.fromarray(a.astype(np.uint8)))
        lienzo.alpha_composite(lineas)
        # números sobre las ciudades, separados (primero las grandes y las nombradas: vienen ya en ese orden)
        d = ImageDraw.Draw(lienzo)
        puestos = []
        for c in ciudades:
            x, y = pr(*lonlat_mapa(c["lon"], c["lat"], c["lat"] < 30))
            if not (30 < x < 930 and 30 < y < MAPA_H - 30):
                continue
            if any(((x - a_) ** 2 + (y - b_) ** 2) ** 0.5 < 60 for a_, b_ in puestos):
                continue
            puestos.append((x, y))
            d.text((x, y), f"{round(c['tmax'])}", font=fnum, fill="white", anchor="mm", stroke_width=5,
                   stroke_fill=(20, 20, 30))
        # leyenda vertical abajo a la derecha (sobre el mar)
        esc = [e for e in ESCALA_TEMP if e[0] > -99]
        x0, y0 = ANCHO - 118, MAPA_H - 40 - 30 * len(esc)
        d.rounded_rectangle([x0 - 14, y0 - 48, x0 + 92, MAPA_H - 26], radius=16, fill=(8, 20, 45, 215))
        d.text((x0 + 38, y0 - 26), "°C", font=fley, fill="white", anchor="mm")
        for k, (u, col) in enumerate(reversed(esc)):
            y = y0 + 30 * k
            d.rectangle([x0, y, x0 + 26, y + 26], fill=col + (255,))
            d.text((x0 + 36, y + 13), str(u), font=fley, fill="white", anchor="lm")
        cache[clave] = lienzo
        return lienzo

    def dibujar(capa, pr, dt):
        capa.alpha_composite(preparar(pr), (0, MAPA_Y0))
    return dibujar
