"""Imagen de satélite del día (NASA GIBS, VIIRS en color real, dominio público) con isobaras y centros de altas
(A) y bajas (B) presiones calculados con Open-Meteo (presión a nivel del mar). Para los días con borrascas, DANAs,
ciclogénesis o anticiclones potentes.

python -m tiempo.satelite [AAAA-MM-DD] [salida.png]
"""
from __future__ import annotations

import io
import json
import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter

log = logging.getLogger(__name__)
LON0, LON1, LAT0, LAT1 = -24.0, 10.0, 26.0, 51.0     # Península, Baleares, Canarias y el Atlántico cercano
GIBS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
CAPAS = ["VIIRS_NOAA20_CorrectedReflectance_TrueColor", "VIIRS_NOAA21_CorrectedReflectance_TrueColor",
         "VIIRS_SNPP_CorrectedReflectance_TrueColor", "MODIS_Terra_CorrectedReflectance_TrueColor"]
COS = math.cos(math.radians((LAT0 + LAT1) / 2))
ATRIBUCION = "Imagen: NASA (VIIRS) · Presión: Open-Meteo"


def _gibs(capa: str, dia: date, ancho: int, alto: int, max_negro: float = 0.25) -> Image.Image | None:
    try:
        r = requests.get(GIBS, timeout=90, params={
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.1.1", "LAYERS": capa, "SRS": "EPSG:4326",
            "BBOX": f"{LON0},{LAT0},{LON1},{LAT1}", "WIDTH": ancho, "HEIGHT": alto, "FORMAT": "image/jpeg",
            "TIME": dia.isoformat()})
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
            log.warning("GIBS %s %s: HTTP %s", capa, dia, r.status_code)
            return None
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        a = np.asarray(im)
        negro = (a.sum(axis=2) < 25).mean()
        log.info("GIBS %s %s: %.0f %% sin datos", capa, dia, 100 * negro)
        return im if negro < max_negro else None
    except Exception as e:  # noqa: BLE001
        log.warning("GIBS %s: %s", capa, e)
        return None


def imagen_satelite(dia: date, ancho: int = 1360) -> tuple[Image.Image, date]:
    """Mosaico del día: el primer satélite y, en sus huecos entre pasadas (negro), los demás; si hoy aún no hay
    imagen (la NASA la publica unas horas después del paso), la de ayer."""
    alto = round(ancho * (LAT1 - LAT0) / (LON1 - LON0))
    for d in (dia, dia - timedelta(days=1)):
        base, hueco = None, None
        for capa in CAPAS:
            im = _gibs(capa, d, ancho, alto, max_negro=0.9)
            if im is None:
                continue
            a = np.asarray(im).astype(np.int16)
            vacio = a.sum(axis=2) < 25
            if base is None:
                base, hueco = a.copy(), vacio
            else:
                base[hueco] = a[hueco]
                hueco = hueco & vacio
            if hueco.mean() < 0.01:
                break
        if base is not None and hueco.mean() < 0.12:
            if hueco.any():  # restos de hueco: se rellenan con la imagen de la víspera
                prev = _gibs(CAPAS[0], d - timedelta(days=1), ancho, alto, max_negro=0.9)
                if prev is not None:
                    base[hueco] = np.asarray(prev).astype(np.int16)[hueco]
            im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
            log.info("Satélite %s: %.1f %% sin cubrir", d, 100 * hueco.mean())
            # De equirrectangular a proporciones reales (los grados de longitud son más cortos)
            return im.resize((round(ancho * COS), alto), Image.LANCZOS), d
    raise RuntimeError("Sin imagen de satélite")


def presion(dia: date, paso: float = 1.5):
    lons = np.arange(LON0, LON1 + 0.01, paso)
    lats = np.arange(LAT0, LAT1 + 0.01, paso)
    LO, LA = np.meshgrid(lons, lats)
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=120, params={
        "latitude": ",".join(f"{x:.2f}" for x in LA.ravel()), "longitude": ",".join(f"{x:.2f}" for x in LO.ravel()),
        "hourly": "pressure_msl,geopotential_height_500hPa", "timezone": "UTC", "start_date": dia.isoformat(), "end_date": dia.isoformat()})
    r.raise_for_status()
    d = r.json()
    d = d if isinstance(d, list) else [d]
    p = np.array([x["hourly"]["pressure_msl"][12] for x in d], dtype=float).reshape(LA.shape)  # 12 UTC
    z = np.array([x["hourly"]["geopotential_height_500hPa"][12] for x in d], dtype=float).reshape(LA.shape)
    return lons, lats, p, z


def _sin_repetir(lista, dist=4.0):
    out = []
    for c in sorted(lista, key=lambda c: c[3] if c[0] != "A" else -c[3]):
        if all(math.hypot(c[1] - o[1], c[2] - o[2]) > dist for o in out if o[0] == c[0]):
            out.append(c)
    return out


