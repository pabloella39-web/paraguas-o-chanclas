"""Guion de la historia del día con Claude: 2 o 3 partes de ~70 s, cada una con final en suspense."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

import requests

from .config import HISTORIAL, PALABRAS_PARTE, tipo_del_dia

log = logging.getLogger(__name__)
# El modelo más capaz para escribir: la calidad de la historia es lo que retiene al público
# (solo respaldo: lo normal es que la escriba la tarea programada con el plan de Claude)
MODELO = os.environ.get("HISTORIAS_MODELO", "claude-sonnet-5-5")

AMBIENTES = ["guerra", "ciudad_antigua", "multitud", "viento", "lluvia", "tormenta", "mar_noche", "pueblo_silencio",
             "iglesia", "hospital", "bosque_noche", "ciudad_noche"]

TIPOS = {
    "guerra_mundial": "la SEGUNDA GUERRA MUNDIAL (Europa, el Pacífico, el frente del Este, la vida de los civiles, la "
                      "resistencia, los bombardeos, las evacuaciones, Normandía, Stalingrado, Berlín, Londres...)",
    "espana": "la HISTORIA DE ESPAÑA del siglo XX o anterior: la Segunda República, la Guerra Civil (sin tomar partido "
              "y mostrando el drama humano de ambos lados), la posguerra, la emigración, la Transición, el 23-F, el "
              "desastre del 98, la Guerra de la Independencia...",
    "asia": "la HISTORIA DE ASIA: China (la Larga Marcha, la Revolución Cultural, la Ciudad Prohibida, el último "
            "emperador, la Gran Muralla), Japón (los samuráis, la era Meiji, Hiroshima y Nagasaki desde el punto de "
            "vista de un civil, el terremoto de Kanto), Corea, Vietnam, la India...",
    "siglo_xx": "un gran HECHO DEL SIGLO XX o principios del XXI que ya sea historia (más de 20 años): el Titanic, "
                "Chernóbil, la caída del Muro de Berlín, la llegada a la Luna, la Guerra Fría, la crisis de los "
                "misiles, el 11-S o el 11-M contados SIEMPRE desde el punto de vista de un testigo, rescatador o "
                "superviviente (nunca del autor), con máximo respeto a las víctimas",
    "antigua": "la HISTORIA ANTIGUA o MEDIEVAL: Pompeya, Roma, Egipto, Cartago, los vikingos, las cruzadas, la peste "
               "negra, la conquista de América, Al-Ándalus...",
    "pueblos": "la HISTORIA DE UN PUEBLO O LUGAR CONCRETO DE ESPAÑA con un suceso real y documentado: Belchite, "
               "Guernica, el pantano que sumergió un pueblo (Mansilla, Riaño), la emigración de un pueblo gallego, "
               "una riada histórica, la mina de un pueblo minero, un pueblo abandonado...",
}

PROMPT = """Eres el guionista y narrador de "{nombre}", un canal de TikTok y YouTube Shorts en español de España con
vídeos POV DE HISTORIA: el espectador VIVE un momento histórico real en segunda persona ("Es el 6 de agosto de 1945.
Tienes doce años y vas camino de la escuela en Hiroshima..."). Hoy toca {tipo_txt}.

Historias ya contadas (NO repitas tema ni momento): {usadas}

RIGOR: todo lo histórico (fechas, lugares, cifras, hechos) debe ser CIERTO y comprobable. El protagonista es un
personaje anónimo inventado pero verosímil (un soldado, una enfermera, un niño, un obrero, una telefonista...), y lo
que vive es lo que vivieron personas reales en ese momento. Si dudas de un dato, déjalo fuera. Nada de política
actual ni de tomar partido: el drama humano. Sin gore explícito ni violencia sexual; con respeto absoluto a las
víctimas. Nunca el punto de vista de un terrorista ni de un verdugo glorificado.

FORMATO: UN solo vídeo de algo más de un minuto: ENTRE {pmin} Y {pmax} PALABRAS en total (crucial).

OBJETIVO: que nadie deslice. Estructura:
- Primera frase (máx. 12 palabras): fecha + lugar + quién eres, como un puñetazo ("Berlín, abril de 1945. Tienes
  catorce años y te acaban de dar un fusil.").
- Bucle abierto en las primeras líneas: qué está a punto de pasar y tú aún no lo sabes (el espectador sí, y eso
  engancha).
- Escalada con detalles sensoriales concretos y reales (el ruido, el olor, el frío, lo que llevas en el bolsillo).
- Uno o dos momentos de impacto (el instante decisivo).
- Frases cortas en la tensión. Habla siempre de TÚ.
- Final: lo que pasó de verdad, con una cifra o un dato real que impresione ("Aquella mañana murieron...", "Nunca
  más se volvió a..."), y una pregunta corta al público ("¿Tú qué habrías hecho?").
ESTILO: narración oral para voz sintética, intensa y cercana. Números escritos con letras. Nada de listas, siglas
raras, símbolos ni acotaciones entre paréntesis o corchetes.

Se entrega en "tramos" CONSECUTIVOS (entre 8 y 11, de 12 a 25 palabras cada uno): al unirlos sale el texto completo.
Cada tramo lleva "imagen": búsqueda en INGLÉS de 2 a 5 palabras para encontrar en Wikimedia Commons una FOTO o
grabado HISTÓRICO REAL de ese momento y lugar ("Berlin 1945 ruins", "Hiroshima 1945 city", "Madrid 1936 barricade",
"Titanic lifeboat 1912", "Pompeii excavation street", "Chernobyl reactor 1986"). Fotos de época de lugares, multitudes,
soldados, objetos, edificios; nunca cadáveres ni escenas crueles. Marca con "susto": true el tramo del momento de
mayor impacto (uno, como mucho dos): sonará un golpe y la imagen dará una sacudida.
"ambiente" del vídeo: uno de {ambientes} (guerra = combates y bombardeos lejanos; multitud = gente, gritos lejanos;
ciudad_antigua = calles de época, carros, campanas).

Además:
- "titulo": 2 a 6 palabras en MAYÚSCULAS, empezando por "POV:" (ej. "POV: ESTÁS EN EL TITANIC").
- "gancho": frase de pantalla para el primer segundo, MAYÚSCULAS, máx. 7 palabras ("TIENES 14 AÑOS Y ES BERLÍN 1945").
- "etiqueta": lugar y fecha en MAYÚSCULAS para la pantalla ("BERLÍN · ABRIL DE 1945").
- "caption": frase gancho para la descripción (máx. 100 caracteres) con 1 emoji, sin hashtags.
- "narrador": "mujer" si la protagonista es una mujer o una niña; "hombre" en el resto de casos.
- "pregunta": pregunta para el primer comentario (máx. 90 caracteres).
- "hashtags": 3 o 4 hashtags específicos (ej. "#segundaguerramundial", "#berlin").

Responde SOLO con JSON válido:
{{"titulo": "POV: ...", "gancho": "...", "etiqueta": "...", "narrador": "hombre", "caption": "...", "pregunta": "...",
"hashtags": ["#..."], "partes": [{{"tramos": [{{"texto": "...", "imagen": "...", "susto": false}}], "ambiente": "..."}}]}}"""


def usadas(n: int = 40) -> list[str]:
    out = []
    for f in sorted(HISTORIAL.glob("*.json"))[-n:]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append(f"{d.get('titulo')} ({d.get('tipo')}): {d.get('resumen', '')[:80]}")
        except Exception:  # noqa: BLE001
            pass
    return out


def _claude(prompt: str) -> dict:
    clave = os.environ["ANTHROPIC_API_KEY"].strip()
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                      json={"model": MODELO, "max_tokens": 16000, "messages": [{"role": "user", "content": prompt}]},
                      timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"Claude HTTP {r.status_code}: {r.text[:400]}")
    texto = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
    return json.loads(re.search(r"\{.*\}", texto, re.S).group(0))


def palabras(t: str) -> int:
    return len(t.split())


def escribir(hoy: date, palabras_parte: int = PALABRAS_PARTE, tipo: str | None = None) -> dict:
    tipo = tipo or tipo_del_dia(hoy)
    from .config import NOMBRE
    pmin, pmax = palabras_parte - 10, palabras_parte + 12
    prompt = PROMPT.format(nombre=NOMBRE.title(), tipo_txt=TIPOS[tipo],
                           usadas="; ".join(usadas()) or "(ninguna todavía)", pmin=pmin, pmax=pmax,
                           ambientes=", ".join(AMBIENTES))
    ultimo = None
    # Guion ya escrito (en el chat, sin gastar API): historias/guiones/AAAA-MM-DD.json
    # Primero, la historia escrita con el plan de Claude (tarea programada, sin API): tiempo/manual.py
    from tiempo import manual
    escrita = manual.responder(f"historia-{hoy.isoformat()}", prompt, "19:30")
    for intento in range(3):
        try:
            if escrita is not None:
                g, escrita = escrita, None   # si no pasa la validación, el siguiente intento va a la API
                g.setdefault("tipo", tipo)
            else:
                g = _claude(prompt)
            partes = g.get("partes") or []
            for p in partes:  # los tramos forman el texto y marcan cuándo cambia la imagen
                if p.get("tramos"):
                    p["tramos"] = [t for t in p["tramos"] if t.get("texto", "").strip()]
                    p["texto"] = " ".join(t["texto"].strip() for t in p["tramos"])
                    p["escenas"] = [t.get("imagen") or "dark night" for t in p["tramos"]]
                else:
                    p["tramos"] = [{"texto": p.get("texto", ""), "imagen": "dark night"}]
                    p["escenas"] = p.get("escenas") or ["dark night"]
            cortas = [palabras(p["texto"]) for p in partes if palabras(p["texto"]) < pmin - 15]
            if len(partes) != 1:
                raise ValueError(f"{len(partes)} partes (debe ser un solo vídeo)")
            if cortas:
                raise ValueError(f"partes demasiado cortas: {cortas}")
            for p in partes:
                for t in p["tramos"]:
                    t["texto"] = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", t["texto"]).strip()
                p["texto"] = " ".join(t["texto"] for t in p["tramos"])
                if p.get("ambiente") not in AMBIENTES:
                    p["ambiente"] = "viento"
                p.setdefault("gancho", g.get("gancho"))
            g["tipo"] = g.get("tipo") or tipo
            log.info("Historia: %s (%s), %d partes de %s palabras", g["titulo"], tipo, len(partes),
                     [palabras(p["texto"]) for p in partes])
            return g
        except Exception as e:  # noqa: BLE001
            ultimo = e
            log.warning("Guion de la historia falló (intento %d): %s", intento + 1, e)
            prompt += f"\n\nATENCIÓN: el intento anterior falló ({e}). Respeta el número de palabras y el JSON."
    raise RuntimeError(f"No se pudo escribir la historia: {ultimo}")


def historia_demo() -> dict:
    frases = ["Berlín, abril de mil novecientos cuarenta y cinco.", "Tienes catorce años y te acaban de dar un fusil.",
              "El cielo retumba sin parar.", "Tu madre te espera en el sótano.", "Y tú aún no sabes lo que viene."]
    tramos = [{"texto": " ".join(frases), "imagen": "Berlin 1945 ruins", "susto": k == 4} for k in range(4)]
    texto = " ".join(t["texto"] for t in tramos)
    return {"titulo": "POV: BERLÍN 1945", "tipo": "guerra_mundial", "gancho": "TIENES 14 AÑOS Y ES BERLÍN 1945",
            "etiqueta": "BERLÍN · ABRIL DE 1945", "caption": "Tienes 14 años y te dan un fusil 🪖",
            "pregunta": "¿Tú qué habrías hecho?", "hashtags": ["#segundaguerramundial", "#berlin"],
            "partes": [{"texto": texto, "tramos": tramos, "escenas": [t["imagen"] for t in tramos],
                        "ambiente": "guerra", "gancho": "TIENES 14 AÑOS Y ES BERLÍN 1945"}]}
