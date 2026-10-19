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

# Palabras objetivo por bloque (≈170 palabras ≈ 63 s a ritmo ágil; la velocidad de la voz se ajusta sola)
PALABRAS = {"intro": 12, "general": 26, "norte": 24, "interior": 22, "mediterraneo": 22,
            "sur": 22, "islas": 22, "cierre": 18}


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
icono: sol, sol_nubes, nubes, lluvia, chubascos, tormenta, nieve, niebla). Fuentes: AEMET (oficial) y Open-Meteo (consenso de varios modelos: europeo, alemán, francés y americano).
{datos}

Texto de AEMET para hoy (contexto, puede venir vacío):
{texto_aemet}

Hoy la locución la lee {presenta}: usa la concordancia de género correcta si hablas de ti.

INTERACCIÓN CON EL PÚBLICO (muy importante, es lo que hace crecer el canal):
- Habla de tú al espectador todo el rato ("si hoy sales a correr...", "tú que estás en Málaga...").
- En la intro, un gancho directo que obligue a quedarse o a responder (una pregunta o un reto).
- En al menos dos bloques regionales, interpela a la gente de una ciudad concreta ("Si eres de Bilbao,
  hoy...", "Gente de Sevilla, ...").
- En el cierre, una pregunta concreta para que comenten (varía cada día: ¿paraguas o chanclas?, ¿desde
  qué ciudad nos ves?, ¿qué plan tienes con este tiempo?, ¿acerté ayer?...) y pide que sigan la cuenta.
  De vez en cuando, que etiqueten a alguien ("etiqueta a ese amigo que siempre va en manga corta").

Escribe la locución en castellano de España, para leer en voz alta por una voz sintética:
- Escribe los números en cifras seguidos de la palabra "grados" o "por ciento" (ej. "24 grados"). Nada de
  símbolos (°, %), emojis, abreviaturas ni siglas raras. "AEMET" se puede decir.
- Ritmo ágil y conversacional, como un presentador joven: frases que fluyan, conectadas con "y", "mientras
  que", "eso sí". NUNCA enumeres ciudades con dos puntos ni listas largas de números; agrúpalas
  ("Bilbao y Santander rondarán los 16 grados") y destaca solo lo interesante. Evita paréntesis y guiones.
- Menciona las ciudades por su nombre (S.C. Tenerife = Santa Cruz de Tenerife).
- Un chiste o comentario gracioso por bloque como mucho; que el dato vaya primero.
- Si una ciudad tiene "discrepancia_tmax" de 3 o más, puedes bromear con que AEMET y los modelos no se ponen de acuerdo.
- Longitud EXACTA aproximada por bloque (palabras): {palabras}. Total ≈ {total} palabras. Es crucial respetarlo.

Bloques:
- intro: saludo con la fecha y gancho para que no deslicen el vídeo.
- general: resumen de España en una frase o dos (lo más destacado del día).
- norte, interior, mediterraneo, sur, islas: el tiempo de esas ciudades (islas = Baleares y Canarias).
- cierre: despedida graciosa + pide que sigan "Paraguas o Chanclas" para el parte de mañana a las 7 y media.
  Si encaja, termina diciendo si hoy toca paraguas o chanclas.

Además escribe "caption": UNA sola frase gancho para la descripción del post (máx. 90 caracteres), que
interpele al público con una pregunta o reto relacionado con el tiempo de hoy, con 1 o 2 emojis y SIN
hashtags (los hashtags y el resumen se añaden automáticamente).

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


def escribir_guion(prev: list[dict], hoy: date, texto_aemet: str = "", factor: float = 1.0,
                   presenta: str = "un presentador") -> dict:
    """factor < 1 pide un guion más corto; > 1 más largo (para ajustar la duración)."""
    palabras = {k: max(6, round(v * factor)) for k, v in PALABRAS.items()}
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if clave:
        prompt = PROMPT.format(fecha=fecha_larga(hoy), datos=json.dumps(_resumen_datos(prev), ensure_ascii=False),
                               texto_aemet=texto_aemet[:2500] or "(vacío)",
                               palabras=json.dumps(palabras), total=sum(palabras.values()), presenta=presenta)
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


def _nombre(p):
    return p["nombre"].replace("S.C. Tenerife", "Santa Cruz de Tenerife")


def _frase_ciudades(lista):
    """'máximas entre los 15 grados de Oviedo y los 18 de Pamplona' en vez de enumerar todas."""
    lista = sorted(lista, key=lambda p: p["tmax"])
    lo, hi = lista[0], lista[-1]
    if lo["tmax"] == hi["tmax"]:
        return f"máximas de {hi['tmax']} grados"
    return f"máximas entre los {lo['tmax']} grados de {_nombre(lo)} y los {hi['tmax']} de {_nombre(hi)}"


def _aludir(p, rnd) -> str:
    """Frase dirigida a la gente de una ciudad concreta, según su tiempo."""
    n = _nombre(p)
    if p["lluvia"] >= 50:
        return rnd.choice([f"Si eres de {n}, ni se te ocurra salir sin paraguas.",
                           f"Gente de {n}, hoy toca chubasquero."])
    if p["tmax"] >= 25:
        return rnd.choice([f"Si eres de {n}, hoy las chanclas están justificadas.",
                           f"Gente de {n}, día de terraza, ¿o no?"])
    if p["tmin"] <= 8:
        return rnd.choice([f"Si eres de {n}, por la mañana abrígate bien.",
                           f"Gente de {n}, chaqueta a primera hora."])
    return rnd.choice([f"Si eres de {n}, día tranquilo para lo que tengas en mente.",
                       f"Gente de {n}, hoy el tiempo no os pone excusas."])


CIELO = {"sol": "cielo despejado", "sol_nubes": "sol con alguna nube", "nubes": "cielo nuboso",
         "lluvia": "lluvia", "chubascos": "chubascos a ratos", "tormenta": "posibles tormentas",
         "nieve": "nieve", "niebla": "nieblas por la mañana"}


def guion_plantilla(prev: list[dict], hoy: date, factor: float = 1.0) -> dict:
    """Guion sin IA (respaldo). factor < 0.85 quita los comentarios; > 1.1 añade uno al cierre."""
    rnd = random.Random(hoy.toordinal())
    reg = _resumen_datos(prev)
    caliente = max(prev, key=lambda p: p["tmax"])
    fria = min(prev, key=lambda p: p["tmin"])
    lluviosas = [_nombre(p) for p in prev if p["lluvia"] >= 50]
    # Con factor 1 hay comentario en 3 regiones; si hay que alargar, en todas; si acortar, en ninguna
    con_chiste = {"norte", "mediterraneo", "islas"}
    con_alusion = {"interior", "sur"}
    if factor > 1.1:
        con_chiste = {"norte", "interior", "mediterraneo", "sur", "islas"}
    elif factor < 0.9:
        con_chiste = {"norte"}
    seg = {
        "intro": rnd.choice([
            f"¡Buenos días! Es {fecha_larga(hoy)}. Quédate hasta el final, que hoy te toca elegir: ¿paraguas o chanclas?",
            f"¡Buenos días! Es {fecha_larga(hoy)}. Antes de salir de casa, mira esto, que te ahorro un disgusto.",
            f"¡Buenos días! Es {fecha_larga(hoy)}. Dime desde dónde nos ves, que hoy hay de todo en España.",
        ]),
        "general": (f"Lo más caluroso, {_nombre(caliente)} con {caliente['tmax']} grados, y lo más frío al "
                    f"amanecer, {_nombre(fria)} con {fria['tmin']}. "
                    + (f"Ojo con la lluvia en {' y '.join(lluviosas[:2])}." if lluviosas
                       else "De lluvia, poca cosa.")),
    }
    intros = {"norte": "Empezamos por el norte", "interior": "En el interior",
              "mediterraneo": "En el Mediterráneo", "sur": "En el sur", "islas": "Y en las islas"}
    for r in ("norte", "interior", "mediterraneo", "sur", "islas"):
        lista = reg.get(r, [])
        if not lista:
            seg[r] = ""
            continue
        dom = _icono_dominante(lista)
        chiste = f" {rnd.choice(FRASES[dom])}" if r in con_chiste else ""
        aviso = " Lluvia muy probable." if max(p["lluvia"] for p in lista) >= 50 and dom not in (
            "lluvia", "chubascos", "tormenta") else ""
        alusion = ""
        if r in con_alusion:
            ciudad = max(lista, key=lambda p: (p["lluvia"], p["tmax"]))
            alusion = " " + _aludir(ciudad, rnd)
        seg[r] = f"{intros[r]}, {CIELO[dom]} y {_frase_ciudades(lista)}.{chiste}{alusion}{aviso}"
    pregunta = rnd.choice([
        "Y tú, ¿hoy eres de paraguas o de chanclas? Te leo en comentarios.",
        "¿Desde qué ciudad nos ves? Dímelo en comentarios.",
        "¿Qué plan tienes con este tiempo? Cuéntamelo abajo.",
        "Etiqueta a ese amigo que siempre sale en manga corta.",
    ])
    seg["cierre"] = (f"{pregunta} Y sigue a Paraguas o Chanclas, que mañana a las siete y media "
                     "vuelvo con el parte.")
    if factor > 1.2:
        seg["cierre"] += " ¡Pásaselo a quien siempre sale sin chaqueta!"
    caption = (f"El tiempo en España hoy, {fecha_larga(hoy)} ☀️🌧️ ¿Tú hoy eres de paraguas o de chanclas? 👇 "
               "#eltiempo #AEMET #meteo #tiempoespaña #paraguasochanclas")
    return {"segmentos": seg, "caption": caption}
