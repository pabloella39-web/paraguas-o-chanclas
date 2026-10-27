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
from .contexto import notas as notas_dia
from .prioridad import orden_regiones

log = logging.getLogger(__name__)

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]

# Palabras objetivo por bloque (≈170 palabras ≈ 63 s a ritmo ágil; la velocidad de la voz se ajusta sola)
PALABRAS = {"intro": 22, "general": 20, "norte": 24, "interior": 22, "mediterraneo": 22,
            "sur": 26, "islas": 22, "cierre": 18}


def fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _resumen_datos(prev: list[dict]) -> dict:
    por_region = {}
    for p in prev:
        por_region.setdefault(p["region"], []).append(
            {k: p.get(k) for k in ("nombre", "tmax", "tmin", "lluvia", "lluvia_franjas", "lluvia_mm", "viento",
                                   "racha", "icono", "cielo", "discrepancia_tmax") if p.get(k) is not None})
    return por_region


# ---------------------------------------------------------------- Claude
PROMPT = """Eres el guionista de "Paraguas o Chanclas" (@paraguasochanclas), un canal de TikTok sobre el tiempo en España con HUMOR LIGERO: cercano,
ingenioso, con chascarrillos y comparaciones cotidianas muy españolas, pero SIN palabrotas, sin insultos,
sin política y sin burlarte de nadie. La información meteorológica debe ser exacta: usa SOLO los datos
que te doy (no inventes temperaturas, lluvias ni avisos).

PRECISIÓN CON LA LLUVIA (la gente se queja si no acertamos; mejor matizar que exagerar):
- "lluvia" es la probabilidad en las horas de calle (mañana y tarde); "lluvia_franjas" la da por madrugada, mañana,
  tarde y noche, y "lluvia_mm" son los litros previstos.
- Di CUÁNDO llueve: si solo es por la noche o de madrugada, dilo así ("por la noche puede caer algo") y no digas
  "paraguas sí o sí" ni "te mojas".
- Si "lluvia_mm" es menor de 1, son lloviznas o "cuatro gotas": no lo vendas como día de lluvia.
- "Sí o sí", "te mojas seguro" o similares, solo con 80 % o más en mañana o tarde Y al menos 2 litros.
- Con 30-60 % habla de "posibles chubascos" o "puede caer algo", nunca de lluvia segura.
- Cuando la lluvia sea abundante ("lluvia_mm" de 5 o más), di cuántos litros por metro cuadrado caerán, redondeando
  ("hasta 15 litros por metro cuadrado en Bilbao"): es el dato que la gente entiende y comprueba.

Hoy es {fecha}. Datos por región (temperaturas en grados, lluvia = probabilidad en %, viento en km/h;
icono: sol, sol_nubes, nubes, lluvia, chubascos, tormenta, nieve, niebla). Fuentes: AEMET (oficial) y Open-Meteo (consenso de varios modelos: europeo, alemán, francés y americano).
{datos}

Texto de AEMET para hoy (contexto, puede venir vacío):
{texto_aemet}

CONTEXTO DEL DÍA (menciónalo de pasada, con gracia, en la intro, en "general" o en el cierre; si está vacío, nada):
{contexto}

Hoy la locución la lee {presenta}: usa la concordancia de género correcta si hablas de ti.

INTERACCIÓN CON EL PÚBLICO (muy importante, es lo que hace crecer el canal):
- Habla de tú al espectador todo el rato ("si hoy sales a correr...", "tú que estás en Málaga...").
- RETENCIÓN (lo más importante): casi la mitad de la gente se va en los 3 primeros segundos. La intro NO saluda ni
  lee la fecha (ya sale en pantalla). La PRIMERA FRASE (máximo 10 palabras) es el gancho: urgencia + fenómeno +
  ciudad concreta, como un titular de última hora ("Ojo, Málaga: rachas de 80 kilómetros por hora hoy.",
  "Madrid, hoy te mojas sí o sí.", "Barcelona, aviso naranja por lluvias."). Usa el GANCHO DE HOY de abajo y nombra
  primero las ciudades que más nos ven (Madrid, Barcelona, Málaga, Sevilla, Valencia) si están afectadas. La segunda
  frase amplía en una línea y promete que al final dirás dónde hará más calor y más frío ("quédate, que al final...").
  Urgencia sí, mentiras no: solo habla de avisos si los hay de verdad.
GANCHO DE HOY: {gancho}
- En al menos dos bloques regionales, interpela a la gente de una ciudad concreta ("Si eres de Bilbao,
  hoy...", "Gente de Sevilla, ...").
- En el cierre, una pregunta concreta para que comenten (varía cada día: ¿paraguas o chanclas?, ¿desde
  qué ciudad nos ves?, ¿qué plan tienes con este tiempo?, ¿acerté ayer?...) y pide que sigan la cuenta.
  LLAMADA DE HOY (obligatoria en el cierre, con tus palabras y con gracia): {cta}

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

ORDEN DE HOY: los bloques regionales NO van siempre igual: se cuentan de más a menos relevante. Hoy el orden es
{orden}. Motivos detectados en los datos: {motivos}. Empieza el primero con fuerza (es la noticia del día) y
enlaza cada región con la siguiente con naturalidad; no digas "empezamos por el norte" si no toca.

Bloques (en este orden: intro, las regiones en el orden de hoy, general y cierre):
- intro: el gancho (ver RETENCIÓN), sobre la región que va primera.
- general: va AL FINAL, justo antes del cierre: es la recompensa prometida. Dónde hará más calor y dónde más
  frío de España (con las cifras) y, si acaso, un remate de una frase.
- norte, interior, mediterraneo, sur, islas: el tiempo de esas ciudades (islas = Baleares y Canarias). En "sur" \
nombra SIEMPRE Ceuta y Melilla (aunque sea en una frase corta): la gente de allí lo pide.
- cierre: despedida graciosa + pide que sigan "Paraguas o Chanclas" para tener el tiempo de cada día. NUNCA digas \
horas de publicación ni "mañana a las...".
  Si encaja, termina diciendo si hoy toca paraguas o chanclas.

Además escribe "titular": el gancho para la pantalla, en MAYÚSCULAS, de 2 a 5 palabras y máximo 26 caracteres,
sin emojis, con la CIUDAD o zona y el fenómeno (ej. "MADRID, HOY TE MOJAS", "MÁLAGA: RACHAS DE 80", "BARCELONA,
AVISO NARANJA", "SEVILLA SE ACHICHARRA").

Y escribe "caption": UNA sola frase gancho para la descripción del post (máx. 90 caracteres), que
interpele al público con una pregunta o reto relacionado con el tiempo de hoy, con 1 o 2 emojis y SIN
hashtags (los hashtags y el resumen se añaden automáticamente).

Responde SOLO con JSON válido con esta forma:
{{"segmentos": {{"intro": "...", "general": "...", "norte": "...", "interior": "...", "mediterraneo": "...",
"sur": "...", "islas": "...", "cierre": "..."}}, "titular": "...", "caption": "..."}}"""


