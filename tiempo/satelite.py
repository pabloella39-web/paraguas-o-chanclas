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
                if vz == vz_ven.min() and borde.min() - vz >= 25 and vz < 5750:
                    out.append(("DANA", lons[j], lats[i], vz))
    return _sin_repetir(out)


def componer(dia: date, salida: Path | None = None) -> tuple[Image.Image, dict]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sat, dia_sat = imagen_satelite(dia)
    W, H = sat.size
    lons, lats, p, z = presion(dia_sat)   # la situación del mismo día que la foto
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
        x, y = min(max(x, 90), W - 90), min(max(y, 70), H - 130)   # que no se corte en el borde
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


def clip_muestra(img: Image.Image, salida: Path, segundos: float = 5.0):
    """Clip vertical de muestra: título arriba, la imagen con un acercamiento lento y la atribución."""
    import subprocess
    from .mapa import fuente
    W, H, fps = 1080, 1920, 30
    base = img.convert("RGB")
    esc = W / base.width
    base = base.resize((W, round(base.height * esc)), Image.LANCZOS)
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                             f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                             "-crf", "22", str(salida)], stdin=subprocess.PIPE)
    for k in range(int(segundos * fps)):
        t = k / (segundos * fps)
        z = 1 + 0.12 * t
        bw, bh = round(W * z), round(base.height * z)
        im = base.resize((bw, bh), Image.BILINEAR).crop(((bw - W) // 2, (bh - base.height) // 2,
                                                         (bw - W) // 2 + W, (bh - base.height) // 2 + base.height))
        f = Image.new("RGB", (W, H), (6, 16, 38))
        y0 = (H - base.height) // 2 + 60
        f.paste(im, (0, y0))
        d = ImageDraw.Draw(f)
        d.text((W // 2, y0 - 120), "ASÍ LO VE EL SATÉLITE", font=fuente("Black", 76), fill=(255, 196, 45),
               anchor="mm")
        d.text((W // 2, y0 - 50), "Altas (A) y bajas (B) presiones", font=fuente("Bold", 40), fill=(220, 230, 255),
               anchor="mm")
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    proc.wait()


def viento(dia: date, nivel: str = "700hPa", paso: float = 1.5, hora: int = 12):
    """Viento previsto en altura (por defecto 700 hPa, unos 3.000 m: el que arrastra nubes y frentes)."""
    lons = np.arange(LON0, LON1 + 0.01, paso)
    lats = np.arange(LAT0, LAT1 + 0.01, paso)
    LO, LA = np.meshgrid(lons, lats)
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=120, params={
        "latitude": ",".join(f"{x:.2f}" for x in LA.ravel()), "longitude": ",".join(f"{x:.2f}" for x in LO.ravel()),
        "hourly": f"wind_speed_{nivel},wind_direction_{nivel}", "timezone": "UTC", "wind_speed_unit": "kmh",
        "start_date": dia.isoformat(), "end_date": dia.isoformat()})
    r.raise_for_status()
    d = r.json()
    d = d if isinstance(d, list) else [d]
    vel = np.array([x["hourly"][f"wind_speed_{nivel}"][hora] for x in d], dtype=float).reshape(LA.shape)
    dirc = np.array([x["hourly"][f"wind_direction_{nivel}"][hora] for x in d], dtype=float).reshape(LA.shape)
    rad = np.radians(dirc)
    u, v = -vel * np.sin(rad), -vel * np.cos(rad)   # hacia dónde sopla (este, norte)
    return lons, lats, u, v


def clip_viento(img: Image.Image, dia: date, salida: Path, segundos: float = 6.0, titulo: str = "ASÍ SE MUEVE EL TIEMPO"):
    """Foto de satélite fija + partículas que fluyen con el viento previsto + flecha de avance (si hay viento
    organizado sobre la Península)."""
    import subprocess
    from .mapa import fuente
    lons, lats, u, v = viento(dia)
    W, H, fps = 1080, 1920, 30
    base = img.convert("RGB")
    esc = W / base.width
    base = base.resize((W, round(base.height * esc)), Image.LANCZOS)
    bh = base.height
    y0 = (H - bh) // 2 + 60

    def uv(px, py):  # interpolación bilineal en píxeles de la imagen
        lon = LON0 + px / W * (LON1 - LON0)
        lat = LAT1 - py / bh * (LAT1 - LAT0)
        fi = np.clip((lat - lats[0]) / (lats[1] - lats[0]), 0, len(lats) - 1.001)
        fj = np.clip((lon - lons[0]) / (lons[1] - lons[0]), 0, len(lons) - 1.001)
        i0, j0 = fi.astype(int), fj.astype(int)
        di, dj = fi - i0, fj - j0
        def b(m):
            return (m[i0, j0] * (1 - di) * (1 - dj) + m[i0 + 1, j0] * di * (1 - dj) +
                    m[i0, j0 + 1] * (1 - di) * dj + m[i0 + 1, j0 + 1] * di * dj)
        return b(u), b(v)

    rnd = np.random.default_rng(7)
    n = 2200
    px, py = rnd.uniform(0, W, n), rnd.uniform(0, bh, n)
    edad = rnd.integers(0, 60, n)
    k = 0.055                       # km/h → píxeles por fotograma (60 km/h ≈ 3,3 px)
    estela = np.zeros((bh, W), np.float32)
    # Flecha de avance: viento medio sobre la Península
    msk = (lambda LO, LA: (LO > -10) & (LO < 4) & (LA > 36) & (LA < 44))(*np.meshgrid(lons, lats))
    um, vm = u[msk].mean(), v[msk].mean()
    vmed = math.hypot(um, vm)
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                             f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                             "-crf", "22", str(salida)], stdin=subprocess.PIPE)
    fondo_sat = np.asarray(base).astype(np.float32) * 0.85
    for f_ in range(int(segundos * fps)):
        uu, vv = uv(px, py)
        nx, ny = px + uu * k, py - vv * k
        estela *= 0.92
        # trazos: se marca el segmento recorrido
        for t in (0.0, 0.33, 0.66, 1.0):
            xs = np.clip((px + (nx - px) * t).astype(int), 0, W - 1)
            ys = np.clip((py + (ny - py) * t).astype(int), 0, bh - 1)
            estela[ys, xs] = np.maximum(estela[ys, xs], np.clip(np.hypot(uu, vv) / 60, 0.35, 1.0))
        px, py, edad = nx, ny, edad + 1
        fuera = (px < 0) | (px >= W) | (py < 0) | (py >= bh) | (edad > 70) | (np.hypot(uu, vv) < 3)
        m = int(fuera.sum())
        px[fuera], py[fuera], edad[fuera] = rnd.uniform(0, W, m), rnd.uniform(0, bh, m), 0
        e = Image.fromarray((np.clip(estela, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
        a = np.asarray(e).astype(np.float32)[..., None] / 255
        sat = fondo_sat * (1 - a) + np.array([255, 255, 255], np.float32) * a
        cuadro = Image.new("RGB", (W, H), (6, 16, 38))
        cuadro.paste(Image.fromarray(sat.astype(np.uint8)), (0, y0))
        d = ImageDraw.Draw(cuadro, "RGBA")
        if vmed >= 20:  # flecha grande con el sentido del avance, que palpita
            cx, cy = W * 0.47, y0 + bh * 0.47
            ang = math.atan2(-vm, um)
            pul = 1 + 0.08 * math.sin(f_ / fps * 6)
            L = 260 * pul
            x1, y1 = cx - math.cos(ang) * L / 2, cy - math.sin(ang) * L / 2
            x2, y2 = cx + math.cos(ang) * L / 2, cy + math.sin(ang) * L / 2
            d.line([(x1, y1), (x2, y2)], fill=(255, 196, 45, 235), width=26)
            pa = [(x2 + math.cos(ang) * 40, y2 + math.sin(ang) * 40),
                  (x2 + math.cos(ang + 2.4) * 70, y2 + math.sin(ang + 2.4) * 70),
                  (x2 + math.cos(ang - 2.4) * 70, y2 + math.sin(ang - 2.4) * 70)]
            d.polygon(pa, fill=(255, 196, 45, 235))
        d.text((W // 2, y0 - 120), titulo, font=fuente("Black", 74), fill=(255, 196, 45), anchor="mm")
        d.text((W // 2, y0 - 50), "Satélite + viento previsto a 3.000 m", font=fuente("Bold", 40),
               fill=(220, 230, 255), anchor="mm")
        proc.stdin.write(cuadro.tobytes())
    proc.stdin.close()
    proc.wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dia = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    sal = Path(sys.argv[2] if len(sys.argv) > 2 else "satelite.jpg")
    im, info = componer(dia, sal)
    print(json.dumps(info))
    clip_muestra(im, sal.with_suffix(".mp4"))
    clip_viento(im, date.fromisoformat(info["dia_satelite"]), sal.with_name(sal.stem + "_viento.mp4"))
