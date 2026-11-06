"""Los sitios más fríos y más calurosos de verdad, no solo las capitales.

- Previsión: un puñado de pueblos que suelen ser los más fríos (valles y páramos del interior) o los más calurosos
  (valle del Guadalquivir, Vegas del Guadiana, sur de Canarias...), con el mismo consenso de modelos que las capitales.
- Observado: la mínima y la máxima más extremas que han medido las estaciones de AEMET (se guardan cada hora, porque
  la API solo da las últimas ~12 h).
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
RAIZ = Path(__file__).resolve().parent.parent
OBSERVADOS = RAIZ / "estado" / "extremos_observados.json"
TZ = ZoneInfo("Europe/Madrid")

# (pueblo, provincia, lat, lon) — pueblos habitados, sin cumbres ni estaciones de esquí
FRIOS = [
    ("Molina de Aragón", "Guadalajara", 40.844, -1.886), ("Sigüenza", "Guadalajara", 41.068, -2.643),
    ("Calamocha", "Teruel", 40.919, -1.298), ("Albarracín", "Teruel", 40.408, -1.444),
    ("Griegos", "Teruel", 40.422, -1.711), ("Daroca", "Zaragoza", 41.114, -1.414),
    ("Tragacete", "Cuenca", 40.347, -1.849), ("Medinaceli", "Soria", 41.172, -2.434),
    ("El Burgo de Osma", "Soria", 41.587, -3.067), ("Aranda de Duero", "Burgos", 41.670, -3.689),
    ("Villarcayo", "Burgos", 42.938, -3.571), ("Reinosa", "Cantabria", 43.002, -4.137),
    ("Aguilar de Campoo", "Palencia", 42.794, -4.260), ("Riaño", "León", 42.972, -5.007),
    ("Astorga", "León", 42.458, -6.056), ("Puebla de Sanabria", "Zamora", 42.054, -6.635),
    ("Vitigudino", "Salamanca", 41.010, -6.435), ("Guijuelo", "Salamanca", 40.558, -5.671),
    ("Béjar", "Salamanca", 40.386, -5.763), ("Peñaranda de Bracamonte", "Salamanca", 40.902, -5.205),
    ("El Barco de Ávila", "Ávila", 40.357, -5.523), ("Navarredonda de Gredos", "Ávila", 40.360, -5.128),
    ("Cuéllar", "Segovia", 41.401, -4.314), ("Rascafría", "Madrid", 40.904, -3.880),
    ("Ezcaray", "La Rioja", 42.326, -3.013), ("Isaba", "Navarra", 42.861, -0.921),
    ("Jaca", "Huesca", 42.570, -0.549), ("Sabiñánigo", "Huesca", 42.519, -0.364),
    ("Benasque", "Huesca", 42.604, 0.523), ("Vielha", "Lleida", 42.702, 0.796),
    ("La Seu d'Urgell", "Lleida", 42.358, 1.461), ("Puigcerdà", "Girona", 42.432, 1.928),
    ("Olot", "Girona", 42.181, 2.490), ("Morella", "Castellón", 40.619, -0.101),
    ("Vilafranca", "Castellón", 40.415, -0.257), ("Ademuz", "Valencia", 40.061, -1.287),
    ("Villena", "Alicante", 38.637, -0.866), ("Huéscar", "Granada", 37.810, -2.541),
    ("Guadix", "Granada", 37.300, -3.137), ("Baza", "Granada", 37.490, -2.773),
    ("Xinzo de Limia", "Ourense", 42.063, -7.724), ("A Gudiña", "Ourense", 42.061, -7.139),
]
CALIDOS = [
    ("Montoro", "Córdoba", 38.024, -4.383), ("Palma del Río", "Córdoba", 37.700, -5.283),
    ("Écija", "Sevilla", 37.542, -5.083), ("Lora del Río", "Sevilla", 37.659, -5.527),
    ("Andújar", "Jaén", 38.039, -4.051), ("El Granado", "Huelva", 37.521, -7.405),
    ("Don Benito", "Badajoz", 38.956, -5.861), ("Almendralejo", "Badajoz", 38.683, -6.408),
    ("Talavera de la Reina", "Toledo", 39.963, -4.830), ("Lorca", "Murcia", 37.677, -1.701),
    ("Orihuela", "Alicante", 38.085, -0.944), ("Xàtiva", "Valencia", 38.990, -0.518),
    ("Fraga", "Huesca", 41.522, 0.349), ("Caspe", "Zaragoza", 41.235, -0.039),
    ("Motril", "Granada", 36.745, -3.518), ("Vélez-Málaga", "Málaga", 36.781, -4.101),
    ("Maspalomas", "Las Palmas", 27.760, -15.586), ("Adeje", "Santa Cruz de Tenerife", 28.122, -16.726),
    ("La Aldea de San Nicolás", "Las Palmas", 27.984, -15.780), ("Tías", "Las Palmas", 28.961, -13.645),
]


MUNICIPIOS = RAIZ / "estado" / "municipios_pueblos.json"


def _norm(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").replace("'", "").strip()


def _ids_aemet(clave: str) -> dict:
    """Código de municipio de AEMET de cada pueblo (se busca una vez en /maestro/municipios y se guarda)."""
    try:
        ids = json.loads(MUNICIPIOS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        ids = {}
    faltan = [x for x in FRIOS if x[0] not in ids]
    if faltan and clave:
        from .fuentes import _aemet_get
        try:
            maestro = json.loads(_aemet_get("/maestro/municipios", clave))
        except Exception as e:  # noqa: BLE001
            log.warning("Maestro de municipios de AEMET no disponible: %s", e)
            maestro = []
        for n, _, la, lo in faltan:
            cand = []
            for m in maestro:
                nombres = {_norm(m.get("nombre", ""))} | {_norm(x) for x in m.get("nombre", "").split("/")}
                if _norm(n) in nombres or any(_norm(n) == x.split(",")[0] for x in nombres):
                    try:
                        d = math.hypot(float(m["latitud_dec"]) - la, float(m["longitud_dec"]) - lo)
                    except Exception:  # noqa: BLE001
                        d = 9
                    cand.append((d, m["id"].replace("id", "")))
            if cand and min(cand)[0] < 0.3:
                ids[n] = min(cand)[1]
        MUNICIPIOS.parent.mkdir(exist_ok=True)
        MUNICIPIOS.write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding="utf-8")
    return ids


def previstos(dia: date, aemet: bool = True) -> dict:
    """{'frio': {nombre, provincia, tmin}, 'calor': {nombre, provincia, tmax}} según la previsión de ese día.
    Con clave de AEMET se usa su predicción municipal (recoge mejor las heladas de los valles); si no, el consenso de
    modelos de Open-Meteo (que suaviza mucho las mínimas de los sitios más fríos)."""
    from .fuentes import _openmeteo_todas, aemet_ciudad
    clave = os.environ.get("AEMET_API_KEY", "") if aemet else ""
    ids = _ids_aemet(clave) if clave else {}
    out = {}
    for k, lista, var, elegir in (("frio", FRIOS, "tmin", min), ("calor", CALIDOS, "tmax", max)):
        try:
            om = _openmeteo_todas([{"id": n, "lat": la, "lon": lo} for n, _, la, lo in lista], dia)
        except Exception as e:  # noqa: BLE001
            log.warning("Previsión de pueblos (%s) no disponible: %s", k, e)
            om = {}
        vals = []
        # AEMET solo para el frío y para los 12 pueblos más fríos según los modelos (cada consulta tarda; con todos
        # se iban casi 20 minutos por los límites de AEMET)
        candidatos = set()
        if k == "frio":
            orden = sorted((om[n][var], n) for n, *_ in lista if (om.get(n) or {}).get(var) is not None)
            candidatos = {n for _, n in orden[:12]} or {n for n, *_ in lista}
        for n, p, _, _ in lista:
            v = None
            if n in ids and n in candidatos:
                try:
                    v = aemet_ciudad({"id": ids[n]}, clave, dia)[var]
                except Exception as e:  # noqa: BLE001
                    log.info("AEMET %s: %s", n, e)
            if v is None:
                v = (om.get(n) or {}).get(var)
            if v is not None:
                vals.append((v, n, p))
        if vals:
            v, n, p = elegir(vals)
            out[k] = {"nombre": n, "provincia": p, var: int(round(v))}
    return out


# ---------------------------------------------------------------- observado (estaciones de AEMET)
def _iso(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("+0000", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _dentro(x: float, y: float, anillo) -> bool:
    dentro = False
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            dentro = not dentro
    return dentro


def _cerca_de(la: float, lo: float) -> str:
    """Provincia del punto (por los polígonos del mapa); si cae en el mar, la ciudad grande más cercana."""
    from . import mapa
    for p in mapa.provincias():
        if any(_dentro(lo, la, a) for a in p["anillos"]):
            n = p["nombre"].split("/")[-1]
            return {"Illes Balears": "Baleares", "Santa Cruz De Tenerife": "Santa Cruz de Tenerife"}.get(n, n)
    from .poblaciones import GRANDES
    n, _, _ = min(GRANDES, key=lambda c: math.hypot((c[1] - la), (c[2] - lo) * math.cos(math.radians(la))))
    return n


def _nombre_estacion(s: str) -> str:
    s = s.split(",")[0].split("/")[0].strip()
    return " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in s.split())


def registrar(ahora: datetime | None = None):
    """Lo llama el workflow de respuestas cada hora: guarda, por día (hora de Madrid), la mínima y la máxima más
    extremas medidas en España."""
    from .fuentes import _aemet_get
    obs = json.loads(_aemet_get("/observacion/convencional/todas", os.environ.get("AEMET_API_KEY", "")))
    try:
        est = json.loads(OBSERVADOS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        est = {}
    for o in obs:
        try:
            dia = _iso(o["fint"]).astimezone(TZ).date().isoformat()
            la, lo = float(o["lat"]), float(o["lon"])
        except Exception:  # noqa: BLE001
            continue
        if not (27 <= la <= 44.5 and -18.5 <= lo <= 4.5):
            continue
        d = est.setdefault(dia, {})
        for k, campo, mejor in (("min", "tamin", lambda a, b: a < b), ("max", "tamax", lambda a, b: a > b)):
            v = o.get(campo)
            if not isinstance(v, (int, float)) or not -30 <= v <= 50:
                continue
            if (o.get("alt") or 0) > 1500:   # cumbres y puertos: no son «un pueblo»
                continue
            if k not in d or mejor(v, d[k]["valor"]):
                d[k] = {"valor": v, "sitio": _nombre_estacion(o.get("ubi", "")), "zona": _cerca_de(la, lo),
                        "hora": o["fint"]}
    hoy = (ahora or datetime.now(timezone.utc)).astimezone(TZ).date()
    est = {k: v for k, v in est.items() if date.fromisoformat(k) >= hoy - timedelta(days=4)}
    OBSERVADOS.parent.mkdir(exist_ok=True)
    OBSERVADOS.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Extremos observados de hoy: %s", est.get(hoy.isoformat()))


def observados(dia: date) -> dict:
    try:
        return json.loads(OBSERVADOS.read_text(encoding="utf-8")).get(dia.isoformat(), {})
    except Exception:  # noqa: BLE001
        return {}


def _g(v) -> str:
    return "grado" if abs(v) == 1 else "grados"


def _num(v) -> str:
    return str(round(v, 1)).replace(".", ",").replace(",0", "")


def _capitales(prev, var, elegir) -> tuple[list[str], int]:
    v = elegir(c[var] for c in prev)
    return [c["nombre"] for c in prev if c[var] == v][:3], v


def _y(nombres: list[str]) -> str:
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def texto(prev: list[dict], dia: date, hoy: date, cuando: str = "mañana") -> tuple[str, dict]:
    """Nota para el guion + extremos para el mapa: la capital (o capitales) más fría y, además, el sitio que de verdad
    será el más frío de España (un pueblo de donde sea); igual con el calor."""
    nf, vf = _capitales(prev, "tmin", min)
    nc, vc = _capitales(prev, "tmax", max)
    capf = next(c for c in prev if c["nombre"] == nf[0])
    capc = next(c for c in prev if c["nombre"] == nc[0])
    p = previstos(dia)
    extremos = {"calor": capc, "frio": capf}
    caps = "las capitales" if len(nf) > 1 else "la capital"
    frio = f"{caps} más fría{'s' if len(nf) > 1 else ''}, {_y(nf)}, con {vf} {_g(vf)}"
    f = p.get("frio")
    if f and f["tmin"] < vf:
        frio += f"; y el sitio más frío de España, {f['nombre']} ({f['provincia']}), con {f['tmin']} {_g(f['tmin'])}"
        extremos["frio"] = {**capf, "nombre": f["nombre"], "tmin": f["tmin"]}
    caps = "las capitales" if len(nc) > 1 else "la capital"
    calor = f"{caps} más calurosa{'s' if len(nc) > 1 else ''}, {_y(nc)}, con {vc} {_g(vc)}"
    c = p.get("calor")
    if c and c["tmax"] > vc:
        calor += f"; y el sitio más caluroso de España, {c['nombre']} ({c['provincia']}), con {c['tmax']} {_g(c['tmax'])}"
        extremos["calor"] = {**capc, "nombre": c["nombre"], "tmax": c["tmax"]}
    txt = (f"\n\nLO MÁS FRÍO Y LO MÁS CALUROSO DE ESPAÑA {cuando.upper()} (capitales y pueblos): FRÍO: {frio}. "
           f"CALOR: {calor}. En el bloque general di las DOS cosas: la capital (o capitales) más fría y, si hay un "
           "sitio aún más frío, ese pueblo con su provincia, esté donde esté («la capital más fría, Burgos, con 0 "
           "grados; pero lo más frío de España será Molina de Aragón, en Guadalajara, con −4»). Igual con el calor. "
           "En el mapa sale el sitio más extremo.")
    o = observados(hoy).get("min")
    if o and o["valor"] <= 0:
        txt += (f" Dato medido, si quieres usarlo como curiosidad en media frase: esta madrugada la estación de "
                f"AEMET de {o['sitio']} ({o['zona']}) marcó {_num(o['valor'])} grados, lo más frío de España.")
    return txt, extremos


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    if sys.argv[1:] == ["registrar"]:
        registrar()
    else:
        print(previstos(date.today() + timedelta(days=1)))
