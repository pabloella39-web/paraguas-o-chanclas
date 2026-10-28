"""Descarga y fusión de datos: AEMET OpenData + Open-Meteo (multimodelo) + Google Weather (opcional)."""
from __future__ import annotations

import logging
import os
import time
from datetime import date

import requests

from .config import CIUDADES

log = logging.getLogger(__name__)

AEMET_BASE = "https://opendata.aemet.es/opendata/api"
GOOGLE_URL = "https://weather.googleapis.com/v1/forecast/days:lookup"

# Categorías de icono que entiende el renderizador
SOL, SOL_NUBES, NUBES, LLUVIA, CHUBASCOS, TORMENTA, NIEVE, NIEBLA = (
    "sol", "sol_nubes", "nubes", "lluvia", "chubascos", "tormenta", "nieve", "niebla")


# ---------------------------------------------------------------- AEMET
def _aemet_get(ruta: str, clave: str, intentos: int = 5):
    """AEMET responde en dos pasos: una URL de 'datos' y luego el contenido (ISO-8859-15)."""
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(f"{AEMET_BASE}{ruta}", headers={"api_key": clave, "cache-control": "no-cache"},
                             timeout=30)
            meta = r.json()
            if meta.get("estado") == 429 or r.status_code == 429:
                log.info("AEMET pide esperar (límite de peticiones); reintento en %d s", 20 * (i + 1))
                time.sleep(20 * (i + 1))
                raise RuntimeError("AEMET: límite de peticiones")
            if meta.get("estado") != 200:
                raise RuntimeError(f"AEMET {ruta}: {meta.get('descripcion')}")
            r2 = requests.get(meta["datos"], timeout=30)
            r2.raise_for_status()
            return r2.content.decode("iso-8859-15")
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"AEMET falló tras {intentos} intentos: {ultimo}")


def _aemet_cielo(codigo: str) -> str | None:
    """Códigos de estadoCielo de AEMET -> icono."""
    if not codigo:
        return None
    c = codigo.rstrip("n")
    try:
        n = int(c)
    except ValueError:
        return None
    if n == 11:
        return SOL
    if n in (12, 17):
        return SOL_NUBES
    if n in (13,):
        return SOL_NUBES
    if 14 <= n <= 16:
        return NUBES
    if 23 <= n <= 26 or 43 <= n <= 46:
        return CHUBASCOS if n in (23, 43) else LLUVIA
    if 33 <= n <= 36 or 71 <= n <= 74:
        return NIEVE
    if 51 <= n <= 54 or 61 <= n <= 64:
        return TORMENTA
    if n in (81, 82, 83):
        return NIEBLA
    return None


def _periodo(lista, preferidos=("00-24", "12-24", "06-12", "12-18")):
    por_periodo = {x.get("periodo", "00-24"): x for x in (lista or [])}
    for p in preferidos:
        x = por_periodo.get(p)
        if x and str(x.get("value", "")).strip() != "":
            return x
    for x in lista or []:
        if str(x.get("value", "")).strip() != "":
            return x
    return None


def aemet_ciudad(ciudad: dict, clave: str, hoy: date) -> dict:
    import json
    datos = json.loads(_aemet_get(f"/prediccion/especifica/municipio/diaria/{ciudad['id']}", clave))
    dias = datos[0]["prediccion"]["dia"]
    dia = next((d for d in dias if d["fecha"].startswith(hoy.isoformat())), dias[0])
    cielo = _periodo(dia.get("estadoCielo"))
    prob = _periodo(dia.get("probPrecipitacion"))
    probs = [int(x["value"]) for x in dia.get("probPrecipitacion", []) if str(x.get("value", "")).isdigit()]
    vientos = [int(x.get("velocidad") or 0) for x in dia.get("viento", []) if str(x.get("velocidad", "")).isdigit()]
    # Probabilidad por franjas: la del día entero (00-24) incluye la madrugada y la noche, y decir "paraguas" por
    # cuatro gotas a las 23:00 se percibe como un fallo. El dato principal es el de las horas de calle (06-18).
    franjas = {}
    for x in dia.get("probPrecipitacion", []):
        if str(x.get("value", "")).isdigit():
            franjas[x.get("periodo", "00-24")] = int(x["value"])
    lluvia_franjas = {n: franjas[p] for n, p in (("madrugada", "00-06"), ("mañana", "06-12"), ("tarde", "12-18"),
                                                ("noche", "18-24")) if p in franjas}
    if "mañana" in lluvia_franjas or "tarde" in lluvia_franjas:
        lluvia = max(lluvia_franjas.get("mañana", 0), lluvia_franjas.get("tarde", 0))
    else:
        lluvia = int(prob["value"]) if prob else (max(probs) if probs else 0)
    return {
        "tmax": int(dia["temperatura"]["maxima"]),
        "tmin": int(dia["temperatura"]["minima"]),
        "lluvia": lluvia,
        "lluvia_franjas": lluvia_franjas or None,
        "viento": max(vientos) if vientos else None,
        "icono": _aemet_cielo(str(cielo["value"])) if cielo else None,
        "cielo": cielo.get("descripcion") if cielo else None,
        "uv": dia.get("uvMax"),
    }