def _claude(prompt: str, clave: str) -> dict:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.environ.get("CLAUDE_MODEL", MODELO_CLAUDE), "max_tokens": 12000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=240,
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


# Llamada a la acción del cierre: rota cada día (mencionar amigos / pedir tu ciudad / pregunta libre)
CTAS = {
    "mencion": 'pide que MENCIONEN EN COMENTARIOS a sus amigos para que estén al tanto del tiempo y sepan si '
               'necesitan paraguas o chanclas (ej. "menciona a ese amigo que siempre sale sin paraguas").',
    "ciudad": 'invita a escribir en comentarios su pueblo o ciudad para contestarle con su previsión: "dime en '
              'comentarios tu pueblo y te digo si allí toca paraguas o chanclas".',
    "pregunta": "una pregunta concreta para que comenten (¿paraguas o chanclas?, ¿desde qué ciudad nos ves?, "
                "¿qué plan tienes con este tiempo?, ¿acerté ayer?...).",
}
CIERRES_PLANTILLA = {
    "mencion": "Menciona a tus amigos para que sepan si hoy necesitan paraguas o chanclas.",
    "ciudad": "Dime en comentarios tu pueblo y te digo si allí toca paraguas o chanclas.",
}


GANCHO_TEXTO = ""   # lo rellena main.py con tiempo.gancho.para_guion() antes de escribir el guion
GANCHO = None       # dict de tiempo.gancho.fenomeno_del_dia (también para la plantilla sin IA)


