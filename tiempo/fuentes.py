"""Descarga y fusión de datos: AEMET OpenData + Google Weather API."""
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
def _aemet_get(ruta: str, clave: str, intentos: int = 4):
    """AEMET responde en dos pasos: una URL de 'datos' y luego el contenido (ISO-8859-15)."""
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(f"{AEMET_BASE}{ruta}", headers={"api_key": clave, "cache-control": "no-cache"},
                             timeout=30)
            meta = r.json()
            if meta.get("estado") == 429 or r.status_code == 429:
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
    return {
        "tmax": int(dia["temperatura"]["maxima"]),
        "tmin": int(dia["temperatura"]["minima"]),
        "lluvia": int(prob["value"]) if prob else (max(probs) if probs else 0),
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


# ---------------------------------------------------------------- Fusión
def _media(a, b):
    vals = [v for v in (a, b) if v is not None]
    return round(sum(vals) / len(vals)) if vals else None


def fusionar(ciudad: dict, ae: dict | None, go: dict | None) -> dict:
    ae, go = ae or {}, go or {}
    if not ae and not go:
        raise RuntimeError(f"Sin datos para {ciudad['nombre']}")
    icono = ae.get("icono") or go.get("icono") or SOL_NUBES
    # Si Google ve tormenta probable y AEMET solo lluvia, se respeta la oficial (AEMET)
    res = {
        **{k: ciudad[k] for k in ("id", "nombre", "lat", "lon", "region")},
        "tmax": _media(ae.get("tmax"), go.get("tmax")),
        "tmin": _media(ae.get("tmin"), go.get("tmin")),
        "lluvia": _media(ae.get("lluvia"), go.get("lluvia")) or 0,
        "viento": _media(ae.get("viento"), go.get("viento")),
        "racha": go.get("racha"),
        "icono": icono,
        "cielo": ae.get("cielo") or go.get("cielo"),
        "fuentes": [n for n, d in (("AEMET", ae), ("Google", go)) if d],
    }
    if ae.get("tmax") is not None and go.get("tmax") is not None:
        res["discrepancia_tmax"] = round(abs(ae["tmax"] - go["tmax"]))
    return res


def obtener_previsiones(hoy: date) -> tuple[list[dict], str]:
    clave_aemet = os.environ.get("AEMET_API_KEY", "")
    clave_google = os.environ.get("GOOGLE_WEATHER_API_KEY", "")
    if not clave_aemet and not clave_google:
        raise RuntimeError("Faltan AEMET_API_KEY y GOOGLE_WEATHER_API_KEY")
    resultado, fallos = [], []
    for c in CIUDADES:
        ae = go = None
        if clave_aemet:
            try:
                ae = aemet_ciudad(c, clave_aemet, hoy)
            except Exception as e:  # noqa: BLE001
                log.warning("AEMET %s: %s", c["nombre"], e)
            time.sleep(1.2)  # AEMET limita las peticiones por minuto
        if clave_google:
            try:
                go = google_ciudad(c, clave_google)
            except Exception as e:  # noqa: BLE001
                log.warning("Google %s: %s", c["nombre"], e)
        try:
            resultado.append(fusionar(c, ae, go))
        except RuntimeError as e:
            fallos.append(str(e))
    if len(resultado) < len(CIUDADES) * 0.75:
        raise RuntimeError(f"Demasiadas ciudades sin datos: {fallos}")
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
