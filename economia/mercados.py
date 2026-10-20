"""Cotizaciones: bolsas, materias primas, divisas y criptomonedas.

Fuentes (en orden): Yahoo Finance (gráfico diario de 1 mes) → CNBC (respaldo de cotización e histórico).
Cripto: CoinGecko → Yahoo. Todas son públicas y gratuitas; los datos pueden llevar retraso.
"""
from __future__ import annotations

import logging
import math
import random
import time
from datetime import date, datetime, timedelta, timezone

import requests

from .config import ACTIVOS

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json,text/plain,*/*", "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}


def _sesion_yahoo():
    """Yahoo rechaza (429) las peticiones de servidores salvo que imiten la huella TLS de un navegador."""
    try:
        from curl_cffi import requests as cr
        return cr.Session(impersonate="chrome")
    except ImportError:
        s = requests.Session()
        s.headers.update(UA)
        return s


def _num(txt) -> float | None:
    if txt in (None, "", "UNCH"):
        return None
    try:
        return float(str(txt).replace(",", "").replace("%", "").replace("+", ""))
    except ValueError:
        return None


def _resultado(precio, previo, serie, fecha, fuente, maximo_anual=None):
    if precio is None or not previo:
        raise ValueError("sin precio")
    cambio = (precio / previo - 1) * 100
    semana = None
    if len(serie) >= 6:
        semana = (precio / serie[-6] - 1) * 100
    mes = (precio / serie[0] - 1) * 100 if serie else None
    return {"precio": precio, "previo": previo, "cambio": round(cambio, 2),
            "semana": None if semana is None else round(semana, 2),
            "mes": None if mes is None else round(mes, 2), "serie": [round(v, 6) for v in serie[-23:]],
            "fecha": fecha, "fuente": fuente,
            "cerca_maximos": bool(maximo_anual and precio >= maximo_anual * 0.985)}


def yahoo(sesion, simbolo: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(simbolo)}"
    for intento in range(3):
        r = sesion.get(url, params={"range": "1mo", "interval": "1d"}, timeout=20)
        if r.status_code == 429:
            time.sleep(3 * (intento + 1))
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError("Yahoo 429")
    res = r.json()["chart"]["result"][0]
    meta = res["meta"]
    off = timedelta(seconds=meta.get("gmtoffset", 0))
    barras = [(datetime.fromtimestamp(t, timezone.utc) + off, c)
              for t, c in zip(res.get("timestamp", []), res["indicators"]["quote"][0].get("close", []))
              if c is not None]
    if len(barras) < 2:
        raise ValueError("serie corta")
    precio = meta.get("regularMarketPrice") or barras[-1][1]
    t_precio = (datetime.fromtimestamp(meta.get("regularMarketTime", 0), timezone.utc) + off).date()
    # Si la última barra es la sesión en curso (futuros, Asia), se compara con la anterior
    if barras[-1][0].date() >= t_precio:
        previo, serie = barras[-2][1], [c for _, c in barras[:-1]] + [precio]
    else:
        previo, serie = barras[-1][1], [c for _, c in barras] + [precio]
    return _resultado(precio, previo, serie, t_precio.isoformat(), "Yahoo Finance", meta.get("fiftyTwoWeekHigh"))


def cnbc(simbolos: list[str]) -> dict[str, dict]:
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
           + "%7C".join(requests.utils.quote(s) for s in simbolos)
           + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    out = {}
    for q in r.json()["FormattedQuoteResult"]["FormattedQuote"]:
        precio, previo = _num(q.get("last")), _num(q.get("previous_day_closing"))
        serie = []
        try:
            h = requests.get("https://ts-api.cnbc.com/harmony/app/charts/1M.json", params={"symbol": q["symbol"]},
                             headers=UA, timeout=20).json()
            serie = [float(b["close"]) for b in h["barData"]["priceBars"]][-22:]
        except Exception as e:  # noqa: BLE001
            log.info("CNBC sin histórico para %s: %s", q.get("symbol"), e)
        fecha = (q.get("last_time") or "")[:10] or date.today().isoformat()
        try:
            out[q["symbol"]] = _resultado(precio, previo, serie + ([precio] if serie else []), fecha, "CNBC",
                                          _num(q.get("yrhiprice")))
        except ValueError:
            pass
    return out


def coingecko() -> dict[str, dict]:
    base = "https://api.coingecko.com/api/v3"
    p = requests.get(f"{base}/simple/price", params={"ids": "bitcoin,ethereum", "vs_currencies": "usd",
                                                     "include_24hr_change": "true"}, headers=UA, timeout=20)
    p.raise_for_status()
    p = p.json()
    out = {}
    for clave, cid in (("btc", "bitcoin"), ("eth", "ethereum")):
        precio, cambio = p[cid]["usd"], p[cid]["usd_24h_change"]
        serie = []
        try:
            h = requests.get(f"{base}/coins/{cid}/market_chart", params={"vs_currency": "usd", "days": 30,
                                                                       "interval": "daily"}, headers=UA, timeout=20)
            serie = [v for _, v in h.json()["prices"]]
            time.sleep(1.5)
        except Exception as e:  # noqa: BLE001
            log.info("CoinGecko sin histórico de %s: %s", cid, e)
        previo = precio / (1 + cambio / 100)
        serie = (serie[:-1] + [precio]) if serie else [previo, precio]
        r = _resultado(precio, previo, serie, date.today().isoformat(), "CoinGecko")
        # El "semanal" de cripto es de 7 días naturales (cotiza todos los días)
        if len(serie) >= 8:
            r["semana"] = round((precio / serie[-8] - 1) * 100, 2)
        out[clave] = r
    return out


def obtener_mercados() -> dict[str, dict]:
    datos: dict[str, dict] = {}
    sesion = _sesion_yahoo()
    for clave, nombre, grupo, sy, sc, icono, unidad, dec in ACTIVOS:
        if grupo == "cripto":
            continue
        try:
            datos[clave] = yahoo(sesion, sy)
        except Exception as e:  # noqa: BLE001
            log.warning("Yahoo falló para %s (%s): %s", nombre, sy, e)
        time.sleep(0.4)
    faltan = [a for a in ACTIVOS if a[2] != "cripto" and a[0] not in datos and a[4]]
    if faltan:
        try:
            por_simbolo = cnbc([a[4] for a in faltan])
            for a in faltan:
                if a[4] in por_simbolo:
                    datos[a[0]] = por_simbolo[a[4]]
        except Exception as e:  # noqa: BLE001
            log.warning("CNBC falló: %s", e)
    try:
        datos.update(coingecko())
    except Exception as e:  # noqa: BLE001
        log.warning("CoinGecko falló: %s; se usa Yahoo", e)
        for clave, sy in (("btc", "BTC-USD"), ("eth", "ETH-USD")):
            try:
                datos[clave] = yahoo(sesion, sy)
            except Exception as e2:  # noqa: BLE001
                log.warning("Tampoco Yahoo para %s: %s", clave, e2)
    for clave, *_ in ACTIVOS:
        if clave in datos:
            datos[clave].update(dict(zip(("clave", "nombre", "grupo", "yahoo", "cnbc", "icono", "unidad", "dec"),
                                         next(a for a in ACTIVOS if a[0] == clave))))
    imprescindibles = {"ibex", "sp500", "btc", "oro"}
    if len(imprescindibles & datos.keys()) < 3:
        raise RuntimeError(f"Faltan datos de mercado básicos: solo hay {sorted(datos)}")
    log.info("Mercados: %d activos (%s)", len(datos), ", ".join(f"{k} {v['fuente']}" for k, v in datos.items()))
    return datos


def mercados_demo(hoy: date) -> dict[str, dict]:
    """Datos inventados (aproximados a octubre de 2026) para probar el vídeo sin conexión."""
    base = {"ibex": 19215.9, "stoxx": 5712.4, "dax": 24410.2, "sp500": 6842.7, "nasdaq": 23120.5, "dow": 46210.3,
            "nikkei": 48120.0, "oro": 4161.4, "plata": 48.62, "brent": 66.84, "wti": 62.91, "gas": 31.45,
            "eurusd": 1.1215, "btc": 83146.0, "eth": 2464.9}
    rnd = random.Random(hoy.toordinal())
    out = {}
    for a in ACTIVOS:
        clave = a[0]
        p = base[clave]
        vol = 0.025 if a[2] == "cripto" else 0.009
        serie = [p]
        for _ in range(22):
            serie.insert(0, serie[0] / (1 + rnd.gauss(0.0006, vol)))
        serie = [s * (1 + 0.004 * math.sin(i / 3)) for i, s in enumerate(serie)]
        serie[-1] = p
        r = _resultado(p, serie[-2], serie, (hoy - timedelta(days=1)).isoformat(), "demo")
        r.update(dict(zip(("clave", "nombre", "grupo", "yahoo", "cnbc", "icono", "unidad", "dec"), a)))
        out[clave] = r
    return out
