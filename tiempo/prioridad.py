"""Orden de las regiones en el parte: primero lo más relevante del día (DANA, temporal, calor extremo...).

Cada región suma puntos por lluvia probable, tormentas, nieve, viento, calor o frío extremos y por las
menciones con palabras de alerta en el texto de AEMET. En días tranquilos, un pequeño factor aleatorio
(distinto cada día) hace que el orden también varíe.
"""
from __future__ import annotations

import random
import re
from datetime import date

REGIONES = ["norte", "interior", "mediterraneo", "sur", "islas"]
CLAVES_AEMET = {
    "norte": r"Galicia|Asturias|Cant[aá]br|Pa[ií]s Vasco|Euskadi|Navarra|Rioja|Pirineo occidental",
    "interior": r"Castilla|Madrid|Arag[oó]n|Ebro|meseta|Sistema Central|Ib[eé]rico",
    "mediterraneo": r"Catalu|Valencia|Valenciana|Castell[oó]n|Alicante|Murcia|Mediterr[aá]neo|Pirineo oriental",
    "sur": r"Andaluc|Extremadura|Estrecho|Guadalquivir|Ceuta|Melilla|Alborán|C[aá]diz|M[aá]laga|Almer[ií]a",
    "islas": r"Baleares|Balear|Mallorca|Menorca|Ibiza|Canarias|Canario",
}
ALERTA = r"tormenta|fuerte|intens|aviso|temporal|dana|granizo|ola de calor|calor|nieve|nevada|rachas|torrencial|" \
         r"inundaci|alerta|adversos|muy alt|heladas"


def _puntos(lista: list[dict], texto_aemet: str, region: str) -> tuple[float, list[str]]:
    p, motivos = 0.0, []
    lluvia = max(c["lluvia"] for c in lista)
    if lluvia >= 40:
        p += (lluvia - 30) / 7
        motivos.append(f"lluvia probable ({lluvia} %)")
    tormentas = [c["nombre"] for c in lista if c["icono"] == "tormenta"]
    if tormentas:
        p += 6 + 2 * len(tormentas)
        motivos.append("tormentas en " + ", ".join(tormentas[:2]))
    nieve = [c["nombre"] for c in lista if c["icono"] == "nieve"]
    if nieve:
        p += 7
        motivos.append("nieve en " + ", ".join(nieve[:2]))
    racha = max((c.get("racha") or c.get("viento") or 0) for c in lista)
    if racha >= 50:
        p += (racha - 40) / 5
        motivos.append(f"viento fuerte (rachas de {racha} km/h)")
    tmax = max(c["tmax"] for c in lista)
    if tmax >= 30:
        p += (tmax - 28) * 1.3
        motivos.append(f"calor ({tmax} grados)")
    tmin = min(c["tmin"] for c in lista)
    if tmin <= 2:
        p += (3 - tmin) * 1.2
        motivos.append(f"frío ({tmin} grados de mínima)")
    # Frases del texto de AEMET que nombran la zona junto a palabras de alerta
    n = 0
    for frase in re.split(r"(?<=[.;])\s+", texto_aemet or ""):
        if re.search(CLAVES_AEMET[region], frase, re.I) and re.search(ALERTA, frase, re.I):
            n += 1
    if n:
        p += min(12, 4 * n)
        motivos.append("aviso o fenómeno destacado según AEMET")
    return p, motivos


def orden_regiones(prev: list[dict], texto_aemet: str, hoy: date) -> tuple[list[str], dict]:
    rnd = random.Random(hoy.toordinal() * 13)
    por_region = {}
    for c in prev:
        por_region.setdefault(c["region"], []).append(c)
    puntos, motivos = {}, {}
    for r in REGIONES:
        if r not in por_region:
            continue
        p, m = _puntos(por_region[r], texto_aemet, r)
        puntos[r] = p + rnd.uniform(0, 2.5)  # variedad en días tranquilos
        motivos[r] = m
    orden = sorted(puntos, key=lambda r: -puntos[r])
    return orden, {r: {"puntos": round(puntos[r], 1), "motivos": motivos[r]} for r in orden}