def centros(lons, lats, p, z=None, radio: int = 3):
    """A y B en superficie; DANA = mínimo aislado del geopotencial en 500 hPa sin borrasca debajo."""
    out = []
    for i in range(1, p.shape[0] - 1):
        for j in range(1, p.shape[1] - 1):
            v = p[i, j]
            ven = p[max(0, i - radio):i + radio + 1, max(0, j - radio):j + radio + 1]
            if v == ven.min() and v <= 1010:
                out.append(("B", lons[j], lats[i], v))
            elif v == ven.max() and v >= 1020:
                out.append(("A", lons[j], lats[i], v))
            if z is not None:
                vz = z[i, j]
                vz_ven = z[max(0, i - radio):i + radio + 1, max(0, j - radio):j + radio + 1]
                # cerrada: más baja que todo su entorno y al menos 40 m por debajo del borde de la ventana
                borde = np.concatenate([vz_ven[0], vz_ven[-1], vz_ven[:, 0], vz_ven[:, -1]])
                if vz == vz_ven.min() and borde.min() - vz >= 40 and vz < 5700:
                    out.append(("DANA", lons[j], lats[i], vz))
    return _sin_repetir(out)


def componer(dia: date, salida: Path | None = None) -> tuple[Image.Image, dict]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sat, dia_sat = imagen_satelite(dia)
    W, H = sat.size
    lons, lats, p, z = presion(dia)
    # Isobaras cada 4 hPa con matplotlib sobre un lienzo transparente del mismo tamaño
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    ax.axis("off")
    from scipy.ndimage import zoom
    fino = zoom(p, 4, order=3)
    lo2 = np.linspace(LON0, lons[-1], fino.shape[1])
    la2 = np.linspace(LAT0, lats[-1], fino.shape[0])
    niveles = np.arange(960, 1052, 4)
    cs = ax.contour(lo2, la2, fino, levels=niveles, colors="white", linewidths=2.2, alpha=0.85)
    ax.clabel(cs, fmt="%d", fontsize=13, colors="white")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True, dpi=100)
    plt.close(fig)
    capa = Image.open(io.BytesIO(buf.getvalue())).convert("RGBA").resize((W, H))
    img = sat.convert("RGBA")
    img = Image.alpha_composite(img, Image.new("RGBA", img.size, (0, 0, 0, 40)))
    img.alpha_composite(capa)
    # Silueta de España
    from .config import RAIZ
    esp = json.loads((RAIZ / "assets" / "espana.json").read_text())
    d = ImageDraw.Draw(img)

    def xy(lon, lat):
        return (lon - LON0) / (LON1 - LON0) * W, (LAT1 - lat) / (LAT1 - LAT0) * H
    for prov in esp:
        for an in prov["anillos"]:
            d.line([xy(lo, la) for lo, la in an] + [xy(*an[0])], fill=(255, 220, 120, 150), width=1)
    # A y B
    from .mapa import fuente
    f = fuente("Black", 92)
    cs_ = centros(lons, lats, p, z)
    for tipo, lo, la, v in cs_:
        x, y = xy(lo, la)
        if tipo == "DANA":
            w = fuente("Black", 54).getlength("DANA") + 50
            d.rounded_rectangle([x - w / 2, y - 44, x + w / 2, y + 44], radius=44, fill=(150, 40, 200, 235),
                                outline=(255, 255, 255, 255), width=5)
            d.text((x, y - 2), "DANA", font=fuente("Black", 54), fill=(255, 255, 255), anchor="mm")
            continue
        col = (40, 120, 255) if tipo == "A" else (230, 40, 50)
        d.ellipse([x - 62, y - 62, x + 62, y + 62], fill=col + (230,), outline=(255, 255, 255, 255), width=5)
        d.text((x, y - 4), tipo, font=f, fill=(255, 255, 255), anchor="mm")
        d.text((x, y + 92), f"{round(v)} hPa", font=fuente("Bold", 30), fill=(255, 255, 255), anchor="mm",
               stroke_width=4, stroke_fill=(0, 0, 0))
    d.text((W - 16, H - 14), ATRIBUCION, font=fuente("SemiBold", 22), fill=(255, 255, 255, 220), anchor="rd",
           stroke_width=3, stroke_fill=(0, 0, 0))
    info = {"dia_satelite": dia_sat.isoformat(), "centros": [(t, round(lo, 1), round(la, 1), round(v)) for t, lo, la, v in cs_]}
    if salida:
        img.convert("RGB").save(salida, quality=92)
    return img, info


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dia = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    sal = Path(sys.argv[2] if len(sys.argv) > 2 else "satelite.jpg")
    _, info = componer(dia, sal)
    print(json.dumps(info))
