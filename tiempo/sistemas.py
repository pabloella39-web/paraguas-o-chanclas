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

AMPLIA = (-30.0, 10.0, 30.0, 52.0, 2.0)        # rejilla para seguir el centro (Atlántico + península)
VISTA_SISTEMA = (-21.0, 6.5, 32.5, 48.5)       # lo que se ve en el vídeo durante el tramo
PENINSULA_BOX = (-9.5, 3.5, 36.0, 43.8)
VIENTO = (-10.4, 4.6, 35.4, 44.2, 0.6)         # rejilla de las rachas (península y Baleares)

ESCALA_VIENTO = [(30, (170, 225, 205)), (40, (110, 205, 160)), (50, (240, 225, 90)), (60, (250, 180, 60)),
                 (70, (245, 120, 50)), (80, (225, 60, 60)), (90, (190, 40, 120)), (100, (140, 50, 170)),
                 (120, (90, 40, 140))]


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
    nombre = nombres[0] if nombres else None
    log.info("Sistema detectado: %s %s (mín. %.0f, a %.1f° de la península), %d pasos", tipo, nombre or "", vmin, d,
             len(tray))
    return {"tipo": tipo, "nombre": nombre, "nombres": nombres, "trayectoria": tray, "minimo": vmin, "distancia": d,
            "datos": (lons, lats, horas, ps, zs)}


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
            + (f" AEMET cita también: {', '.join(s['nombres'][1:])} (detrás o a la vez): nómbrala(s)."
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
        m = vv >= u
        rgba[m, :3] = col
        rgba[m, 3] = 205
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
        campos._pegar(capa, img, caja, pr, MAPA_Y0, cache, f"p{n % 3}")
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


def capa_viento(lons, lats, horas, cubo, max_fotogramas: int = 14, seg_por_fotograma: float = 0.42):
    """Rachas de viento hora a hora (km/h) en colores, con reloj y leyenda. None si no sopla fuerte."""
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
    for k in range(k0, k1 + 1, paso):
        img, caja = _imagen_campo(lons, lats, cubo[k:k + paso].max(axis=0), ESCALA_VIENTO, campos.PX_GRADO * 0.6)
        t = datetime.fromisoformat(horas[k])
        fotos.append((img, caja, f"{campos.DIAS_CORTOS[t.weekday()]} {t.hour:02d}:00"))
    cache: dict = {}
    provs = mapa_.provincias()
    f, fpeq, freloj = fuente("ExtraBold", 26), fuente("Bold", 20), fuente("Black", 54)

    def dibujar(capa, pr, dt):
        n = min(len(fotos) - 1, int(max(0.0, dt - TRANSICION) / seg_por_fotograma))
        img, caja, reloj = fotos[n]

        def campo(lienzo, pr_, dt_):
            campos._pegar(lienzo, img, caja, pr_, 0, cache, f"v{n}")
            d_ = ImageDraw.Draw(lienzo)
            for p_ in provs:
                for anillo in p_["anillos"]:
                    pts = [pr_(*campos.lonlat_mapa(lo, la, la < 30)) for lo, la in anillo]
                    d_.line(pts + [pts[0]], fill=(255, 255, 255, 200), width=3)
        campos._recortado(campo)(capa, pr, dt)
        if len(cache) > 4:
            for kk in list(cache)[:-2]:
                cache.pop(kk, None)
        d = ImageDraw.Draw(capa)
        w = freloj.getlength(reloj) + 48
        d.rounded_rectangle([ANCHO - 40 - w, MAPA_Y0 + 24, ANCHO - 40, MAPA_Y0 + 104], radius=22, fill=(8, 20, 45, 225))
        d.text((ANCHO - 40 - w / 2, MAPA_Y0 + 64), reloj, font=freloj, fill=(255, 255, 255, 255), anchor="mm")
        campos._leyenda_horizontal(capa, MAPA_Y0 + MAPA_H - 86, "RACHAS DE VIENTO (KM/H)", f, fpeq, ESCALA_VIENTO)
    dibujar.duracion = len(fotos) * seg_por_fotograma
    dibujar.maximo = float(cubo.max())
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
        caja = (*_visible(VISTA_SISTEMA, 0.3), 1.0)   # toda la pantalla, sin recuadro (un modelo: menos datos)
        lo, la, horas, cubo = campos.lluvia_horaria(ini, caja, fin, modelos=False)
        cubo = np.stack([campos.sin_recuadro_canarias(lo, la, c) for c in cubo])
        ev = campos.capa_evolucion(lo, la, horas, cubo, False, max_fotogramas=14, seg_por_fotograma=0.42)
        if ev:
            trozos.append(ev)
            acum = cubo.sum(axis=0)
            ev.peso = 1.3 if acum.max() >= 80 else 1.15 if acum.max() >= 40 else 1.0   # más lluvia, más tiempo
            notas.append(f"lluvia máxima acumulada en el periodo ≈ {acum.max():.0f} l/m²")
    except Exception as e:  # noqa: BLE001
        log.warning("Sin lluvia hora a hora para el sistema: %s", e)
    try:
        from .especiales import _visible
        lo_v, la_v, h_v, c_v = viento_horario(ini, fin, (*_visible(VISTA_SISTEMA, 0.3), 1.2))
        c_v = np.stack([campos.sin_recuadro_canarias(lo_v, la_v, c) for c in c_v])
        cv = capa_viento(lo_v, la_v, h_v, c_v)
        if cv and cv.maximo >= 60:
            cv.peso = 1.3 if cv.maximo >= 100 else 1.15 if cv.maximo >= 80 else 1.0   # más viento, más tiempo
            trozos.append(cv)
            notas.append(f"rachas de hasta {cv.maximo:.0f} km/h")
    except Exception as e:  # noqa: BLE001
        log.warning("Sin rachas hora a hora para el sistema: %s", e)
    return secuencia(trozos), notas
