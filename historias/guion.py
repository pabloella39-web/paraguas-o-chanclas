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

AMBIENTES = ["lluvia", "tormenta", "viento", "bosque_noche", "casa_crujidos", "sotano_goteo", "ciudad_noche",
             "carretera_noche", "mar_noche", "pueblo_silencio", "hospital", "iglesia"]

TIPOS = {
    "ficcion": "un RELATO ORIGINAL de ficción (terror, suspense psicológico o crimen), inventado por ti, ambientado en "
               "España (un pueblo, una ciudad, una carretera, un piso, una masía...). Nada de copiar historias conocidas.",
    "leyenda": "una LEYENDA o historia popular de España (o del mundo hispano) que exista de verdad: la chica de la "
               "curva, el Palacio de Linares, la Santa Compaña, el Hombre del Saco, el Sacamantecas, Belmez... "
               "Cuéntala como leyenda (\"se dice\", \"cuentan que\"), dramatizada, sin presentarla como hecho probado.",
    "real": "un CASO REAL histórico, muy documentado y ya cerrado (con sentencia firme o resuelto hace décadas), "
            "preferiblemente anterior a 1990: crímenes célebres, desapariciones famosas, misterios históricos. Sé "
            "riguroso: cuenta solo hechos establecidos, marca como dudoso lo que lo sea, no inventes diálogos ni "
            "detalles morbosos, trata a las víctimas con respeto y NO nombres a personas vivas que no sean figuras "
            "públicas. Si dudas de un dato, déjalo fuera.",
}