DIAS_CLAVE = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def continuidad(hoy: date) -> str | None:
    """Lo que adelantó sobre hoy el último vídeo semanal (domingo) o de mitad de semana (miércoles)."""
    import json as _json
    from datetime import timedelta as _td
    from .config import RAIZ
    dia = DIAS_CLAVE[hoy.weekday()]
    for atras in range(1, 7):
        f = hoy - _td(days=atras)
        for tipo, quien in (("resto", "el miércoles"), ("semana", "el domingo")):
            ruta = RAIZ / "historial_especiales" / f"{tipo}-{f.isoformat()}.json"
            if ruta.exists():
                try:
                    texto = (_json.loads(ruta.read_text(encoding="utf-8")).get("guion") or {}).get(dia)
                except Exception:  # noqa: BLE001
                    texto = None
                if texto:
                    return (f"CONTINUIDAD: {quien} adelantamos sobre hoy: «{texto}». Compáralo con los datos de hoy: si se "
                            f"cumple, dilo en la intro justo después del gancho, con orgullo y en una frase ('Te lo dije "
                            f"{quien}: hoy el norte se moja'); si ha cambiado, avísalo ('Cambio de planes respecto a lo "
                            f"que te dije {quien}: ...'). Nunca inventes lo que se dijo.")
    return None


def cta_del_dia(hoy: date) -> str:
    # "Dime tu pueblo" es lo que más conversación genera (y se contesta a todos): 4 de cada 7 días
    return ("ciudad", "mencion", "ciudad", "pregunta", "ciudad", "ciudad", "mencion")[hoy.toordinal() % 7]


def _guion_precargado(hoy: date, prompt: str) -> dict | None:
    """Guion escrito con el plan de Claude (tarea programada), sin gastar API: ver tiempo/manual.py."""
    from . import manual
    g = manual.responder(f"parte-{hoy.isoformat()}", prompt, "19:50" if os.environ.get("VISPERA") else "07:05")
    if g and set(g.get("segmentos", {})) >= set(SEGMENTOS):
        g["origen"] = "manual"
        return g
    return None


def escribir_guion(prev: list[dict], hoy: date, texto_aemet: str = "", factor: float = 1.0,
                   presenta: str = "un presentador") -> dict:
    """factor < 1 pide un guion más corto; > 1 más largo (para ajustar la duración)."""
    palabras = {k: max(6, round(v * factor)) for k, v in PALABRAS.items()}
    orden, info = orden_regiones(prev, texto_aemet, hoy)
    if GANCHO and GANCHO.get("ciudades"):  # la región del gancho va primero (el mapa acompaña a la voz)
        region = next((c["region"] for c in prev if c["nombre"] == GANCHO["ciudades"][0]), None)
        if region in orden:
            orden = [region] + [r for r in orden if r != region]
    log.info("Orden de regiones hoy: %s", ", ".join(f"{r} ({info[r]['puntos']})" for r in orden))
    clave = os.environ.get("ANTHROPIC_API_KEY", "")
    if clave:
        prompt = PROMPT.format(fecha=fecha_larga(hoy), datos=json.dumps(_resumen_datos(prev), ensure_ascii=False),
                               texto_aemet=texto_aemet[:2500] or "(vacío)",
                               palabras=json.dumps(palabras), total=sum(palabras.values()), presenta=presenta,
                               orden=" → ".join(orden), cta=CTAS[cta_del_dia(hoy)],
                               gancho=GANCHO_TEXTO or "(sin datos: usa lo más llamativo de los datos)",
                               contexto="\n".join(f"- {n}" for n in notas_dia(hoy) + ([continuidad(hoy)]
                                                                                       if continuidad(hoy) else []))
                               or "(nada especial)",
                               motivos=json.dumps({r: m["motivos"] or ["día tranquilo"] for r, m in info.items()},
                                                  ensure_ascii=False))
        if os.environ.get("VISPERA"):
            prompt = ("IMPORTANTE: este vídeo se publica LA NOCHE ANTERIOR, a las 20:30: es la previsión de MAÑANA, "
                      f"{fecha_larga(hoy)}. Donde abajo pone 'hoy', tú habla de 'mañana' (en la locución, el titular y "
                      "la caption). Nunca digas 'hoy' para el día de la previsión. La continuidad con el vídeo semanal "
                      "también se refiere a mañana.\n\n") + prompt
        pre = _guion_precargado(hoy, prompt)
        if pre:
            pre["orden"] = orden
            return pre
        for intento in range(2):
            try:
                g = _claude(prompt, clave)
                g["origen"] = "claude"
                g["orden"] = orden
                return g
            except Exception as e:  # noqa: BLE001
                log.warning("Guion con Claude falló (intento %d): %s", intento + 1, e)
    if not os.environ.get("PERMITIR_PLANTILLA"):
        raise RuntimeError("Sin guion escrito ni API disponible: no se publica la plantilla básica")
    g = guion_plantilla(prev, hoy, factor, texto_aemet)
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


