"""Agenda económica: datos macro, bancos centrales, inventarios de petróleo (EIA) y reuniones de la UE.

Fuente principal: calendario semanal público de Forex Factory (JSON). Respaldo: fechas oficiales de la
FED y el BCE (config.py) y el informe semanal de la EIA (miércoles, 10:30 de Nueva York).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from .config import BCE, FOMC, ZONA_HORARIA

log = logging.getLogger(__name__)
MAD = ZoneInfo(ZONA_HORARIA)
NY = ZoneInfo("America/New_York")
URL_FF = "https://nfs.faireconomy.media/ff_calendar_{}.json"

# Traducción de los eventos más habituales (los que no estén aquí los traduce Claude)
TRADUCCION = {
    "CPI m/m": "IPC mensual", "CPI y/y": "IPC anual", "Core CPI m/m": "IPC subyacente",
    "CPI Flash Estimate y/y": "IPC adelantado", "Core CPI Flash Estimate y/y": "IPC subyacente adelantado",
    "Flash CPI y/y": "IPC adelantado", "Final CPI y/y": "IPC final",
    "Non-Farm Employment Change": "Empleo no agrícola", "Unemployment Rate": "Tasa de paro",
    "Unemployment Claims": "Peticiones semanales de paro", "Average Hourly Earnings m/m": "Salarios por hora",
    "Crude Oil Inventories": "Inventarios de petróleo (EIA)", "Natural Gas Storage": "Reservas de gas natural",
    "Federal Funds Rate": "Decisión de tipos de la FED", "FOMC Statement": "Comunicado de la FED",
    "FOMC Press Conference": "Rueda de prensa de la FED", "FOMC Meeting Minutes": "Actas de la FED",
    "Beige Book": "Libro Beige de la FED",
    "Main Refinancing Rate": "Decisión de tipos del BCE", "Monetary Policy Statement": "Comunicado del BCE",
    "ECB Press Conference": "Rueda de prensa del BCE", "ECB Monetary Policy Meeting Accounts": "Actas del BCE",
    "Advance GDP q/q": "PIB adelantado", "Prelim GDP q/q": "PIB preliminar", "Final GDP q/q": "PIB final",
    "GDP q/q": "PIB trimestral", "Flash GDP q/q": "PIB adelantado",
    "Retail Sales m/m": "Ventas minoristas", "Core Retail Sales m/m": "Ventas minoristas subyacentes",
    "ISM Manufacturing PMI": "PMI manufacturero ISM", "ISM Services PMI": "PMI de servicios ISM",
    "Flash Manufacturing PMI": "PMI manufacturero adelantado", "Flash Services PMI": "PMI de servicios adelantado",
    "German ifo Business Climate": "Índice Ifo de Alemania", "German ZEW Economic Sentiment": "Índice ZEW de Alemania",
    "ZEW Economic Sentiment": "Índice ZEW", "Core PCE Price Index m/m": "Inflación PCE subyacente",
    "JOLTS Job Openings": "Ofertas de empleo JOLTS", "CB Consumer Confidence": "Confianza del consumidor",
    "Prelim UoM Consumer Sentiment": "Confianza del consumidor de Michigan",
    "Revised UoM Consumer Sentiment": "Confianza del consumidor de Michigan",
    "PPI m/m": "Precios de producción", "Core PPI m/m": "Precios de producción subyacentes",
    "Durable Goods Orders m/m": "Pedidos de bienes duraderos", "Empire State Manufacturing Index": "Índice manufacturero de Nueva York",
    "Philly Fed Manufacturing Index": "Índice manufacturero de Filadelfia",
    "Existing Home Sales": "Venta de viviendas usadas", "New Home Sales": "Venta de viviendas nuevas",
    "Spanish Unemployment Change": "Paro registrado en España", "Spanish Flash CPI y/y": "IPC adelantado de España",
    "Spanish Flash GDP q/q": "PIB adelantado de España", "Spanish Manufacturing PMI": "PMI manufacturero de España",
    "Spanish Services PMI": "PMI de servicios de España",
    "German Prelim CPI m/m": "IPC adelantado de Alemania", "German Flash Manufacturing PMI": "PMI manufacturero de Alemania",
    "ECOFIN Meetings": "Reunión del ECOFIN (ministros de Economía de la UE)",
    "Eurogroup Meetings": "Reunión del Eurogrupo", "EU Economic Summit": "Cumbre de líderes de la UE",
    "BOJ Policy Rate": "Decisión de tipos del Banco de Japón", "Official Bank Rate": "Decisión de tipos del Banco de Inglaterra",
    "OPEC-JMMC Meetings": "Reunión de la OPEP+", "OPEC Meetings": "Reunión de la OPEP",
    "Bank Holiday": "Festivo", "IMF Meetings": "Reuniones del FMI", "G20 Meetings": "Reunión del G20",
    "Chinese GDP q/q": "PIB de China", "GDP q/y": "PIB de China",
}
CLAVES_SIEMPRE = re.compile(r"Crude Oil|Spanish|ECOFIN|Eurogroup|EU Economic|FOMC|ECB|Federal Funds|OPEC|"
                            r"Main Refinancing|Lagarde|Fed Chair", re.I)
PAIS_BANDERA = {"USD": "us", "EUR": "eu", "GBP": "gb", "JPY": "jp", "CNY": "cn", "All": "mundo"}
PREFIJO_BANDERA = {"Spanish": "es", "German": "de", "French": "fr", "Italian": "it"}


def _traducir(titulo: str) -> str | None:
    if titulo in TRADUCCION:
        return TRADUCCION[titulo]
    m = re.match(r"(.+) Speaks$", titulo)
    if m:
        quien = m.group(1).replace("Fed Chair", "presidente de la FED").replace("ECB President", "presidenta del BCE")
        return f"Habla {quien}"
    return None


def _bandera(ev: dict) -> str:
    for pref, b in PREFIJO_BANDERA.items():
        if ev["title"].startswith(pref):
            return b
    return PAIS_BANDERA.get(ev["country"], "mundo")


def _relevante(ev: dict) -> bool:
    if CLAVES_SIEMPRE.search(ev["title"]):
        return True
    if ev["impact"] == "High":
        return ev["country"] in ("USD", "EUR", "GBP", "JPY", "CNY", "All")
    if ev["impact"] == "Medium":
        return ev["country"] in ("USD", "EUR") and ev["title"] in TRADUCCION
    return False


def _semana(cual: str) -> list[dict]:
    r = requests.get(URL_FF.format(cual), timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def _normalizar(ev: dict) -> dict:
    dt_ny = datetime.fromisoformat(ev["date"])
    todo_dia = dt_ny.astimezone(NY).time() == time(0, 0)
    dt = dt_ny.astimezone(MAD)
    return {"titulo": _traducir(ev["title"]) or ev["title"], "original": ev["title"], "traducido": bool(_traducir(ev["title"])),
            "pais": ev["country"], "bandera": _bandera(ev), "impacto": ev["impact"],
            "fecha": (dt_ny.date() if todo_dia else dt.date()).isoformat(),
            "hora": None if todo_dia else dt.strftime("%H:%M"),
            "prevision": ev.get("forecast") or None, "anterior": ev.get("previous") or None}


def _respaldo(desde: date, hasta: date, eia: bool = True) -> list[dict]:
    """Citas fijas por si el calendario no responde: FED, BCE e inventarios EIA."""
    out = []
    for d in FOMC:
        if desde <= d <= hasta:
            h = datetime.combine(d, time(14, 0), NY).astimezone(MAD)
            out.append({"titulo": "Decisión de tipos de la FED", "bandera": "us", "impacto": "High",
                        "fecha": d.isoformat(), "hora": h.strftime("%H:%M"), "pais": "USD"})
    for d in BCE:
        if desde <= d <= hasta:
            out.append({"titulo": "Decisión de tipos del BCE", "bandera": "eu", "impacto": "High",
                        "fecha": d.isoformat(), "hora": "14:15", "pais": "EUR"})
    d = desde
    while eia and d <= hasta:
        if d.weekday() == 2:
            h = datetime.combine(d, time(10, 30), NY).astimezone(MAD)
            out.append({"titulo": "Inventarios de petróleo (EIA)", "bandera": "us", "impacto": "Medium",
                        "fecha": d.isoformat(), "hora": h.strftime("%H:%M"), "pais": "USD"})
        d += timedelta(days=1)
    return out


def proximas_reuniones(hoy: date) -> list[dict]:
    """Próxima reunión de la FED y del BCE (para mencionarlas aunque no sean hoy)."""
    out = []
    for nombre, fechas in (("FED", FOMC), ("BCE", BCE)):
        sig = next((d for d in fechas if d >= hoy), None)
        if sig and (sig - hoy).days <= 21:
            out.append({"banco": nombre, "fecha": sig.isoformat(), "dias": (sig - hoy).days})
    return out


def obtener_agenda(hoy: date, modo: str = "diario") -> dict:
    """modo diario: eventos de hoy. semanal (sábado) / previa (domingo): eventos de la semana siguiente."""
    if modo == "diario":
        desde = hasta = hoy
        semanas = ["thisweek"]
    else:
        desde = hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)  # lunes siguiente
        hasta = desde + timedelta(days=4)
        semanas = ["thisweek", "nextweek"]  # Forex Factory cuenta las semanas de domingo a sábado
    eventos, fuente, fallos = [], "Forex Factory", 0
    for cual in semanas:
        try:
            for ev in _semana(cual):
                if not _relevante(ev):
                    continue
                n = _normalizar(ev)
                if desde.isoformat() <= n["fecha"] <= hasta.isoformat():
                    eventos.append(n)
        except Exception as e:  # noqa: BLE001
            fallos += 1
            log.warning("Calendario %s no disponible: %s", cual, e)
    if not eventos:
        fuente = "calendarios oficiales"
    # Añade las citas fijas que falten (p. ej. si el calendario aún no ha publicado la semana)
    titulos = {(e["fecha"], e["titulo"]) for e in eventos}
    for r in _respaldo(desde, hasta, eia=fallos == len(semanas)):
        if not any(r["fecha"] == f and (r["titulo"] == t or r["titulo"].split()[-1] in t) for f, t in titulos):
            eventos.append(r)
    orden = {"High": 0, "Medium": 1, "Low": 2, "Holiday": 3}
    eventos = [e for e in eventos if e.get("impacto") != "Holiday" or e["bandera"] in ("us", "eu", "es")]
    # Quita duplicados (p. ej. "Comunicado de la FED" y "Decisión de tipos de la FED" el mismo día)
    vistos, unicos = set(), []
    for e in sorted(eventos, key=lambda e: (e["fecha"], e["hora"] or "00:00", orden.get(e.get("impacto"), 3))):
        clave = (e["fecha"], e["hora"], e["bandera"], "FED" if "FED" in e["titulo"] else
                 "BCE" if "BCE" in e["titulo"] else e["titulo"])
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(e)
    # Para la pantalla: lo más importante primero si hay demasiados
    destacados = sorted(unicos, key=lambda e: (orden.get(e.get("impacto"), 3), e["fecha"], e["hora"] or ""))[:6]
    destacados.sort(key=lambda e: (e["fecha"], e["hora"] or "00:00"))
    log.info("Agenda (%s → %s): %d eventos, %d en pantalla", desde, hasta, len(unicos), len(destacados))
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "eventos": unicos, "pantalla": destacados,
            "proximas": proximas_reuniones(hoy), "fuente": fuente}


def agenda_demo(hoy: date, modo: str = "diario") -> dict:
    d = hoy.isoformat()
    ev = [
        {"titulo": "PMI manufacturero adelantado", "bandera": "eu", "impacto": "Medium", "fecha": d, "hora": "10:00"},
        {"titulo": "Peticiones semanales de paro", "bandera": "us", "impacto": "High", "fecha": d, "hora": "14:30"},
        {"titulo": "Inventarios de petróleo (EIA)", "bandera": "us", "impacto": "Medium", "fecha": d, "hora": "16:30"},
        {"titulo": "Reunión del Eurogrupo", "bandera": "eu", "impacto": "Low", "fecha": d, "hora": None},
    ]
    return {"desde": d, "hasta": d, "eventos": ev, "pantalla": ev, "proximas": proximas_reuniones(hoy),
            "fuente": "demo"}
