"""Descripción del post (TikTok la usa como buscador: palabras clave + hashtags)."""
from __future__ import annotations

import random
import re
from datetime import date

from .config import AVISO
from .guion import fecha_larga, fpct, precio_pantalla

GANCHOS = [
    "¿Toro u oso? Te leo en comentarios 👇",
    "Lo que mueve tu dinero hoy, en 1 minuto ☕",
    "Antes de que abra la bolsa, mira esto 👀",
    "Guárdalo y míralo con el café ☕",
    "¿Lo has visto venir? Dímelo en comentarios 👇",
]
FIJOS = ["#economia", "#bolsa", "#finanzas", "#ibex35", "#bitcoin", "#parati", "#torouoso"]


def _flecha(x):
    return "🟢" if (x or 0) >= 0 else "🔴"


def construir(merc: dict, agenda: dict, hoy: date, modo: str, gancho_ia: str | None = None) -> str:
    rnd = random.Random(hoy.toordinal() * 11)
    gancho = re.sub(r"\s*#\S+", "", (gancho_ia or "").strip()).strip() or rnd.choice(GANCHOS)
    sem = modo != "diario"
    titulo = {"diario": f"Resumen económico de hoy, {fecha_larga(hoy)} 📊",
              "semanal": f"La semana en los mercados, {fecha_larga(hoy)} 📊",
              "previa": f"Lo que viene esta semana en los mercados 📅"}[modo]
    lineas = [titulo]
    for k, etq in (("ibex", "IBEX 35"), ("sp500", "S&P 500"), ("btc", "Bitcoin"), ("oro", "Oro"), ("brent", "Brent")):
        if k in merc:
            a = merc[k]
            x = a.get("semana") if sem else a["cambio"]
            lineas.append(f"{_flecha(x)} {etq}: {precio_pantalla(a)} ({fpct(x)})")
    destacados = [e for e in agenda.get("pantalla", []) if e.get("impacto") == "High"][:2]
    for e in destacados:
        lineas.append(f"📅 {(e['hora'] + ' ') if e.get('hora') and not sem else ''}{e['titulo']}")
    lineas.append(f"⚠️ {AVISO}.")

    tags = list(FIJOS)
    texto_agenda = " ".join(e["titulo"] for e in agenda.get("eventos", []))
    if "FED" in texto_agenda or any(p["banco"] == "FED" and p["dias"] <= 2 for p in agenda.get("proximas", [])):
        tags.append("#fed")
    if "BCE" in texto_agenda or any(p["banco"] == "BCE" and p["dias"] <= 2 for p in agenda.get("proximas", [])):
        tags.append("#bce")
    if "petróleo" in texto_agenda.lower():
        tags.append("#petroleo")
    if "oro" in merc and abs(merc["oro"].get("semana" if sem else "cambio") or 0) >= 1:
        tags.append("#oro")
    if "IPC" in texto_agenda:
        tags.append("#inflacion")
    tags += ["#cripto", "#inversion", "#noticias"]
    vistos, unicos = set(), []
    for t in tags:
        if t not in vistos:
            vistos.add(t)
            unicos.append(t)
    return (f"{gancho}\n\n" + "\n".join(lineas) + "\n\n" + " ".join(unicos[:12]))[:2200]