def aemet_texto_nacional(clave: str) -> str:
    try:
        return _aemet_get("/prediccion/nacional/hoy", clave).strip()
    except Exception as e:  # noqa: BLE001
        log.warning("Sin predicción nacional de AEMET: %s", e)
        return ""


# ---------------------------------------------------------------- Google
_GOOGLE_ICONO = {
    "CLEAR": SOL, "MOSTLY_CLEAR": SOL, "PARTLY_CLOUDY": SOL_NUBES, "MOSTLY_CLOUDY": NUBES, "CLOUDY": NUBES,
    "WINDY": SOL_NUBES, "WIND_AND_RAIN": LLUVIA,
    "LIGHT_RAIN_SHOWERS": CHUBASCOS, "CHANCE_OF_SHOWERS": CHUBASCOS, "SCATTERED_SHOWERS": CHUBASCOS,
    "RAIN_SHOWERS": CHUBASCOS, "HEAVY_RAIN_SHOWERS": LLUVIA, "LIGHT_TO_MODERATE_RAIN": LLUVIA,
    "MODERATE_TO_HEAVY_RAIN": LLUVIA, "RAIN": LLUVIA, "LIGHT_RAIN": LLUVIA, "HEAVY_RAIN": LLUVIA,
    "RAIN_PERIODICALLY_HEAVY": LLUVIA,
    "LIGHT_SNOW_SHOWERS": NIEVE, "CHANCE_OF_SNOW_SHOWERS": NIEVE, "SCATTERED_SNOW_SHOWERS": NIEVE,
    "SNOW_SHOWERS": NIEVE, "HEAVY_SNOW_SHOWERS": NIEVE, "LIGHT_TO_MODERATE_SNOW": NIEVE,
    "MODERATE_TO_HEAVY_SNOW": NIEVE, "SNOW": NIEVE, "LIGHT_SNOW": NIEVE, "HEAVY_SNOW": NIEVE,
    "SNOWSTORM": NIEVE, "SNOW_PERIODICALLY_HEAVY": NIEVE, "HEAVY_SNOW_STORM": NIEVE, "BLOWING_SNOW": NIEVE,
    "RAIN_AND_SNOW": NIEVE, "HAIL": TORMENTA, "HAIL_SHOWERS": TORMENTA,
    "THUNDERSTORM": TORMENTA, "THUNDERSHOWER": TORMENTA, "LIGHT_THUNDERSTORM_RAIN": TORMENTA,
    "SCATTERED_THUNDERSTORMS": TORMENTA, "HEAVY_THUNDERSTORM": TORMENTA,
}


def google_ciudad(ciudad: dict, clave: str) -> dict:
    r = requests.get(GOOGLE_URL, params={
        "key": clave, "location.latitude": ciudad["lat"], "location.longitude": ciudad["lon"],
        "days": 1, "languageCode": "es",
    }, timeout=30)
    r.raise_for_status()
    d = r.json()["forecastDays"][0]
    dia = d.get("daytimeForecast", {})
    cond = dia.get("weatherCondition", {})
    return {
        "tmax": d["maxTemperature"]["degrees"],
        "tmin": d["minTemperature"]["degrees"],
        "lluvia": dia.get("precipitation", {}).get("probability", {}).get("percent"),
        "viento": dia.get("wind", {}).get("speed", {}).get("value"),
        "racha": dia.get("wind", {}).get("gust", {}).get("value"),
        "icono": _GOOGLE_ICONO.get(cond.get("type", ""), None),
        "cielo": cond.get("description", {}).get("text"),
        "tormenta": dia.get("thunderstormProbability"),
    }