def guion_plantilla(prev: list[dict], hoy: date, factor: float = 1.0, texto_aemet: str = "") -> dict:
    """Guion sin IA (respaldo). factor < 0.85 quita los comentarios; > 1.1 añade uno al cierre."""
    rnd = random.Random(hoy.toordinal())
    reg = _resumen_datos(prev)
    caliente = max(prev, key=lambda p: p["tmax"])
    fria = min(prev, key=lambda p: p["tmin"])
    lluviosas = [_nombre(p) for p in prev if p["lluvia"] >= 50]
    # Con factor 1 hay comentario en 3 regiones; si hay que alargar, en todas; si acortar, en ninguna
    con_chiste = {"norte", "islas"}
    con_alusion = {"sur"}
    if factor > 1.1:
        con_chiste = {"norte", "interior", "mediterraneo", "sur", "islas"}
    elif factor < 0.9:
        con_chiste = {"norte"}
    seg = {
        "intro": "",  # se rellena abajo, cuando se sabe qué región va primera
        "general": (f"Y lo prometido: lo más caluroso de hoy, {_nombre(caliente)} con {caliente['tmax']} grados, y lo "
                    f"más frío al amanecer, {_nombre(fria)} con {fria['tmin']}. "
                    + (f"Ojo con la lluvia en {' y '.join(lluviosas[:2])}." if lluviosas
                       else "De lluvia, poca cosa.")),
    }
    orden, info = orden_regiones(prev, texto_aemet, hoy)
    if GANCHO and GANCHO.get("ciudades"):  # la región del gancho va primero (el mapa acompaña a la voz)
        region = next((c["region"] for c in prev if c["nombre"] == GANCHO["ciudades"][0]), None)
        if region in orden:
            orden = [region] + [r for r in orden if r != region]
    zonas = {"norte": "el norte", "interior": "el interior", "mediterraneo": "el Mediterráneo", "sur": "el sur",
             "islas": "las islas"}
    intros = {}
    for k, r in enumerate(orden):
        if k == 0:
            intros[r] = f"Empezamos por {zonas[r]}"
        elif k == len(orden) - 1:
            intros[r] = f"Y para terminar, en {zonas[r]}"
        else:
            intros[r] = rnd.choice([f"En {zonas[r]}", f"Vamos con {zonas[r]}", f"Si miramos a {zonas[r]}"])
    for r in orden:
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
        graves = [c for c in lista if c["icono"] in ("tormenta", "nieve") or c["lluvia"] >= 70]
        if graves:
            # Día complicado: primero el aviso, sin chistes
            fen = ("tormentas" if any(c["icono"] == "tormenta" for c in graves) else
                   "nieve" if any(c["icono"] == "nieve" for c in graves) else "lluvia")
            nombres = " y ".join(_nombre(c) for c in graves[:2])
            prob = max(c["lluvia"] for c in graves)
            if fen == "lluvia" and prob < 90:
                seg[r] = (f"{intros[r]}, con lluvia casi segura en {nombres}, un {prob} por ciento. Paraguas en mano. "
                          f"Las máximas, {_frase_ciudades(lista).replace('máximas ', '')}.{alusion}")
            else:
                seg[r] = (f"{intros[r]}, y ojo, que hay {fen} en {nombres}, con hasta un {prob} por ciento de "
                          f"probabilidad de lluvia. Mucha precaución. "
                          f"Las máximas, {_frase_ciudades(lista).replace('máximas ', '')}.{alusion}")
        else:
            seg[r] = f"{intros[r]}, {CIELO[dom]} y {_frase_ciudades(lista)}.{chiste}{alusion}{aviso}"
        if r == "sur":  # Ceuta y Melilla, siempre nombradas
            cm = [p for p in lista if p["nombre"] in ("Ceuta", "Melilla")]
            if cm:
                seg[r] += " " + " y ".join(f"{'en' if k else 'En'} {p['nombre']}, {p['tmax']} grados"
                                           for k, p in enumerate(cm)) + "."
    pregunta = rnd.choice([
        "Y tú, ¿hoy eres de paraguas o de chanclas? Te leo en comentarios.",
        "¿Desde qué ciudad nos ves? Dímelo en comentarios.",
        "¿Qué plan tienes con este tiempo? Cuéntamelo abajo.",
        "Etiqueta a ese amigo que siempre sale en manga corta.",
    ])
    pregunta = CIERRES_PLANTILLA.get(cta_del_dia(hoy), pregunta)
    seg["cierre"] = f"{pregunta} Y sigue a Paraguas o Chanclas para tener el tiempo de cada día."
    if factor > 1.2:
        seg["cierre"] += " ¡Pásaselo a quien siempre sale sin chaqueta!"
    caption = (f"El tiempo en España hoy, {fecha_larga(hoy)} ☀️🌧️ ¿Tú hoy eres de paraguas o de chanclas? 👇 "
               "#eltiempo #AEMET #meteo #tiempoespaña #paraguasochanclas")
    # Gancho: lo más llamativo de la región que abre el vídeo + promesa del final
    top = orden[0]
    lista = reg.get(top, [])
    nombre_zona = {"norte": "el norte", "interior": "el interior", "mediterraneo": "el Mediterráneo",
                   "sur": "el sur", "islas": "las islas"}[top]
    tit_zona = nombre_zona.upper()
    tmax_c = max(lista, key=lambda c: c["tmax"]) if lista else caliente
    if any(c["icono"] == "tormenta" for c in lista):
        gancho, titular = f"Ojo, {nombre_zona}, que hoy vienen tormentas.", f"TORMENTAS EN {tit_zona}"
    elif any(c["icono"] == "nieve" for c in lista):
        gancho, titular = f"Ojo, {nombre_zona}, que hoy puede nevar.", f"NIEVE EN {tit_zona}"
    elif lista and max(c["lluvia"] for c in lista) >= 60:
        gancho, titular = f"Si estás en {nombre_zona}, hoy el paraguas no es opcional.", f"LLUVIA EN {tit_zona}"
    elif lista and tmax_c["tmax"] >= 30:
        gancho, titular = (f"{_nombre(tmax_c)} se va hoy a {tmax_c['tmax']} grados, ¿quién dijo otoño?",
                           f"CALOR EN {tit_zona}")
    elif lista and min(c["tmin"] for c in lista) <= 3:
        gancho, titular = f"Si estás en {nombre_zona}, hoy toca abrigo de verdad al salir.", f"FRÍO EN {tit_zona}"
    else:
        gancho, titular = "¿Paraguas o chanclas? Hoy te lo cuento zona a zona.", "¿PARAGUAS O CHANCLAS?"
    if GANCHO:
        ciudad = (GANCHO["ciudades"] or [None])[0]
        frases = {"tormenta": "llegan tormentas", "lluvia": "hoy te mojas", "nieve": "ojo a la nieve y al hielo",
                  "viento": "agárrate, que sopla fuerte", "sol": "hoy aprieta el calor", "niebla": "niebla al salir"}
        if ciudad:
            gancho = f"Ojo, {ciudad}: {frases.get(GANCHO['icono'], 'hoy toca mirar el cielo')}."
            titular = f"{ciudad.upper()}: {GANCHO['insignia']}"[:30]
    seg["intro"] = gancho + " Y quédate, que al final te digo dónde hará más calor y más frío de España."
    extra = notas_dia(hoy)
    if extra:
        seg["cierre"] = extra[0] + " " + seg["cierre"]
    return {"segmentos": seg, "caption": caption, "orden": orden, "titular": titular[:30]}
