"""Estación del año (astronómica, aproximada) para la música y los adornos del vídeo."""
from __future__ import annotations

from datetime import date

NOMBRES = {"primavera": "PRIMAVERA", "verano": "VERANO", "otono": "OTOÑO", "invierno": "INVIERNO"}


def estacion(d: date) -> str:
    md = (d.month, d.day)
    if (3, 20) <= md < (6, 21):
        return "primavera"
    if (6, 21) <= md < (9, 23):
        return "verano"
    if (9, 23) <= md < (12, 21):
        return "otono"
    return "invierno"
