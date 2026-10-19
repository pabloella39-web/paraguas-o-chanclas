"""Descripción del post pensada para el algoritmo de TikTok.

Estructura (TikTok usa el texto como buscador, así que importan las palabras clave):
  1. Gancho con pregunta al público (provoca comentarios).
  2. Resumen con palabras que la gente busca: "el tiempo hoy", "previsión", nombres de ciudades.
  3. 8-10 hashtags: generales del nicho + según el tiempo del día + ciudades destacadas + estación.
"""
from __future__ import annotations

import random
import re
import unicodedata
from datetime import date

ICONO_EMOJI = {"sol": "☀️", "sol_nubes": "🌤️", "nubes": "☁️", "lluvia": "🌧️", "chubascos": "🌦️",
               "tormenta": "⛈️", "nieve": "❄️", "niebla": "🌫️"}

GANCHOS = [
    "¿Paraguas o chanclas? Te lo digo en 1 minuto 👇",
    "Antes de salir de casa, mira esto 👀",
    "¿Desde qué ciudad nos ves? Te leo en comentarios 👇",
    "Guarda este vídeo antes de vestirte 😏",
    "Etiqueta a quien siempre sale sin chaqueta 🧥",
    "¿Acerté ayer? Dímelo en comentarios 👇",
]

HASHTAGS_FIJOS = ["#eltiempo", "#tiempo", "#prevision", "#españa", "#AEMET", "#parati", "#paraguasochanclas"]


def _sin_tildes(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")


def _hashtag(nombre: str) -> str:
    nombre = nombre.replace("S.C. Tenerife", "Tenerife").replace("Las Palmas", "GranCanaria")
    return "#" + re.sub(r"[^A-Za-z0-9]", "", _sin_tildes(nombre).title())


def _estacion(d: date) -> str:
    m = d.month
    return "#otoño" if m in (9, 10, 11) else "#invierno" if m in (12, 1, 2) else \
        "#primavera" if m in (3, 4, 5) else "#verano"


def construir(prev: list[dict], hoy: date, gancho_ia: str | None = None) -> str:
    rnd = random.Random(hoy.toordinal() * 7)
    caliente = max(prev, key=lambda p: p["tmax"])
    fria = min(prev, key=lambda p: p["tmin"])
    lluvia = sorted([p for p in prev if p["lluvia"] >= 50], key=lambda p: -p["lluvia"])
    tormenta = [p for p in prev if p["icono"] == "tormenta"]
    nieve = [p for p in prev if p["icono"] == "nieve"]
    niebla = [p for p in prev if p["icono"] == "niebla"]

    gancho = (gancho_ia or "").strip() or rnd.choice(GANCHOS)
    gancho = re.sub(r"\s*#\S+", "", gancho).strip()  # los hashtags van al final

    lineas = [f"El tiempo en España hoy, {_dia(hoy)} 🇪🇸"]
    if lluvia:
        nombres = " y ".join(p["nombre"] for p in lluvia[:2])
        lineas.append(f"🌧️ Lluvia en {nombres}")
    if tormenta:
        lineas.append(f"⛈️ Tormentas en {tormenta[0]['nombre']}")
    if nieve:
        lineas.append(f"❄️ Nieve en {nieve[0]['nombre']}")
    if niebla:
        lineas.append(f"🌫️ Niebla en {niebla[0]['nombre']}")
    lineas.append(f"🔥 Máxima: {caliente['tmax']}° en {caliente['nombre']}")
    lineas.append(f"🥶 Mínima: {fria['tmin']}° en {fria['nombre']}")

    tags = list(HASHTAGS_FIJOS)
    if lluvia:
        tags.append("#lluvia")
    if tormenta:
        tags.append("#tormenta")
    if nieve:
        tags.append("#nieve")
    if caliente["tmax"] >= 28:
        tags.append("#calor")
    if fria["tmin"] <= 3:
        tags.append("#frio")
    tags.append(_estacion(hoy))
    # Ciudades destacadas: atraen búsquedas locales ("tiempo Sevilla")
    for p in (lluvia[:1] + [caliente, fria]):
        h = _hashtag(p["nombre"])
        if h not in tags:
            tags.append(h)
    tags = tags[:12]

    texto = f"{gancho}\n\n" + "\n".join(lineas) + "\n\n" + " ".join(tags)
    return texto[:2200]


def _dia(d: date) -> str:
    from .guion import fecha_larga
    return fecha_larga(d)