PROMPT = """Eres el guionista y narrador de "Lo que Callan las Paredes", un canal de TikTok en español de España con
historias de terror, crimen y misterio narradas por una voz grave. Hoy toca {tipo_txt}

Historias ya contadas (NO repitas tema ni giro): {usadas}

FORMATO: la historia se divide en {partes_txt} partes que se publican el mismo día; cada parte es un vídeo de algo
más de un minuto. Cada parte tiene ENTRE {pmin} Y {pmax} PALABRAS (es crucial: menos de {pmin} no llega al minuto).

OBJETIVO: que NADIE deslice. La gente decide en un segundo y se va a los tres si se aburre. Nada de historias
paradas, descriptivas o previsibles: tiene que ser ESPECTACULAR, adictiva y crear expectación real.

ESTRUCTURA OBLIGATORIA DE CADA PARTE:
- Segundo 0: la PRIMERA FRASE (máx. 12 palabras) es un puñetazo: un hecho imposible, una amenaza, una cuenta atrás
  o un detalle que no encaja ("A las tres y doce, alguien llamó desde dentro de mi casa."). Nunca empieces con
  presentaciones, el tiempo que hacía o "me llamo...". En la parte 1 la presentación del personaje llega DESPUÉS del
  gancho y en una sola frase.
- Bucle abierto: en las primeras líneas deja una pregunta sin responder que obligue a seguir (qué hay detrás de la
  puerta, quién envía los mensajes, por qué falta una foto...). Respóndela tarde o nunca dentro de la parte.
- Escalada: cada tramo sube la tensión; nada de relleno. Mínimo DOS giros o revelaciones por parte (algo que cambie
  lo que creíamos: un nombre que no debería estar ahí, una fecha imposible, alguien que ya estaba muerto...).
- Reloj: siempre hay algo en juego y poco tiempo (una noche, una llamada que se corta, alguien que se acerca).
- Ritmo de thriller: frases cortas en los momentos de tensión, a veces de una o dos palabras ("Silencio." "Otra
  vez."). Alterna con alguna frase más larga para respirar. Diálogos breves y directos entre comillas, con voz
  propia. Detalles sensoriales concretos (un olor, un ruido exacto, el frío del pomo), nunca adjetivos vacíos.
- Habla a quien escucha de vez en cuando ("Y tú habrías hecho lo mismo." "Escucha bien lo que viene ahora.").
- FINAL DE PARTE (menos la última): cliffhanger brutal, cortado en seco en mitad de la revelación (una voz que dice
  tu nombre, una puerta que se abre sola, el mensaje que llega desde un número que no existe). Última frase corta.
- Partes 2 y 3: empiezan EN la acción, retomando el cliffhanger en una frase, sin resumir ni decir "en la parte
  anterior".
- ÚLTIMA PARTE: un giro final que nadie vea venir pero que encaje con pistas sembradas antes, y una última imagen
  que se quede en la cabeza. Termina con una frase corta que invite a comentar ("¿Tú habrías abierto esa puerta?").
ESTILO: narración oral para voz sintética, intensa, como un buen narrador de radio a medianoche. Puntos suspensivos
solo en pausas dramáticas. Nada de listas, siglas, símbolos, emojis ni acotaciones entre corchetes o paréntesis.
Números escritos con letras. Sin gore explícito ni violencia sexual: el miedo viene de lo que se insinúa y de lo que
no se ve. Apto para mayores de 16.
ANTES DE RESPONDER, revisa: ¿la primera frase de cada parte engancharía a alguien que va deslizando? ¿hay al menos
dos giros por parte? ¿el final de cada parte obliga a ir a por la siguiente? Si no, reescríbelo.

Cada parte se entrega dividida en "tramos" CONSECUTIVOS (entre 7 y 9 por parte, de 15 a 30 palabras cada uno): al
unir los textos de los tramos sale la parte completa. Cada tramo lleva "imagen": una búsqueda en INGLÉS de 2 a 4
palabras para encontrar una FOTO real que muestre EXACTAMENTE lo que se cuenta en ese tramo (el lugar, el objeto o la
atmósfera concreta: "old stone mill river", "rusty mailbox rural", "candle on wooden table", "flooded basement
stairs", "foggy village street night"). Marca con "susto": true el tramo donde ocurre el momento más impactante de la
parte (uno o dos por parte como mucho): en el vídeo sonará un golpe y la imagen dará un sobresalto justo ahí. Piensa en fotos que existan en un archivo libre (Wikimedia Commons): cosas,
edificios, paisajes y ambientes; NUNCA personas concretas, caras, víctimas ni escenas de violencia.
Además, en cada parte: "ambiente": uno de {ambientes}

Y en cada parte, "gancho": la frase de pantalla para el primer segundo, en MAYÚSCULAS, máximo 7 palabras, que haga
imposible deslizar (ej. "ALGUIEN LLAMÓ DESDE DENTRO", "NO ESTABA SOLA EN CASA", "LA FOTO TENÍA UNA PERSONA MÁS").

Y en general:
- "titulo": 2 a 5 palabras en MAYÚSCULAS, intrigante (ej. "LA HABITACIÓN 14", "EL VECINO DEL QUINTO").
- "caption": una frase gancho para la descripción (máx. 100 caracteres) con 1 emoji, sin hashtags.
- "narrador": "mujer" si la historia la cuenta una mujer en primera persona o la protagonista es una mujer y se
  narra desde su punto de vista; "hombre" en el resto de casos.
- "pregunta": pregunta para el primer comentario fijado (máx. 90 caracteres).
- "hashtags": 4 o 5 hashtags específicos de esta historia (los genéricos se añaden solos).

Responde SOLO con JSON válido:
{{"titulo": "...", "narrador": "hombre", "caption": "...", "pregunta": "...", "hashtags": ["#..."],
"partes": [{{"gancho": "...", "tramos": [{{"texto": "...", "imagen": "...", "susto": false}}], "ambiente": "..."}}]}}"""


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
    partes_txt = "3" if hoy.weekday() in (4, 5, 6) else "2 o 3 (elige 3 si la historia da para ello)"
    pmin, pmax = palabras_parte - 10, palabras_parte + 15
    prompt = PROMPT.format(tipo_txt=TIPOS[tipo], usadas="; ".join(usadas()) or "(ninguna todavía)",
                           partes_txt=partes_txt, pmin=pmin, pmax=pmax, ambientes=", ".join(AMBIENTES))
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
            if not 2 <= len(partes) <= 3:
                raise ValueError(f"{len(partes)} partes")
            if cortas:
                raise ValueError(f"partes demasiado cortas: {cortas}")
            for p in partes:
                for t in p["tramos"]:
                    t["texto"] = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", t["texto"]).strip()
                p["texto"] = " ".join(t["texto"] for t in p["tramos"])
                if p.get("ambiente") not in AMBIENTES:
                    p["ambiente"] = "viento"
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
    t1 = ("Los golpes empezaron la primera noche. Tres. Siempre tres. " * 30).strip()
    return {"titulo": "LOS TRES GOLPES", "tipo": "ficcion", "caption": "Nadie le avisó de lo que había en esa pared 🕯️",
            "pregunta": "¿Tú habrías tirado la pared?", "hashtags": ["#casaencantada", "#golpes"],
            "partes": [{"texto": t1, "tramos": [{"texto": t1[:len(t1) // 2], "imagen": "old house"},
                                                {"texto": t1[len(t1) // 2:], "imagen": "door"}],
                        "escenas": ["old house", "door"], "ambiente": "tormenta"},
                       {"texto": t1, "tramos": [{"texto": t1, "imagen": "basement"}], "escenas": ["basement"],
                        "ambiente": "lluvia"}]}
