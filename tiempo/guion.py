"""Guion del parte con humor ligero: Claude (si hay clave) o plantilla local."""
from __future__ import annotations

import json
import logging
import os
import random
import re
from datetime import date

import requests

from .config import MODELO_CLAUDE, SEGMENTOS

log = logging.getLogger(__name__)

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]

# Palabras objetivo por bloque (≈170 palabras ≈ 62 s de locución)
PALABRAS = {"intro": 14, "general": 30, "norte": 24, "interior": 22, "mediterraneo": 22,
            "sur": 22, "islas": 20, "cierre": 16}


def fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _resumen_datos(prev: list[dict]) -> dict:
    por_region = {}
    for p in prev:
        por_region.setdefault(p["region"], []).append(
            {k: p.get(k) for k in ("nombre", "tmax", "tmin", "lluvia", "viento", "racha", "icono", "cielo",
                                   "discrepancia_tmax")})
    return por_region


# ---------------------------------------------------------------- Claude
PROMPT = """Eres el guionista de "Paraguas o Chanclas" (@paraguasochanclas), un canal de TikTok sobre el tiempo en España con HUMOR LIGERO: cercano,
ingenioso, con chascarrillos y comparaciones cotidianas muy españolas, pero SIN palabrotas, sin insultos,
sin política y sin burlarte de nadie. La información meteorológica debe ser exacta: usa SOLO los datos
que te doy (no inventes temperaturas, lluvias ni avisos).

Hoy es {fecha}. Datos por región (temperaturas en grados, lluvia = probabilidad en %, viento en km/h;
icono: sol, sol_nubes, nubes, lluvia, chubascos, tormenta, nieve, niebla). Fuentes: AEMET y Google.
{datos}

Texto de AEMET para hoy (contexto, puede venir vacío):
{texto_aemet}

Escribe la locución en castellano de España, para leer en voz alta por una voz sintética:
- Escribe los números en cifras seguidos de la palabra "grados" o "por ciento" (ej. "24 grados"). Nada de
  símbolos (°, %), emojis, abreviaturas ni siglas raras. "AEMET" se puede decir.
- Frases cortas y naturales. Menciona las ciudades por su nombre (S.C. Tenerife = Santa Cruz de Tenerife).
- Un chiste o comentario gracioso por bloque como mucho; que el dato vaya primero.
- Si una ciudad tiene "discrepancia_tmax" de 3 o más, puedes bromear con que AEMET y Google no se ponen de acuerdo.
- Longitud EXACTA aproximada por bloque (palabras): {palabras}. Total ≈ {total} palabras. Es crucial respetarlo.

Bloques:
- intro: saludo con la fecha y gancho para que no deslicen el vídeo.
- general: resumen de España en una frase o dos (lo más destacado del día).
- norte, interior, mediterraneo, sur, islas: el tiempo de esas ciudades (islas = Baleares y Canarias).
- cierre: despedida graciosa + pide que sigan "Paraguas o Chanclas" para el parte de mañana a las 7 y media.
  Si encaja, termina diciendo si hoy toca paraguas o chanclas.

Además escribe "caption": el texto del post de TikTok (máx. 150 caracteres + 5 hashtags en español,
incluye #eltiempo y #AEMET; puedes usar 1 o 2 emojis aquí).

Responde SOLO con JSON válido con esta forma:
{{"segmentos": {{"intro": "...", "general": "...", "norte": "...", "interior": "...", "mediterraneo": "...",
"sur": "...", "islas": "...", "cierre": "..."}}, "caption": "..."}}"""


def _claude(prompt: str, clave: str) -> dict:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.environ.get("CLAUDE_MODEL", MODELO_CLAUDE), "max_tokens": 2000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    r.raise_for_status()
    texto = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ValueError("Claude no devolvió JSON")
    data = json.loads(m.group(0))
    if set(data["segmentos"]) < set(SEGMENTOS) or not data.get("caption"):
        raise ValueError("JSON incompleto")
    return data


