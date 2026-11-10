"""Borrascas (con nombre o sin él), temporales y DANAs que entran en la península: detección y su evolución por horas.

- Detección con los datos de Open-Meteo: presión a nivel del mar (borrascas) y altura de 500 hPa (DANAs) cada 3 horas
  durante 3 días en una rejilla amplia del Atlántico y la península; se sigue la trayectoria del centro.
- Nombre: el que haya puesto AEMET (página de borrascas con gran impacto de la temporada), si es reciente.
- Vídeo: tramo «sistema» con tres animaciones seguidas: la borrasca/DANA moviéndose (isobaras y su trayectoria), la
  lluvia hora a hora y, si sopla fuerte, las rachas de viento hora a hora.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timedelta

import numpy as np
import requests
from PIL import Image, ImageDraw

from . import campos

log = logging.getLogger(__name__)

AMPLIA = (-36.0, 14.0, 24.0, 58.0, 2.0)        # rejilla de presión: cubre TODA la pantalla del tramo (y algo más)
VISTA_SISTEMA = (-28.0, 5.5, 25.3, 47.3)       # el Atlántico hasta la península, con Canarias en su sitio real (sin recuadro)
PENINSULA_BOX = (-9.5, 3.5, 36.0, 43.8)
VIENTO = (-10.4, 4.6, 35.4, 44.2, 0.6)         # rejilla de las rachas (península y Baleares)

# Las dos primeras clases (viento flojo) van más transparentes: el color llena TODA la pantalla, sin huecos ni bordes
ESCALA_VIENTO = [(0, (70, 130, 175)), (15, (80, 170, 195)), (30, (110, 215, 190)), (40, (30, 190, 115)), (50, (245, 220, 20)), (60, (255, 160, 10)),
                 (70, (250, 95, 10)), (80, (225, 25, 35)), (90, (185, 5, 105)), (100, (130, 15, 170)),
                 (120, (70, 5, 120))]


# ------------------------------------------------------------------ nombre de AEMET
def nombre_aemet(hoy: date) -> str | None:
    """Nombre de la borrasca de gran impacto más reciente de AEMET (si se nombró en los últimos 5 días)."""
    ini = hoy.year if hoy.month >= 9 else hoy.year - 1
    url = f"https://www.aemet.es/es/conocermas/borrascas/{ini}-{ini + 1}"
    try:
        html = requests.get(url, timeout=30, headers={"User-Agent": "paraguas-o-chanclas"}).text
    except Exception as e:  # noqa: BLE001
        log.info("Página de borrascas de AEMET no disponible: %s", e)
        return None
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = re.sub(r"\s+", " ", texto)
    meses = {m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                             "septiembre", "octubre", "noviembre", "diciembre"])}
    mejor = None
    for m in re.finditer(r"[Bb]orrasca\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)", texto):
        nombre = m.group(1)
        trozo = texto[m.start(): m.start() + 300]
        for d in re.finditer(r"(\d{1,2})\s*(?:/|-|de)\s*(\d{1,2}|[a-z]+)\s*(?:/|-|de)\s*(20\d\d)", trozo):
            dd, mm, aa = d.group(1), d.group(2), d.group(3)
            mes = int(mm) if mm.isdigit() else meses.get(mm.lower())
            try:
                f = date(int(aa), mes, int(dd))
            except (TypeError, ValueError):
                continue
            if 0 <= (hoy - f).days <= 5 and (mejor is None or f > mejor[1]):
                mejor = (nombre, f)
            break
    return mejor[0] if mejor else None


# ------------------------------------------------------------------ detección
def _datos(hoy: date):
    lons, lats = campos._rejilla(AMPLIA)
    puntos = [(la, lo) for la in lats for lo in lons]
    js = campos._pedir(puntos, {"hourly": "pressure_msl,geopotential_height_500hPa", "start_date": hoy.isoformat(),
                                "end_date": (hoy + timedelta(days=2)).isoformat()})
    horas = (js[0].get("hourly") or {}).get("time") or []
    sel = list(range(0, len(horas), 3))
    p = np.array([[((j.get("hourly") or {}).get("pressure_msl") or [1013] * len(horas))[k] or 1013 for k in sel]
                  for j in js], dtype=float)
    z = np.array([[((j.get("hourly") or {}).get("geopotential_height_500hPa") or [5700] * len(horas))[k] or 5700
                   for k in sel] for j in js], dtype=float)
    forma = (len(lats), len(lons))
    return lons, lats, [horas[k] for k in sel], [p[:, n].reshape(forma) for n in range(len(sel))], \
        [z[:, n].reshape(forma) for n in range(len(sel))]


def _minimos(lons, lats, v, umbral, caja, tam=7):
    from scipy.ndimage import gaussian_filter, minimum_filter
    s = gaussian_filter(v, 1.0)
    m = minimum_filter(s, size=tam) == s
    out = []
    for i, j in zip(*np.nonzero(m)):
        lo, la = float(lons[j]), float(lats[i])
        if 1 <= i < s.shape[0] - 1 and 1 <= j < s.shape[1] - 1 and s[i, j] <= umbral and \
                caja[0] <= lo <= caja[1] and caja[2] <= la <= caja[3]:
            out.append((lo, la, float(s[i, j])))
    return out


def _distancia_peninsula(lo, la) -> float:
    """Grados hasta la caja de la península (0 si está encima)."""
    dx = max(PENINSULA_BOX[0] - lo, 0, lo - PENINSULA_BOX[1]) * math.cos(math.radians(la))
    dy = max(PENINSULA_BOX[2] - la, 0, la - PENINSULA_BOX[3])
    return math.hypot(dx, dy)


def _seguir(serie, salto=4.5):
    """Une los mínimos de cada hora en trayectorias (el más cercano a menos de «salto» grados)."""
    tray = []
    for n, mins in enumerate(serie):
        usados = set()
        for t in tray:
            if t["fin"] != n - 1:
                continue
            lo0, la0, _ = t["puntos"][-1][1:]
            cand = [(math.hypot(lo - lo0, la - la0), k) for k, (lo, la, _) in enumerate(mins) if k not in usados]
            if cand:
                d, k = min(cand)
                if d <= salto:
                    usados.add(k)
                    t["puntos"].append((n, *mins[k]))
                    t["fin"] = n
        for k, m in enumerate(mins):
            if k not in usados:
                tray.append({"puntos": [(n, *m)], "fin": n})
    return [t for t in tray if len(t["puntos"]) >= 3]


def nombres_borrascas(texto: str | None, hoy: date) -> list[str]:
    """Todas las borrascas con nombre que cita AEMET ahora: en el texto dado (predicción, avisos) y en su página de
    borrascas de gran impacto (las de los últimos 5 días). En orden de aparición, sin repetir."""
    nombres = re.findall(r"[Bb]orrascas?\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})(?:\s+y\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}))?",
                         texto or "")
    out = [n for par in nombres for n in par if n]
    try:
        n = nombre_aemet(hoy)
        if n:
            out.append(n)
    except Exception:  # noqa: BLE001
        pass
    return list(dict.fromkeys(out))


def nombre_en_texto(texto: str | None) -> str | None:
    """«borrasca Bruna» en el texto de predicción de AEMET (por si la página de borrascas no lo tiene aún)."""
    m = re.search(r"[Bb]orrasca\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})", texto or "")
    return m.group(1) if m else None


def detectar(hoy: date, texto_aemet: str | None = None) -> dict | None:
    """El sistema que afecta (o va a afectar) a la península en los próximos 3 días, o None.
    {"tipo": "borrasca"|"dana", "nombre", "horas", "trayectoria": [(hora_iso, lon, lat, valor)], "minimo", "datos"}"""
    try:
        lons, lats, horas, ps, zs = _datos(hoy)
    except Exception as e:  # noqa: BLE001
        log.warning("Sin datos para detectar borrascas: %s", e)
        return None
    candidatos = []
    # borrascas: mínimo de presión cerrado ≤ 1004 hPa que pasa a menos de ~3,5° de la península
    for t in _seguir([_minimos(lons, lats, p, 1004, (-28, 8, 31, 51)) for p in ps]):
        d = min(_distancia_peninsula(lo, la) for _, lo, la, _ in t["puntos"])
        pmin = min(v for *_, v in t["puntos"])
        if d <= 3.5 or (pmin <= 990 and d <= 10):   # una borrasca profunda en el Atlántico (Bruna) también
            candidatos.append(("borrasca", pmin + 2 * d, t, pmin, d))
    # DANAs: mínimo cerrado a 500 hPa (≤ 5640 m) encima o muy cerca de la península
    for t in _seguir([_minimos(lons, lats, z, 5640, (-20, 8, 32, 48), tam=5) for z in zs]):
        d = min(_distancia_peninsula(lo, la) for _, lo, la, _ in t["puntos"])
        zmin = min(v for *_, v in t["puntos"])
        if d <= 2.0:
            candidatos.append(("dana", 900 + (zmin - 5640) / 10 - 10 * (2 - d), t, zmin, d))
    if not candidatos:
        return None
    # una borrasca en superficie manda (Bruna, aunque lleve aire frío en altura); la DANA, solo si no hay borrasca
    bor = [c for c in candidatos if c[0] == "borrasca"]
    tipo, _, t, vmin, d = min(bor or candidatos, key=lambda c: c[1])
    tray = [(horas[n], lo, la, v) for n, lo, la, v in t["puntos"]]
    nombres = nombres_borrascas(texto_aemet, hoy) if tipo == "borrasca" else []
    # Las demás borrascas que también afectan (Bruna y, detrás, Charles): hasta dos más, las de mayor impacto
    otros = []

    def _la_misma(a, b) -> bool:
        """Dos trazas que en realidad son la misma borrasca (el seguimiento se cortó o se duplicó)."""
        pa, pb = {q[0]: q[1:3] for q in a["puntos"]}, {q[0]: q[1:3] for q in b["puntos"]}
        comunes = set(pa) & set(pb)
        if comunes:
            return min(math.hypot(pa[n][0] - pb[n][0], pa[n][1] - pb[n][1]) for n in comunes) < 5.0
        primero, segundo = (a, b) if a["puntos"][-1][0] < b["puntos"][0][0] else (b, a)
        fin, ini = primero["puntos"][-1], segundo["puntos"][0]
        return ini[0] - fin[0] <= 2 and math.hypot(ini[1] - fin[1], ini[2] - fin[2]) <= 6.0

    if tipo == "borrasca":
        distintas = []
        for c in sorted([c for c in bor if c[2] is not t], key=lambda c: c[1]):
            if not _la_misma(c[2], t) and not any(_la_misma(c[2], x[2]) for x in distintas):
                distintas.append(c)
        for c in distintas[:2]:
            otros.append({"tipo": "borrasca", "nombre": None, "minimo": c[3], "distancia": c[4],
                          "trayectoria": [(horas[n], lo, la, v) for n, lo, la, v in c[2]["puntos"]]})
    principal = {"tipo": tipo, "nombre": None, "nombres": nombres, "trayectoria": tray, "minimo": vmin,
                 "distancia": d, "datos": (lons, lats, horas, ps, zs), "otros": otros}
    # Nombres de AEMET, en el orden en que los cita (el de la que llega antes, primero): la borrasca que antes se
    # acerca a la península recibe el primero. Si hay más borrascas que nombres, las últimas se quedan sin nombre.
    def _llegada(x):
        return min(x["trayectoria"], key=lambda q: _distancia_peninsula(q[1], q[2]))[0]
    for x, n_ in zip(sorted([principal, *otros], key=_llegada), nombres):
        x["nombre"] = n_
    for x in [principal, *otros]:   # trayectoria suavizada (la rejilla es de 2°: sin esto va a saltos)
        tr_ = x["trayectoria"]
        x["trayectoria"] = [tr_[0]] + [
            (b[0], (a[1] + 2 * b[1] + c[1]) / 4, (a[2] + 2 * b[2] + c[2]) / 4, b[3])
            for a, b, c in zip(tr_, tr_[1:], tr_[2:])] + [tr_[-1]]
    log.info("Sistema detectado: %s %s (mín. %.0f, a %.1f° de la península), %d pasos%s", tipo,
             principal["nombre"] or "", vmin, d, len(tray),
             "".join(f"; además borrasca {o['nombre'] or 'sin nombre'} (mín. {o['minimo']:.0f}, a {o['distancia']:.1f}°)"
                     for o in otros))
    return principal


def texto_guion(s: dict, cuando: str, segundos: float = 14.0) -> str:
    if not s:
        return ""
    tr = s["trayectoria"]
    t0 = datetime.fromisoformat(tr[0][0])
    t1 = datetime.fromisoformat(tr[-1][0])
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    def donde(lo, la):
        if _distancia_peninsula(lo, la) == 0:
            return "sobre la península"
        ns = "nor" if la > 43.8 else "sur" if la < 36 else ""
        eo = "oeste" if lo < -9.5 else "este" if lo > 3.5 else ""
        rumbo = (ns + eo) if ns and eo else ("norte" if ns == "nor" else ns) or eo
        return f"al {rumbo} de la península"
    quien = (f"la borrasca {s['nombre']}" if s.get("nombre") else "una borrasca") if s["tipo"] == "borrasca" \
        else "una DANA (depresión aislada en niveles altos)"
    dato = f"centro de {s['minimo']:.0f} hPa" if s["tipo"] == "borrasca" else "aire muy frío en altura"
    return (f"\n\nSISTEMA DEL DÍA: {quien} ({dato}). Su centro pasa de estar {donde(*tr[0][1:3])} ({dias[t0.weekday()]} "
            f"{t0.hour}:00) a {donde(*tr[-1][1:3])} ({dias[t1.weekday()]} {t1.hour}:00). Añade a \"segmentos\" la clave "
            f"\"sistema\" (unas {round(segundos * 2.7 / 2) * 2} palabras: en pantalla van {round(segundos)} segundos de mapas y tienen "
            "que verse enteros, no lo acortes), justo después del gancho (y del aviso, si lo hay): en pantalla se ve "
            f"primero {('la borrasca' if s['tipo'] == 'borrasca' else 'la DANA')} moviéndose con su trayectoria, luego "
            "la lluvia hora a hora y, si sopla fuerte, las rachas de viento hora a hora. Cuenta por dónde entra, cuándo "
            "llega lo peor (lluvia y viento) y cuándo se va" + (f"; llámala por su nombre, {s['nombre']}" if s.get("nombre")
                                                            else "; no le inventes nombre: solo AEMET los pone") + "."
            + "".join(
                f" ADEMÁS hay otra borrasca en pantalla, {('la borrasca ' + o['nombre']) if o.get('nombre') else 'sin nombre'} "
                f"(centro de {o['minimo']:.0f} hPa): pasa de {donde(*o['trayectoria'][0][1:3])} "
                f"({dias[datetime.fromisoformat(o['trayectoria'][0][0]).weekday()]}) a {donde(*o['trayectoria'][-1][1:3])} "
                f"({dias[datetime.fromisoformat(o['trayectoria'][-1][0]).weekday()]}). Cuenta las dos, en el orden en que "
                "llegan, y qué trae cada una." for o in (s.get("otros") or []))
            + (f" AEMET cita: {', '.join(s['nombres'])}."
               if len(s.get("nombres") or []) > 1 else ""))


# ------------------------------------------------------------------ capas del vídeo
def _imagen_campo(lons, lats, v, escala, px):
    """Campo en colores (escala discreta) como imagen RGBA en coordenadas lon/lat."""
    from scipy.ndimage import zoom
    f = max(1, int(px * (lons[1] - lons[0])))
    vv = zoom(v, f, order=1)
    h, w = vv.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    for u, col in escala:
        m = vv >= max(u, 0.5)   # 0 exacto = sin dato (el recuadro de Canarias): transparente
        rgba[m, :3] = col
        rgba[m, 3] = 238 if u >= 30 or escala[0][0] >= 30 else 150
    img = Image.fromarray(rgba[::-1], "RGBA")
    return img, (float(lons[0]), float(lons[-1]), float(lats[0]), float(lats[-1]))


def capa_trayectoria(s: dict, seg_por_fotograma: float = 0.32):
    """Isobaras moviéndose cada 3 horas con el centro (B o DANA) y la trayectoria completa marcada."""
    from .especiales import fuente
    from .video import MAPA_Y0, TRANSICION
    from .config import ANCHO
    lons, lats, horas, ps, zs = s["datos"]
    tr = s["trayectoria"]
    pasos = sorted({horas.index(h) for h, *_ in tr})
    k0, k1 = max(0, pasos[0] - 1), min(len(horas) - 1, pasos[-1] + 1)
    fotos = []
    for k in range(k0, k1 + 1):
        img, caja = campos._imagen_isobaras(lons, lats, ps[k])
        fotos.append((k, img, caja))
    cache: dict = {}
    f, f2, freloj = fuente("Black", 60), fuente("Black", 30), fuente("Black", 54)
    etiqueta = (f"BORRASCA {s['nombre'].upper()}" if s.get("nombre") else "BORRASCA") if s["tipo"] == "borrasca" \
        else "DANA"

    def dibujar(capa, pr, dt):
        n = min(len(fotos) - 1, int(max(0.0, dt - TRANSICION) / seg_por_fotograma))
        k, img, caja = fotos[n]
        # recortado al mapa: la rejilla de presión es más grande que la pantalla y no debe pisar el título
        campos._recortado(lambda lienzo, pr_, dt_: campos._pegar(lienzo, img, caja, pr_, 0, cache, f"p{n % 3}"))(
            capa, pr, dt)
        if len(cache) > 3:
            cache.clear()
        d = ImageDraw.Draw(capa)
        pts = [(pr(lo, la)[0], pr(lo, la)[1] + MAPA_Y0) for _, lo, la, _ in tr]
        if len(pts) > 1:   # trayectoria prevista (discontinua) y recorrida (continua)
            for a, b in zip(pts, pts[1:]):
                d.line([a, b], fill=(255, 255, 255, 140), width=5)
        actual = [(x, y) for (h, *_), (x, y) in zip(tr, pts) if horas.index(h) <= k]
        if len(actual) > 1:
            d.line(actual, fill=(255, 80, 80, 255), width=8)
        pos = next(((x, y, v) for (h, lo, la, v), (x, y) in zip(tr, pts) if horas.index(h) == k), None)
        if pos is None and actual:
            pos = (*actual[-1], tr[len(actual) - 1][3])
        if pos:
            x, y, v = pos
            col = (235, 60, 60) if s["tipo"] == "borrasca" else (150, 70, 200)
            d.ellipse([x - 44, y - 44, x + 44, y + 44], fill=(255, 255, 255, 235), outline=col + (255,), width=7)
            d.text((x, y - 2), "B" if s["tipo"] == "borrasca" else "D", font=f, fill=col + (255,), anchor="mm")
            txt = etiqueta + (f" · {v:.0f} hPa" if s["tipo"] == "borrasca" else "")
            w = f2.getlength(txt) + 30
            xx = min(max(x, w / 2 + 20), ANCHO - w / 2 - 20)
            d.rounded_rectangle([xx - w / 2, y + 52, xx + w / 2, y + 100], radius=20, fill=col + (235,))
            d.text((xx, y + 76), txt, font=f2, fill=(255, 255, 255, 255), anchor="mm")
        t = datetime.fromisoformat(horas[k])
        if s.get("otros"):   # las demás borrascas que hay en el mapa, con su nombre
            _marcar_centros(capa, pr, s["otros"], t, siempre_el_primero=False)
            d = ImageDraw.Draw(capa)
        reloj = f"{campos.DIAS_CORTOS[t.weekday()]} {t.hour:02d}:00"
        w = freloj.getlength(reloj) + 48
        d.rounded_rectangle([ANCHO - 40 - w, MAPA_Y0 + 24, ANCHO - 40, MAPA_Y0 + 104], radius=22, fill=(8, 20, 45, 225))
        d.text((ANCHO - 40 - w / 2, MAPA_Y0 + 64), reloj, font=freloj, fill=(255, 255, 255, 255), anchor="mm")
    dibujar.duracion = len(fotos) * seg_por_fotograma
    return dibujar


def viento_horario(ini: date, fin: date, caja=VIENTO):
    lons, lats = campos._rejilla(caja)
    puntos = [(la, lo) for la in lats for lo in lons]
    js = campos._pedir(puntos, {"hourly": "wind_gusts_10m", "start_date": ini.isoformat(), "end_date": fin.isoformat()})
    horas = (js[0].get("hourly") or {}).get("time") or []
    cubo = np.array([[x or 0 for x in ((j.get("hourly") or {}).get("wind_gusts_10m") or [0] * len(horas))]
                     for j in js], dtype=float)
    return lons, lats, horas, cubo.T.reshape(len(horas), len(lats), len(lons))


def capa_viento(lons, lats, horas, cubo, max_fotogramas: int = 14, seg_por_fotograma: float = 0.42,
                isobaras=None):
    """Rachas de viento hora a hora (km/h) en colores, con reloj y leyenda. None si no sopla fuerte.
    «isobaras» = (lons, lats, horas, presiones cada 3 h): se dibujan encima, como en los mapas de isobaras y viento."""
    from .especiales import fuente
    from .video import MAPA_H, MAPA_Y0, TRANSICION
    from .config import ANCHO
    from . import mapa as mapa_
    activas = [k for k in range(len(horas)) if cubo[k].max() >= 50]
    if not activas:
        return None
    k0, k1 = activas[0], activas[-1]
    paso = max(1, -(-(k1 - k0 + 1) // max_fotogramas))
    fotos = []
    horas_fotos = [horas[k] for k in range(k0, k1 + 1, paso)]
    for k in range(k0, k1 + 1, paso):
        img, caja = _imagen_campo(lons, lats, cubo[k:k + paso].max(axis=0), ESCALA_VIENTO, campos.PX_GRADO * 0.6)
        t = datetime.fromisoformat(horas[k])
        fotos.append((img, caja, f"{campos.DIAS_CORTOS[t.weekday()]} {t.hour:02d}:00"))
    cache: dict = {}
    provs = mapa_.provincias()
    f, fpeq, freloj = fuente("ExtraBold", 26), fuente("Bold", 20), fuente("Black", 54)
    # isobaras: la de la hora más cercana (hay una cada 3 horas)
    iso_de, iso_img = [], {}
    if isobaras:
        try:
            ilo, ila, ih, ips = isobaras[:4]
            tiempos = [datetime.fromisoformat(h) for h in ih]
            for h in horas_fotos:
                t = datetime.fromisoformat(h)
                iso_de.append(min(range(len(tiempos)), key=lambda q: abs((tiempos[q] - t).total_seconds())))
            for q in sorted(set(iso_de)):
                iso_img[q] = campos._imagen_isobaras(ilo, ila, ips[q], fondo=False)
        except Exception as e:  # noqa: BLE001
            log.warning("Sin isobaras sobre el viento: %s", e)
            iso_de, iso_img = [], {}

    def dibujar(capa, pr, dt):
        n = min(len(fotos) - 1, int(max(0.0, dt - TRANSICION) / seg_por_fotograma))
        img, caja, reloj = fotos[n]

        def campo(lienzo, pr_, dt_):
            campos._pegar(lienzo, img, caja, pr_, 0, cache, f"v{n}")
            if iso_de and iso_de[n] in iso_img:
                campos._pegar(lienzo, *iso_img[iso_de[n]], pr_, 0, cache, f"i{iso_de[n]}")
            d_ = ImageDraw.Draw(lienzo)
            for p_ in provs:
                for anillo in p_["anillos"]:
                    pts = [pr_(*campos.lonlat_mapa(lo, la, la < 30)) for lo, la in anillo]
                    d_.line(pts + [pts[0]], fill=(255, 255, 255, 200), width=3)
        campos._recortado(campo)(capa, pr, dt)
        if len(cache) > 6:
            for kk in list(cache)[:-4]:
                cache.pop(kk, None)
        d = ImageDraw.Draw(capa)
        w = freloj.getlength(reloj) + 48
        d.rounded_rectangle([ANCHO - 40 - w, MAPA_Y0 + 24, ANCHO - 40, MAPA_Y0 + 104], radius=22, fill=(8, 20, 45, 225))
        d.text((ANCHO - 40 - w / 2, MAPA_Y0 + 64), reloj, font=freloj, fill=(255, 255, 255, 255), anchor="mm")
        campos._leyenda_horizontal(capa, MAPA_Y0 + MAPA_H - 86,
                                   "ISOBARAS Y RACHAS DE VIENTO (KM/H)" if iso_img else "RACHAS DE VIENTO (KM/H)",
                                   f, fpeq, ESCALA_VIENTO)
    dibujar.duracion = len(fotos) * seg_por_fotograma
    dibujar.maximo = float(cubo.max())
    dibujar.horas_fotos, dibujar.seg = horas_fotos, seg_por_fotograma
    return dibujar


def _etiqueta(x: dict) -> str:
    if x["tipo"] == "borrasca":
        return f"BORRASCA {x['nombre'].upper()}" if x.get("nombre") else "BORRASCA"
    return f"DANA {x['nombre'].upper()}" if x.get("nombre") else "DANA"


def titulo_sistemas(s: dict) -> str:
    """Rótulo del tramo: «BORRASCA BRUNA, HORA A HORA» o «BRUNA Y CHARLES, HORA A HORA» si hay dos con nombre."""
    orden = sorted([s, *(s.get("otros") or [])],   # en el orden en que llegan
                   key=lambda x: min(x["trayectoria"], key=lambda q: _distancia_peninsula(q[1], q[2]))[0])
    con_nombre = [x["nombre"].upper() for x in orden if x.get("nombre")]
    if len(con_nombre) > 1:
        return " Y ".join(con_nombre[:2]) + ", HORA A HORA"
    if s["tipo"] == "borrasca":
        return (_etiqueta(s) if s.get("nombre") else "LA BORRASCA") + ", HORA A HORA"
    return "LA DANA, HORA A HORA"


def _centro_en(x: dict, t: datetime, margen_h: float = 3.0):
    """Posición del centro en el instante t (interpolada); None si ese sistema aún no existe o ya se ha ido."""
    tr = [(datetime.fromisoformat(h), lo, la) for h, lo, la, _ in x["trayectoria"]]
    if t < tr[0][0] - timedelta(hours=margen_h) or t > tr[-1][0] + timedelta(hours=margen_h):
        return None
    if t <= tr[0][0]:
        return tr[0][1:]
    for (ta, xa, ya), (tb, xb, yb) in zip(tr, tr[1:]):
        if ta <= t <= tb:
            u = (t - ta).total_seconds() / max(1.0, (tb - ta).total_seconds())
            return xa + (xb - xa) * u, ya + (yb - ya) * u
    return tr[-1][1:]


def _marcar_centros(capa, pr, sistemas: list, t: datetime, siempre_el_primero: bool = True):
    """La B (o D) de cada borrasca/DANA con su nombre, en su sitio a esa hora. Si queda fuera, pegada al borde."""
    from .especiales import fuente
    from .video import MAPA_H, MAPA_Y0
    from .config import ANCHO
    f, f2 = fuente("Black", 54), fuente("Black", 30)
    d = ImageDraw.Draw(capa)
    puestos = []
    for n, x in enumerate(sistemas):
        pos = _centro_en(x, t, 1e6 if (n == 0 and siempre_el_primero) else 3.0)
        if pos is None:
            continue
        px, py = pr(*pos)
        py += MAPA_Y0
        px = min(max(px, 70), ANCHO - 70)
        py = min(max(py, MAPA_Y0 + 160), MAPA_Y0 + MAPA_H - 210)
        while any(abs(px - a) < 230 and abs(py - b) < 120 for a, b in puestos) and py < MAPA_Y0 + MAPA_H - 330:
            py += 125   # dos centros muy juntos: que no se pisen los rótulos
        puestos.append((px, py))
        borr = x["tipo"] == "borrasca"
        col = (235, 60, 60) if borr else (150, 70, 200)
        d.ellipse([px - 40, py - 40, px + 40, py + 40], fill=(255, 255, 255, 240), outline=col + (255,), width=7)
        d.text((px, py - 2), "B" if borr else "D", font=f, fill=col + (255,), anchor="mm")
        txt = _etiqueta(x)
        w = f2.getlength(txt) + 30
        xx = min(max(px, w / 2 + 20), ANCHO - w / 2 - 20)
        d.rounded_rectangle([xx - w / 2, py + 48, xx + w / 2, py + 96], radius=20, fill=col + (240,))
        d.text((xx, py + 72), txt, font=f2, fill=(255, 255, 255, 255), anchor="mm")


def con_centro(capa_fn, s: dict):
    """Sobre la lluvia o el viento hora a hora: el centro de cada borrasca o DANA moviéndose, con su nombre, para
    que se vea de quién es todo lo que hay en pantalla (Bruna, y detrás Charles)."""
    from .video import TRANSICION
    if not capa_fn or not s or not s.get("trayectoria") or not getattr(capa_fn, "horas_fotos", None):
        return capa_fn
    sistemas = [s, *(s.get("otros") or [])]

    def dibujar(capa, pr, dt):
        capa_fn(capa, pr, dt)
        n = min(len(capa_fn.horas_fotos) - 1, int(max(0.0, dt - TRANSICION) / capa_fn.seg))
        _marcar_centros(capa, pr, sistemas, datetime.fromisoformat(capa_fn.horas_fotos[n]))
    for k in ("duracion", "peso", "maximo", "horas_fotos", "seg"):
        if hasattr(capa_fn, k):
            setattr(dibujar, k, getattr(capa_fn, k))
    return dibujar


COMODO = 5.0   # segundos que necesita cada animación (trayectoria, lluvia, viento) para verse entera con calma


def secuencia(capas: list, fundido: float = 0.5):
    """Varias animaciones una detrás de otra dentro del mismo tramo. Se reparten TODO el tramo a partes parecidas
    (algo más la que tiene más incidencia: atributo «peso»), y cada una se reproduce entera, a su propio ritmo
    uniforme, dentro de su parte: ninguna va a toda prisa ni se queda a medias."""
    from .video import TRANSICION
    capas = [c for c in capas if c]
    nat = [getattr(c, "duracion", 5.0) for c in capas]
    pesos = [getattr(c, "peso", 1.0) for c in capas]
    partes = [COMODO * w for w in pesos]
    est = {"ini": [sum(partes[:k]) for k in range(len(capas))], "parte": partes}

    def ajustar(dur_tramo: float):
        util = max(2.0, dur_tramo - TRANSICION - 0.2)
        est["parte"] = [util * w / sum(pesos) for w in pesos]
        est["ini"] = [sum(est["parte"][:k]) for k in range(len(capas))]

    def _local(n, tt):
        """Tiempo «natural» de la animación n: recorre todos sus fotogramas en su parte (el último se queda 0,7 s)."""
        parte = max(0.5, est["parte"][n] - 0.7)
        return TRANSICION + min(nat[n] - 0.01, max(0.0, tt - est["ini"][n]) * nat[n] / parte)

    def dibujar(capa, pr, dt):
        tt = dt - TRANSICION
        n = max([k for k, t0 in enumerate(est["ini"]) if tt >= t0] or [0])
        if n and tt - est["ini"][n] < fundido:   # fundido corto con la anterior
            capas[n - 1](capa, pr, _local(n - 1, tt))
            tmp = Image.new("RGBA", capa.size, (0, 0, 0, 0))
            capas[n](tmp, pr, _local(n, tt))
            s = max(0.0, (tt - est["ini"][n]) / fundido)
            tmp.putalpha(tmp.getchannel("A").point(lambda v: int(v * s)))
            capa.alpha_composite(tmp)
            return
        capas[n](capa, pr, _local(n, tt) if tt >= 0 else dt)
    dibujar.duracion = sum(partes)
    dibujar.ajustar = ajustar
    dibujar.n = len(capas)
    return dibujar


def _ventana_pico(lo, la, horas, cubo) -> str | None:
    """Entre qué horas llueve con más fuerza sobre la península (las horas con al menos el 60 % del máximo)."""
    mi = (lo >= PENINSULA_BOX[0]) & (lo <= PENINSULA_BOX[1])
    mj = (la >= PENINSULA_BOX[2]) & (la <= PENINSULA_BOX[3])
    if not mi.any() or not mj.any():
        return None
    serie = np.array([float(c[np.ix_(mj, mi)].mean()) for c in cubo])
    if serie.max() < 0.15:
        return None
    k = np.nonzero(serie >= 0.6 * serie.max())[0]
    a, b = datetime.fromisoformat(horas[int(k[0])]), datetime.fromisoformat(horas[int(k[-1])]) + timedelta(hours=1)
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"de las {a.hour}:00 del {dias[a.weekday()]} a las {b.hour}:00 del {dias[b.weekday()]}"


def preparar(s: dict, hoy: date):
    """Capa del tramo «sistema» (trayectoria → lluvia hora a hora → rachas) y datos para el guion."""
    from datetime import timedelta as _td
    tr = s["trayectoria"]
    # la animación empieza el día del parte (no cuando el centro de la borrasca se acerca, que puede ser el jueves)
    ini = hoy
    fin = min(max(datetime.fromisoformat(tr[-1][0]).date(), hoy), hoy + _td(days=2))
    trozos, notas = [capa_trayectoria(s)], []
    try:
        from .especiales import _visible
        caja = (*_visible(VISTA_SISTEMA, 1.6), 1.0)   # toda la pantalla, sin recuadro (un modelo: menos datos)
        lo, la, horas, cubo = campos.lluvia_horaria(ini, caja, fin, modelos=False)
        ev = campos.capa_evolucion(lo, la, horas, cubo, False, max_fotogramas=14, seg_por_fotograma=0.42)
        if ev:
            acum = cubo.sum(axis=0)
            ev.peso = 1.3 if acum.max() >= 80 else 1.15 if acum.max() >= 40 else 1.0   # más lluvia, más tiempo
            trozos.append(con_centro(ev, s))
            notas.append(f"lluvia máxima acumulada en el periodo ≈ {acum.max():.0f} l/m²")
            pico = _ventana_pico(lo, la, horas, cubo)
            if pico:
                notas.append(f"lo más intenso de la lluvia sobre la península: {pico} (dilo así, con las horas: "
                             "«lo más fuerte, entre las diez de la mañana y las seis de la tarde»; nunca frases "
                             "ambiguas como «con lo peor de la mañana a la tarde»)")
    except Exception as e:  # noqa: BLE001
        log.warning("Sin lluvia hora a hora para el sistema: %s", e)
    try:
        from .especiales import _visible
        lo_v, la_v, h_v, c_v = viento_horario(ini, fin, (*_visible(VISTA_SISTEMA, 1.9), 1.2))
        cv = capa_viento(lo_v, la_v, h_v, c_v, isobaras=s.get("datos"))
        if cv and cv.maximo >= 60:
            cv.peso = 1.3 if cv.maximo >= 100 else 1.15 if cv.maximo >= 80 else 1.0   # más viento, más tiempo
            trozos.append(con_centro(cv, s))
            notas.append(f"rachas de hasta {cv.maximo:.0f} km/h")
    except Exception as e:  # noqa: BLE001
        log.warning("Sin rachas hora a hora para el sistema: %s", e)
    return secuencia(trozos), notas


# ------------------------------------------------------------------ el temporal, hora a hora, en los vídeos de aviso
def _por_provincias(lo, la, horas, cubo, umbral: float, cortes: int = 4, n: int = 3) -> dict:
    """Por dónde va pasando: en varios momentos, las provincias peninsulares con más lluvia o viento en esa hora."""
    from . import mapa as mapa_
    activas = [k for k in range(len(horas)) if np.nanmax(cubo[k]) >= umbral]
    if not activas:
        return {}
    k0, k1 = activas[0], activas[-1]
    ks = sorted({k0 + round((k1 - k0) * i / max(1, cortes - 1)) for i in range(cortes)})
    centros = []
    for p in mapa_.provincias():
        anillos = [a for a in p["anillos"] if a]   # también Canarias (en el plano de las borrascas van en su sitio)
        if anillos:
            a = max(anillos, key=len)
            centros.append((p["nombre"].split("/")[-1], sum(q[0] for q in a) / len(a), sum(q[1] for q in a) / len(a)))
    out = {}
    for k in ks:
        t = datetime.fromisoformat(horas[k])
        vals = []
        for nombre, x, y in centros:
            i, j = int(np.abs(lo - x).argmin()), int(np.abs(la - y).argmin())
            v = float(np.nanmax(cubo[k][max(0, j - 1):j + 2, max(0, i - 1):i + 2]))
            if v >= umbral:
                vals.append((v, nombre))
        if vals:
            out[f"{campos.DIAS_CORTOS[t.weekday()]} {t.hour:02d}:00"] = [f"{nm} ({v:.0f})" for v, nm in sorted(vals, reverse=True)[:n]]
    return out


def preparar_aviso(hoy: date, fin: date, texto: str = ""):
    """Tramo «temporal» de los vídeos de aviso: mapa amplio con la lluvia hora a hora y las rachas hora a hora (y la
    trayectoria si hay una borrasca o DANA identificada). Devuelve (capa, datos para el guion, etiqueta) o None."""
    from datetime import timedelta as _td
    from .especiales import _visible
    fin = min(max(fin, hoy), hoy + _td(days=2))
    trozos, datos, etiqueta, s = [], {}, "EL TEMPORAL, HORA A HORA", None
    try:
        s = detectar(hoy, texto)
        if s and (s.get("nombre") or s["distancia"] == 0 or (s["tipo"] == "borrasca" and s["minimo"] <= 1000)):
            trozos.append(capa_trayectoria(s))
            etiqueta = titulo_sistemas(s)
            datos["sistema"] = (f"{s['tipo']}" + (f" {s['nombre']}" if s.get("nombre") else "")
                                + (f", mínimo de {s['minimo']:.0f} hPa" if s["tipo"] == "borrasca" else "")
                                + "".join(f"; y detrás la borrasca {o['nombre'] or 'sin nombre'} ({o['minimo']:.0f} hPa)"
                                          for o in s.get("otros") or []))
        else:
            s = None
    except Exception as e:  # noqa: BLE001
        log.warning("Aviso: sin trayectoria del sistema: %s", e)
    try:
        lo, la, horas, cubo = campos.lluvia_horaria(hoy, (*_visible(VISTA_SISTEMA, 1.6), 1.0), fin, modelos=False)
        ev = campos.capa_evolucion(lo, la, horas, cubo, False, max_fotogramas=14, seg_por_fotograma=0.42)
        if ev:
            ev.peso = 1.3 if cubo.sum(axis=0).max() >= 80 else 1.0
            trozos.append(con_centro(ev, s))
            datos["lluvia_por_donde_pasa_l_m2_en_1_hora"] = _por_provincias(lo, la, horas, cubo, 1.0)
    except Exception as e:  # noqa: BLE001
        log.warning("Aviso: sin lluvia hora a hora del temporal: %s", e)
    try:
        lo_v, la_v, h_v, c_v = viento_horario(hoy, fin, (*_visible(VISTA_SISTEMA, 1.9), 1.2))
        cv = capa_viento(lo_v, la_v, h_v, c_v, isobaras=(s or {}).get("datos"))
        if cv and cv.maximo >= 45:
            cv.peso = 1.3 if cv.maximo >= 100 else 1.15 if cv.maximo >= 80 else 1.0
            trozos.append(con_centro(cv, s))
            datos["rachas_por_donde_pasa_km_h"] = _por_provincias(lo_v, la_v, h_v, c_v, 45.0)
    except Exception as e:  # noqa: BLE001
        log.warning("Aviso: sin rachas hora a hora del temporal: %s", e)
    if not [t for t in trozos if t]:
        return None
    return secuencia(trozos), datos, etiqueta