# ---------------------------------------------------------------- Open-Meteo (sin clave)
OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
# Varios modelos numéricos; se usa la mediana entre ellos (consenso)
MODELOS = ["ecmwf_ifs025", "icon_seamless", "meteofrance_seamless", "gfs_seamless"]
_WMO = {0: SOL, 1: SOL, 2: SOL_NUBES, 3: NUBES, 45: NIEBLA, 48: NIEBLA,
        51: LLUVIA, 53: LLUVIA, 55: LLUVIA, 56: LLUVIA, 57: LLUVIA, 61: LLUVIA, 63: LLUVIA, 65: LLUVIA,
        66: LLUVIA, 67: LLUVIA, 71: NIEVE, 73: NIEVE, 75: NIEVE, 77: NIEVE, 80: CHUBASCOS, 81: CHUBASCOS,
        82: CHUBASCOS, 85: NIEVE, 86: NIEVE, 95: TORMENTA, 96: TORMENTA, 99: TORMENTA}
_VARS = ["temperature_2m_max", "temperature_2m_min", "precipitation_probability_max", "precipitation_sum",
         "weather_code", "wind_speed_10m_max", "wind_gusts_10m_max"]


def _mediana(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def openmeteo_todas(ciudades: list[dict], hoy: date) -> dict[str, dict]:
    """Una sola petición para todas las ciudades y todos los modelos."""
    r = requests.get(OPENMETEO_URL, params={
        "latitude": ",".join(str(c["lat"]) for c in ciudades),
        "longitude": ",".join(str(c["lon"]) for c in ciudades),
        "daily": ",".join(_VARS), "models": ",".join(MODELOS),
        "timezone": "Europe/Madrid", "start_date": hoy.isoformat(), "end_date": hoy.isoformat(),
        "wind_speed_unit": "kmh",
    }, timeout=60)
    r.raise_for_status()
    datos = r.json()
    if isinstance(datos, dict):
        datos = [datos]
    out = {}
    for c, d in zip(ciudades, datos):
        dia = d.get("daily", {})

        def serie(var):
            vals = []
            for m in MODELOS:
                v = dia.get(f"{var}_{m}", dia.get(var) if len(MODELOS) == 1 else None)
                if isinstance(v, list) and v and v[0] is not None:
                    vals.append(v[0])
            return vals

        codigos = serie("weather_code")
        # Icono: el código más "severo" que den al menos la mitad de los modelos
        icono = None
        if codigos:
            codigos.sort(reverse=True)
            icono = _WMO.get(int(codigos[len(codigos) // 2]))
        lluvia_mm = _mediana(serie("precipitation_sum"))
        prob = _mediana(serie("precipitation_probability_max"))
        if prob is None and lluvia_mm is not None:
            # Probabilidad aproximada: % de modelos que dan al menos 1 mm
            mm = serie("precipitation_sum")
            prob = round(100 * sum(1 for v in mm if v >= 1) / len(mm)) if mm else None
        out[c["id"]] = {
            "tmax": _mediana(serie("temperature_2m_max")),
            "tmin": _mediana(serie("temperature_2m_min")),
            "lluvia": prob,
            "lluvia_mm": lluvia_mm,
            "viento": _mediana(serie("wind_speed_10m_max")),
            "racha": _mediana(serie("wind_gusts_10m_max")),
            "icono": icono,
            "modelos": len(serie("temperature_2m_max")),
        }
    return out


# ---------------------------------------------------------------- Fusión
# Peso de cada fuente: AEMET (oficial, con predictores humanos) pesa más
PESOS = {"AEMET": 0.5, "Open-Meteo": 0.3, "Google": 0.2}


def _ponderada(valores: dict):
    vals = {k: v for k, v in valores.items() if v is not None}
    if not vals:
        return None
    tot = sum(PESOS[k] for k in vals)
    return round(sum(PESOS[k] * v for k, v in vals.items()) / tot)


def fusionar(ciudad: dict, fuentes_: dict[str, dict | None]) -> dict:
    f = {k: v for k, v in fuentes_.items() if v}
    if not f:
        raise RuntimeError(f"Sin datos para {ciudad['nombre']}")

    def campo(nombre):
        return _ponderada({k: d.get(nombre) for k, d in f.items()})

    # Icono: AEMET manda; si no hay, Open-Meteo; luego Google
    icono = next((f[k]["icono"] for k in ("AEMET", "Open-Meteo", "Google") if k in f and f[k].get("icono")),
                 SOL_NUBES)
    tmaxes = [d["tmax"] for d in f.values() if d.get("tmax") is not None]
    res = {
        **{k: ciudad[k] for k in ("id", "nombre", "lat", "lon", "region")},
        "tmax": campo("tmax"), "tmin": campo("tmin"),
        "lluvia": campo("lluvia") or 0, "viento": campo("viento"),
        "racha": _ponderada({k: d.get("racha") for k, d in f.items() if k != "AEMET"}),
        "lluvia_mm": (f.get("Open-Meteo") or {}).get("lluvia_mm"),          # litros previstos (mediana de modelos)
        "lluvia_franjas": (f.get("AEMET") or {}).get("lluvia_franjas"),      # % por mañana / tarde / noche
        "icono": icono,
        "cielo": next((f[k].get("cielo") for k in ("AEMET", "Google") if k in f and f[k].get("cielo")), None),
        "fuentes": list(f),
    }
    if len(tmaxes) >= 2:
        res["discrepancia_tmax"] = round(max(tmaxes) - min(tmaxes))
    return res


EXTRA: list[dict] = []   # previsión de CIUDADES_EXTRA del último obtener_previsiones (para el guion)


def obtener_extra(hoy: date) -> list[dict]:
    from .config import CIUDADES_EXTRA
    cs = [{"id": f"x{k}", "nombre": n, "lat": la, "lon": lo, "region": r} for k, (n, la, lo, r) in enumerate(CIUDADES_EXTRA)]
    try:
        om = openmeteo_todas(cs, hoy)
    except Exception as e:  # noqa: BLE001
        log.warning("Ciudades extra sin datos: %s", e)
        return []
    out = []
    for c in cs:
        d = om.get(c["id"])
        if d and d.get("tmax") is not None:
            out.append({"nombre": c["nombre"], "region": c["region"], "tmax": round(d["tmax"]), "tmin": round(d["tmin"]),
                        "lluvia": round(d.get("lluvia") or 0), "lluvia_mm": round(d.get("lluvia_mm") or 0, 1),
                        "racha": round(d.get("racha") or 0), "icono": d.get("icono")})
    return out


def obtener_previsiones(hoy: date) -> tuple[list[dict], str]:
    clave_aemet = os.environ.get("AEMET_API_KEY", "")
    clave_google = os.environ.get("GOOGLE_WEATHER_API_KEY", "")
    EXTRA[:] = obtener_extra(hoy)
    try:
        om = openmeteo_todas(CIUDADES, hoy)
    except Exception as e:  # noqa: BLE001
        log.warning("Open-Meteo falló: %s", e)
        om = {}
    if not clave_aemet and not om:
        raise RuntimeError("Sin AEMET_API_KEY y Open-Meteo no responde")
    resultado, fallos = [], []
    for c in CIUDADES:
        ae = go = None
        if clave_aemet:
            try:
                ae = aemet_ciudad(c, clave_aemet, hoy)
            except Exception as e:  # noqa: BLE001
                log.warning("AEMET %s: %s", c["nombre"], e)
            time.sleep(2.5)  # AEMET limita las peticiones por minuto (cada ciudad son 2)
        if clave_google:
            try:
                go = google_ciudad(c, clave_google)
            except Exception as e:  # noqa: BLE001
                log.warning("Google %s: %s", c["nombre"], e)
        try:
            resultado.append(fusionar(c, {"AEMET": ae, "Open-Meteo": om.get(c["id"]), "Google": go}))
        except RuntimeError as e:
            fallos.append(str(e))
    if len(resultado) < len(CIUDADES) * 0.75:
        raise RuntimeError(f"Demasiadas ciudades sin datos: {fallos}")
    usadas = sorted({f for r in resultado for f in r["fuentes"]})
    log.info("Fuentes usadas: %s", ", ".join(usadas))
    texto = aemet_texto_nacional(clave_aemet) if clave_aemet else ""
    return resultado, texto


def previsiones_demo() -> tuple[list[dict], str]:
    """Datos inventados para probar el render sin claves."""
    import random
    random.seed(7)
    base = {"norte": (17, 10, 70, "lluvia"), "interior": (19, 7, 20, "sol_nubes"),
            "mediterraneo": (24, 15, 10, "sol"), "sur": (26, 14, 5, "sol"), "islas": (25, 19, 15, "sol_nubes")}
    res = []
    for c in CIUDADES:
        tx, tn, ll, ic = base[c["region"]]
        if c["nombre"] in ("Bilbao", "Santander"):
            ic = "chubascos"
        if c["nombre"] == "Pamplona":
            ic = "nubes"
        if c["nombre"] == "Zaragoza":
            ic = "nubes"
        if c["nombre"] == "Valladolid":
            ic = "niebla"
        res.append({**{k: c[k] for k in ("id", "nombre", "lat", "lon", "region")},
                    "tmax": tx + random.randint(-2, 3), "tmin": tn + random.randint(-2, 2),
                    "lluvia": max(0, ll + random.randint(-10, 10)), "viento": random.randint(8, 30),
                    "racha": None, "icono": ic, "cielo": None, "fuentes": ["demo"]})
    return res, ""
