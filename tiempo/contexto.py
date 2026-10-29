"""Contexto del día para el guion: cambio de hora, inicio de estación, festivos y hora del atardecer."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MAD = ZoneInfo("Europe/Madrid")


def _ultimo_domingo(anio: int, mes: int) -> date:
    d = date(anio, mes + 1, 1) - timedelta(days=1) if mes < 12 else date(anio, 12, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _pascua(anio: int) -> date:
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(anio, mes, dia)


def atardecer(d: date, lat=40.4168, lon=-3.7038) -> str:
    """Hora local (Madrid) de la puesta de sol (fórmula de la NOAA, precisión de ±2 min)."""
    n = d.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                    - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(math.radians(lat)) * math.cos(decl))
                                - math.tan(math.radians(lat)) * math.tan(decl)))
    minutos_utc = 720 - 4 * (lon - ha) - eqt
    t = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=minutos_utc)
    return t.astimezone(MAD).strftime("%H:%M")


FESTIVOS = {(1, 1): "Año Nuevo", (1, 6): "Reyes", (5, 1): "el Día del Trabajo", (8, 15): "la Asunción",
            (10, 12): "la Fiesta Nacional", (11, 1): "Todos los Santos", (12, 6): "el Día de la Constitución",
            (12, 8): "la Inmaculada", (12, 24): "Nochebuena", (12, 25): "Navidad", (12, 31): "Nochevieja"}
# Fechas con plan (no festivas) que dan gancho humano los días de tiempo tranquilo
EVENTOS = {(10, 31): "Halloween", (11, 1): "Todos los Santos (castañas, visitas al cementerio)", (2, 14): "San Valentín",
           (6, 23): "la Noche de San Juan", (12, 22): "el sorteo de la Lotería de Navidad", (1, 7): "el inicio de las rebajas",
           (12, 5): "el puente de diciembre", (3, 19): "San José y las Fallas", (11, 11): "San Martín"}
INICIO_ESTACION = {(3, 20): "la primavera", (6, 21): "el verano", (9, 23): "el otoño", (12, 21): "el invierno"}


def notas(d: date) -> list[str]:
    out = []
    oct_, mar = _ultimo_domingo(d.year, 10), _ultimo_domingo(d.year, 3)
    for cambio, tipo in ((oct_, "invierno"), (mar, "verano")):
        if d == cambio - timedelta(days=1):
            out.append(f"Esta madrugada se cambia la hora (horario de {tipo}): "
                       + ("a las 3 serán las 2, una hora más de sueño." if tipo == "invierno"
                          else "a las 2 serán las 3, una hora menos de sueño."))
        elif d == cambio:
            out.append(f"Esta madrugada se ha cambiado la hora (horario de {tipo}). Hoy anochece en Madrid a las "
                       f"{atardecer(d)}.")
        elif 0 < (d - cambio).days <= 2:
            out.append(f"Primeros días con el horario de {tipo}: " + (
                f"anochece una hora antes, hoy en Madrid a las {atardecer(d)}." if tipo == "invierno"
                else f"anochece una hora más tarde, hoy en Madrid a las {atardecer(d)}."))
    if (d.month, d.day) in INICIO_ESTACION:
        out.append(f"Hoy empieza oficialmente {INICIO_ESTACION[(d.month, d.day)]}.")
    if (d.month, d.day) in FESTIVOS:
        out.append(f"Hoy es {FESTIVOS[(d.month, d.day)]} (festivo).")
    manana = d + timedelta(days=1)
    for dd, cuando in ((d, "Hoy"), (manana, "Mañana")):
        if (dd.month, dd.day) in EVENTOS:
            out.append(f"{cuando} es {EVENTOS[(dd.month, dd.day)]}: buen gancho humano si el tiempo está tranquilo.")
    if manana.weekday() == 5:
        out.append("Mañana empieza el fin de semana: planes, terrazas, excursiones, ropa tendida…")
    if (manana.month, manana.day) in FESTIVOS:
        out.append(f"Mañana es {FESTIVOS[(manana.month, manana.day)]}: si hay planes, el tiempo importa.")
    p = _pascua(d.year)
    if d == p - timedelta(days=2):
        out.append("Hoy es Viernes Santo (festivo).")
    if p - timedelta(days=6) <= d <= p - timedelta(days=3):
        out.append("Es Semana Santa: mucha gente viaja; viene bien el tiempo para procesiones y escapadas.")
    return out