def escribir_guion(prev: list[dict], hoy: date, texto_aemet: str = "", factor: float = 1.0) -> dict:
    """factor < 1 pide un guion más corto; > 1 más largo (para ajustar la duración)."""
    palabras = {k: max(6, round(v * factor)) for k, v in PALABRAS.items()}
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if clave:
        prompt = PROMPT.format(fecha=fecha_larga(hoy), datos=json.dumps(_resumen_datos(prev), ensure_ascii=False),
                               texto_aemet=texto_aemet[:2500] or "(vacío)",
                               palabras=json.dumps(palabras), total=sum(palabras.values()))
        for intento in range(2):
            try:
                g = _claude(prompt, clave)
                g["origen"] = "claude"
                return g
            except Exception as e:  # noqa: BLE001
                log.warning("Guion con Claude falló (intento %d): %s", intento + 1, e)
    g = guion_plantilla(prev, hoy, factor)
    g["origen"] = "plantilla"
    return g


# ---------------------------------------------------------------- Plantilla (sin IA)
FRASES = {
    "sol": ["Gafas de sol obligatorias.", "Día de terraza, sin excusas.", "El sol hace horas extra."],
    "sol_nubes": ["Nubes y claros, indeciso como tú eligiendo serie.", "Alguna nube despistada, poco más."],
    "nubes": ["Cielo gris, de mantita y sofá.", "El sol se ha cogido el día libre."],
    "lluvia": ["El paraguas, de copiloto.", "Hoy no tiendas la ropa."],
    "chubascos": ["Chaparrones de ahora sí, ahora no.", "Paraguas aunque parezca que no."],
    "tormenta": ["El cielo viene con efectos especiales.", "Mejor planes bajo techo."],
    "nieve": ["Abrigo de los gordos.", "Guantes, bufanda y paciencia."],
    "niebla": ["Niebla de película de misterio.", "Al volante, con calma."],
}


def _icono_dominante(lista):
    cuenta = {}
    for p in lista:
        cuenta[p["icono"]] = cuenta.get(p["icono"], 0) + 1
    return max(cuenta, key=cuenta.get)


def _ciudades_txt(lista):
    partes = [f"{p['nombre'].replace('S.C. Tenerife', 'Santa Cruz de Tenerife')} {p['tmax']}" for p in lista]
    return ", ".join(partes[:-1]) + f" y {partes[-1]} grados" if len(partes) > 1 else f"{partes[0]} grados"


def guion_plantilla(prev: list[dict], hoy: date, factor: float = 1.0) -> dict:
    """Guion sin IA (respaldo). factor < 1 quita chistes; factor > 1 añade alguno."""
    rnd = random.Random(hoy.toordinal())
    reg = _resumen_datos(prev)
    caliente = max(prev, key=lambda p: p["tmax"])
    fria = min(prev, key=lambda p: p["tmin"])
    con_chiste = {"norte", "mediterraneo", "islas"} if factor < 0.92 else (
        {"norte", "interior", "mediterraneo", "sur", "islas"})
    if factor < 0.8:
        con_chiste = set()
    seg = {
        "intro": f"Buenos días, es {fecha_larga(hoy)} y este es el tiempo en España.",
        "general": (f"Lo más caluroso hoy, {caliente['nombre']} con {caliente['tmax']} grados. "
                    f"Lo más frío al amanecer, {fria['nombre']} con {fria['tmin']}."),
    }
    nombres = {"norte": "En el norte", "interior": "En el interior", "mediterraneo": "En el Mediterráneo",
               "sur": "En el sur", "islas": "En las islas"}
    for r in ("norte", "interior", "mediterraneo", "sur", "islas"):
        lista = reg.get(r, [])
        if not lista:
            seg[r] = ""
            continue
        chiste = f" {rnd.choice(FRASES[_icono_dominante(lista)])}" if r in con_chiste else ""
        lluvia = " Ojo, que puede llover." if max(p["lluvia"] for p in lista) >= 50 else ""
        seg[r] = f"{nombres[r]}.{chiste} Máximas: {_ciudades_txt(lista)}.{lluvia}"
    seg["cierre"] = "Esto es todo. Sigue a Paraguas o Chanclas y mañana a las 7 y media, otro parte."
    if factor > 1.08:
        seg["cierre"] += " Y pásaselo a quien siempre sale sin chaqueta."
    caption = f"¿Paraguas o chanclas? El tiempo en España hoy, {fecha_larga(hoy)} ☀️🌧️ #eltiempo #AEMET #meteo #tiempoespaña #paraguasochanclas"
    return {"segmentos": seg, "caption": caption}
