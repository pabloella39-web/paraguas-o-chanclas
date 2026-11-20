"""Variedad de ganchos y formato de los días tranquilos (15-nov-2026).

Los partes del 12 al 14 de noviembre repitieron la misma fórmula tres días («… partido en dos: ¿paraguas o
chanclas?») sin un solo dato concreto y se quedaron en 1.700-9.400 visualizaciones. Aquí se le da al guionista lo
que ya se ha usado, para que no lo repita, y, cuando no hay tiempo adverso, los datos llamativos del día para que
el vídeo gire en torno a UNO de ellos."""
from __future__ import annotations

import json
import re

from .config import RAIZ

FUERTES = ("ALERTA POR TORMENTAS", "ATENCIÓN: NIEVE", "RACHAS FUERTES", "OJO A LA LLUVIA", "CALOR FUERTE")


def recientes(n: int = 5) -> list[dict]:
    """Los últimos vídeos (partes y especiales, no avisos): primera frase, primera línea del texto y titular."""
    fichas = []
    for ruta in list((RAIZ / "historial").glob("20*.json")) + [
            p for p in (RAIZ / "historial_especiales").glob("*.json")
            if p.name.split("-")[0] in ("semana", "resto", "finde") and "anterior" not in p.name]:
        try:
            d = json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        guion = d.get("guion") or {}
        intro = guion.get("intro") or guion.get("gancho") or next(iter(guion.values()), "") if isinstance(guion, dict) else ""
        fichas.append({"orden": ruta.stat().st_mtime,
                       "frase": re.split(r"(?<=[.!?…])\s", str(intro).strip())[0][:120],
                       "texto": (d.get("caption") or "").split("\n")[0][:120],
                       "titular": str(d.get("titular") or "")[:60]})
    fichas.sort(key=lambda f: f["orden"])
    return fichas[-n:]


def nota() -> str:
    """Bloque para el prompt: lo ya usado y la regla de no repetirlo."""
    try:
        rec = recientes()
    except Exception:  # noqa: BLE001
        rec = []
    if not rec:
        return ""
    lista = "\n".join(f"  · frase: «{f['frase']}» | texto del post: «{f['texto']}» | titular: «{f['titular']}»"
                      for f in rec)
    return ("\n\nGANCHOS YA USADOS en los últimos vídeos (del más antiguo al más reciente):\n" + lista +
            "\nREGLA DE VARIEDAD (obligatoria): la primera frase, el titular y la PRIMERA LÍNEA del texto del post "
            "de hoy no pueden parecerse a ninguno de esos: ni la misma estructura, ni las mismas palabras clave, ni "
            "la misma pregunta. Prohibidas las fórmulas gastadas: «partido en dos», «media España» + «la otra media» y, sobre "
            "todo, la PREGUNTA DE ELEGIR ENTRE DOS COSAS («¿abrigo o manga corta?», «¿paraguas o chanclas?», «¿terraza "
            "o sofá?», «¿qué plan tienes?»): ni en la primera frase ni en la primera línea del texto del post, que son "
            "AFIRMACIONES con el dato. Esa pregunta solo puede ir en el cierre del vídeo. Cada una de las tres lleva un DATO CONCRETO "
            "de hoy (un sitio + una cifra, una hora o un día): nada de frases que valdrían para cualquier día.\n")


def dia_tranquilo(prev: list[dict], fen: dict, cuando: str = "mañana") -> str:
    """Si no hay tiempo adverso, los datos llamativos del día para que el vídeo gire en torno a uno."""
    if fen.get("nivel") or fen.get("insignia") in FUERTES:
        return ""
    c = [x for x in prev if isinstance(x.get("tmax"), (int, float)) and isinstance(x.get("tmin"), (int, float))]
    if len(c) < 5:
        return ""
    frio, calor = min(c, key=lambda x: x["tmin"]), max(c, key=lambda x: x["tmax"])
    salto = max(c, key=lambda x: x["tmax"] - x["tmin"])
    fresca = min(c, key=lambda x: x["tmax"])
    mojadas = [x["nombre"] for x in c if (x.get("lluvia") or 0) >= 50]
    secas = [x["nombre"] for x in c if (x.get("lluvia") or 0) <= 10]
    datos = [
        f"{calor['tmax'] - fresca['tmax']} grados de diferencia en la máxima entre {calor['nombre']} "
        f"({calor['tmax']}) y {fresca['nombre']} ({fresca['tmax']})",
        f"la mínima más baja: {frio['tmin']} grados en {frio['nombre']}",
        f"el mayor salto entre la madrugada y la tarde: {salto['tmax'] - salto['tmin']} grados en {salto['nombre']} "
        f"(de {salto['tmin']} a {salto['tmax']})",
        f"{len(mojadas)} de {len(c)} ciudades con paraguas" + (f" ({', '.join(mojadas[:5])})" if mojadas else "")
        + f" y {len(secas)} sin una gota",
    ]
    return ("\n\nDÍA TRANQUILO (no hay avisos naranjas ni rojos ni tiempo adverso): el parte general de siempre no "
            "engancha. El vídeo de " + cuando + " gira en torno a UN SOLO DATO LLAMATIVO, el que más sorprenda a "
            "alguien de cualquier punto de España. Elige uno de estos (o el de «pueblos» de arriba si es mejor), con "
            "sus cifras exactas:\n" + "\n".join(f"  · {d}" for d in datos) +
            "\nCómo usarlo: 1) la primera frase lo dice con el sitio y la cifra; 2) se retoma a mitad del vídeo con "
            "una comparación que lo haga sentir (qué ropa, qué plan, cuánto cambia de un sitio a otro); 3) el cierre "
            "pregunta por él («¿y en tu ciudad cuántos grados de diferencia?»). El titular y la primera línea del "
            "texto del post también van con ese dato. NO cambies la duración, el número de bloques ni las palabras "
            "de cada bloque: el parte sigue completo, por zonas; solo cambia el hilo.\n")
