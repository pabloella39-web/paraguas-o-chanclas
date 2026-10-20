"""Guion del resumen económico: Claude (si hay clave) o plantilla automática.

Las cifras se calculan y redondean en el código (nunca las inventa el modelo) y se le pasan ya
escritas tal y como se deben leer en voz alta.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from datetime import date, timedelta

import requests

from .config import MODELO_CLAUDE, NOMBRE_CANAL, SEGMENTOS

log = logging.getLogger(__name__)

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
PALABRAS = {"intro": 16, "bolsas": 36, "cripto": 20, "materias": 24, "agenda": 26, "noticias": 30, "cierre": 18}


# ---------------------------------------------------------------- formato de cifras
def fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def fnum(x: float, dec: int = 0) -> str:
    """19215.9 -> '19.216' ; 66.84 -> '66,84' (formato español)."""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fpct(x: float | None, signo: bool = True) -> str:
    if x is None:
        return "—"
    s = fnum(abs(x), 1 if abs(x) < 10 else 0)
    return (("+" if x >= 0 else "−") if signo else "") + s + " %"


def precio_pantalla(a: dict) -> str:
    dec = a["dec"]
    if a["clave"] in ("btc", "eth"):
        dec = 0
    return fnum(a["precio"], dec)


def _d1(x: float) -> str:
    """Un decimal, sin ',0' (107,0 -> '107')."""
    t = fnum(x, 1)
    return t[:-2] if t.endswith(",0") else t


def precio_hablado(a: dict) -> str:
    """Redondeo pensado para el oído: 83.146 $ -> 'unos 83.100 dólares'."""
    p, c = a["precio"], a["clave"]
    if c == "btc":
        return f"unos {fnum(round(p, -2))} dólares"
    if c == "eth":
        return f"unos {fnum(round(p, -1))} dólares"
    if c == "eurusd":
        return f"{fnum(p, 2)} dólares"
    if c in ("oro",):
        return f"{fnum(p)} dólares la onza"
    if c == "plata":
        return f"{_d1(p)} dólares la onza"
    if c in ("brent", "wti"):
        return f"{_d1(p)} dólares el barril"
    if c == "gas":
        return f"{_d1(p)} euros el megavatio hora"
    return f"{fnum(p)} puntos"


def movimiento(x: float | None, pasado: bool = True) -> str:
    if x is None:
        return "sin datos"
    if abs(x) < 0.05:
        return "terminó plano" if pasado else "está plano"
    verbo = ("subió" if x > 0 else "bajó") if pasado else ("sube" if x > 0 else "baja")
    return f"{verbo} un {fnum(abs(x), 1)} %"


def cuando(fecha_iso: str, hoy: date) -> str:
    d = date.fromisoformat(fecha_iso)
    if d == hoy:
        return "hoy"
    if d == hoy - timedelta(days=1):
        return "ayer"
    return f"el {DIAS[d.weekday()]}"


_NUM = ["doce", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce"]


def hora_hablada(hhmm: str | None) -> str:
    """'16:30' -> 'a las cuatro y media de la tarde'."""
    if not hhmm:
        return "a lo largo del día"
    h, m = map(int, hhmm.split(":"))
    if m == 45:
        h, sufijo = h + 1, " menos cuarto"
    else:
        sufijo = {0: "", 15: " y cuarto", 30: " y media"}.get(m, f" y {m}")
    franja = ("de la madrugada" if h < 6 else "de la mañana" if h < 12 else "del mediodía" if h < 14
              else "de la tarde" if h < 21 else "de la noche")
    n = _NUM[h % 12]
    return f"a l{'a' if n == 'una' else 'as'} {n}{sufijo} {franja}"


def dia_hablado(fecha_iso: str) -> str:
    d = date.fromisoformat(fecha_iso)
    return f"el {DIAS[d.weekday()]} {d.day}"


# ---------------------------------------------------------------- datos para el modelo
def resumen_datos(merc: dict, agenda: dict, hoy: date) -> dict:
    activos = {}
    for k, a in merc.items():
        activos[a["nombre"]] = {
            "valor_para_leer": precio_hablado(a), "cambio_dia_pct": a["cambio"],
            "cambio_semana_pct": a.get("semana"), "cambio_mes_pct": a.get("mes"),
            "ultimo_cierre": cuando(a["fecha"], hoy) if a["grupo"] in ("bolsa",) else "ahora",
            "cerca_de_maximos_del_año": a.get("cerca_maximos", False)}
    eventos = [{"cuando": (dia_hablado(e["fecha"]) + ", " if agenda["desde"] != agenda["hasta"] else "")
                + hora_hablada(e.get("hora")), "evento": e["titulo"], "zona": e["bandera"],
                "importancia": e.get("impacto"), "prevision": e.get("prevision"), "anterior": e.get("anterior")}
               for e in agenda["eventos"][:14]]
    prox = [f"{p['banco']}: {dia_hablado(p['fecha'])} (dentro de {p['dias']} días)" for p in agenda["proximas"]]
    out = {"activos": activos, "agenda": eventos, "proximas_reuniones_bancos_centrales": prox}
    if agenda.get("hoy") is not None:  # edición de la noche: lo que estaba previsto hoy
        out["agenda_de_hoy"] = [{"hora": e.get("hora"), "evento": e["titulo"], "importancia": e.get("impacto"),
                                 "prevision": e.get("prevision"), "anterior": e.get("anterior")}
                                for e in agenda["hoy"][:10]]
    return out


MODOS = {
    "diario": "Edición de la MAÑANA de un día laborable, publicada antes de que abra la bolsa española: qué esperar del día. Las bolsas "
              "europeas y de EE. UU. muestran el cierre de su última sesión; el Nikkei, el cierre de esta madrugada; "
              "oro, petróleo, euro y cripto, el precio de ahora mismo. La agenda es la de HOY.",
    "noche": "Resumen de la JORNADA DE HOY, publicado por la noche. Las bolsas europeas (IBEX, Euro Stoxx, DAX) "
             "ya cerraron HOY; Wall Street puede seguir abierta (di 'a esta hora' si su último dato es de hoy); el "
             "Nikkei cerró esta madrugada. Oro, petróleo, euro y cripto: precio de ahora mismo. Cuenta qué ha pasado HOY "
             "con los eventos de 'agenda_de_hoy' (decisiones de la FED o del BCE, datos de inflación o empleo, "
             "inventarios de petróleo, reuniones de la UE...): su resultado SOLO si aparece en los TITULARES; si no "
             "aparece, no lo inventes. El bloque 'agenda' es la de MAÑANA (di 'mañana'). Nunca digas 'ayer' para "
             "referirte a hoy.",
    "semanal": "Es sábado: repaso de la SEMANA en los mercados. Usa sobre todo cambio_semana_pct. "
               "La agenda es la de la SEMANA QUE VIENE (cuenta solo lo más importante).",
    "previa": "Es domingo: los mercados están cerrados. Repasa en breve cómo acabó la semana (cambio_semana_pct), "
              "cómo va el bitcoin el fin de semana y céntrate en lo que trae la SEMANA QUE VIENE.",
}

PROMPT = """Eres guionista de {canal}, un canal de TikTok en español de España que cada día laborable publica dos \
vídeos de poco más de un minuto: por la mañana, lo que se espera del día; por la noche, cómo ha acabado. Lo lee en voz alta {presenta} con voz sintética.

Hoy es {fecha}. {modo}

TONO: cercano, con energía y claro, como un amigo que sabe de economía y te lo cuenta con ganas en el café. \
Humor ligero (un toque, no chistes forzados). Explica la jerga en cuatro palabras cuando salga (p. ej. "el BCE, \
el banco que fija los tipos en Europa").

ESTILO NARRATIVO (muy importante: NO es un recital de cotizaciones):
- Cuenta la HISTORIA del día con un hilo conductor: qué ha movido los mercados y por qué (según los TITULARES), \
y engancha cada bloque con el siguiente con una transición natural ("Y mientras la bolsa sonreía, el petróleo \
iba a lo suyo...", "Pero ojo, que aquí viene lo interesante...").
- Las cifras ya salen en pantalla: elige solo las que importan, como máximo 2 o 3 por bloque, y redondeadas. \
Nunca encadenes cotizaciones una detrás de otra.
- Escribe como se habla: frases enlazadas con "y", "pero", "mientras", "así que"; mezcla alguna frase corta y \
contundente con otras más largas. Usa algún "¡...!" y alguna pregunta para dar entonación, sin pasarte.
- Nada de listas ni de dos puntos.

REGLAS OBLIGATORIAS (contenido financiero):
- Usa SOLO las cifras de DATOS, copiadas tal cual en "valor_para_leer"; para porcentajes, redondea a un decimal \
con coma (0,9 %). Nunca inventes cifras, fechas, causas ni nombres de personas. Puedes citar a una persona solo \
si aparece en los TITULARES.
- Si explicas por qué se movió algo, básate solo en los TITULARES; si no hay explicación, no la inventes.
- Prohibido aconsejar: nada de "compra", "vende", "es buen momento", "va a subir". No predigas precios.
- En "cierre" di de forma natural que es información y no un consejo de inversión.

INTERACCIÓN (para que la gente comente):
- Habla al espectador de tú. "intro" empieza con un gancho que dé ganas de quedarse (una pregunta o un dato \
llamativo de hoy) y menciona el día.
- "cierre" pregunta "¿toro u oso?" (toro si crees que sube, oso si crees que baja) aplicado a algo concreto de \
hoy (el IBEX, el bitcoin, el oro...), invita a comentar y a seguir a {canal} para tener la información actualizada \
cada día. NUNCA digas horas de publicación ni "mañana a las..." para el próximo vídeo. Varía la forma cada día.

BLOQUES (en este orden). LÍMITE ESTRICTO: como máximo {total} palabras en total y estas por bloque: \
{palabras}. El vídeo dura poco más de un minuto: si te pasas, no cabe. Mejor contar menos cosas y bien.
- intro: gancho + día.
- bolsas: el IBEX 35 primero y, en una o dos frases, cómo ha ido Europa y Wall Street (y el Nikkei si aporta). \
Di cuándo es el cierre (ayer, hoy, el viernes...).
- cripto: bitcoin (y ethereum si hay espacio).
- materias: oro, petróleo Brent (y WTI, plata o gas si destacan) y el euro frente al dólar.
- agenda: lo importante de la agenda con la hora en palabras como en DATOS ("a las cuatro y media de la tarde"); \
incluye reuniones de la FED o del BCE, inventarios de petróleo de EE. UU., datos de inflación o empleo y \
reuniones de la UE si las hay. Si hay una reunión de la FED o del BCE próxima, menciónala. Si la agenda está \
vacía, dilo con gracia.
- noticias: las 2 noticias económicas más relevantes para alguien de España de los TITULARES, contadas con tus \
palabras (no copies titulares). Si no hay titulares, haz una curiosidad sobre los datos del día.
- cierre: pregunta, aviso de que no es consejo de inversión y "sígueme".

Además:
- "caption": frase gancho para la descripción del post, máximo 90 caracteres, con 1 emoji, sin hashtags.
- "titulares": las 2 noticias del bloque "noticias" como titulares para la pantalla, máximo 55 caracteres cada \
uno, escritos por ti, con su "fuente" (el nombre del medio del que sale).
- "agenda_es": traducción breve al español (máx. 45 caracteres) de cada evento de la agenda cuyo nombre esté en \
inglés, como objeto {{"nombre original": "traducción"}}.

DATOS:
{datos}

TITULARES (últimas horas):
{titulares}

Responde SOLO con JSON válido:
{{"segmentos": {{"intro": "...", "bolsas": "...", "cripto": "...", "materias": "...", "agenda": "...", \
"noticias": "...", "cierre": "..."}}, "caption": "...", "titulares": [{{"titulo": "...", "fuente": "..."}}], \
"agenda_es": {{}}}}"""


def _claude(prompt: str, clave: str) -> dict:
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.environ.get("CLAUDE_MODEL", MODELO_CLAUDE), "max_tokens": 12000,
              "messages": [{"role": "user", "content": prompt}]}, timeout=240)
    r.raise_for_status()
    texto = "".join(b.get("text", "") for b in r.json()["content"])
    m = re.search(r"\{.*\}", texto, re.S)
    data = json.loads(m.group(0))
    faltan = [s for s in SEGMENTOS if not str(data.get("segmentos", {}).get(s, "")).strip()]
    if faltan:
        raise ValueError(f"Faltan bloques: {faltan}")
    return data


def _revisar(g: dict) -> dict:
    """Red de seguridad: si el guion contiene consejos de inversión explícitos, se descarta."""
    prohibido = re.compile(r"\b(compra|vende|invierte) (ya|ahora|hoy)\b|\bes (un )?buen momento (para|de) "
                           r"(comprar|vender|invertir|entrar)|\bte (recomiendo|aconsejo) (comprar|vender|invertir)|"
                           r"\bva a (subir|bajar|dispararse|desplomarse)\b", re.I)
    for s, txt in g["segmentos"].items():
        if prohibido.search(txt):
            raise ValueError(f"El bloque {s} parece un consejo de inversión: {txt[:80]}")
    return g


def _contar(g: dict) -> int:
    return sum(len(str(v).split()) for v in g["segmentos"].values())


ACORTAR = """Este guion para un vídeo de TikTok es demasiado largo ({actual} palabras) y debe durar poco más \
de un minuto. Reescríbelo con un MÁXIMO de {total} palabras en total, respetando este máximo por bloque: \
{palabras}. Quita detalles secundarios, no las cifras principales ni la pregunta final. No añadas datos nuevos, \
mantén el mismo tono y las mismas reglas (sin consejos de inversión; aviso de que es información en el cierre).
Responde SOLO con el mismo JSON, con los mismos campos.

{guion}"""


def _acortar(g: dict, palabras: dict, clave: str) -> dict:
    total = sum(palabras.values())
    log.info("Guion de %d palabras: se pide recortar a %d", _contar(g), total)
    nuevo = _claude(ACORTAR.format(actual=_contar(g), total=total, palabras=json.dumps(palabras, ensure_ascii=False),
                                   guion=json.dumps({k: v for k, v in g.items() if k != "origen"},
                                                    ensure_ascii=False)), clave)
    for k in ("titulares", "agenda_es", "caption"):
        nuevo.setdefault(k, g.get(k))
    return _revisar(nuevo)


def escribir_guion(merc, agenda, titulares, hoy: date, modo: str, factor: float = 1.0,
                   presenta: str = "un presentador") -> dict:
    palabras = {k: max(8, round(v * factor)) for k, v in PALABRAS.items()}
    clave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if clave:
        tit = "\n".join(f"- [{t['fuente']}] {t['titulo']}. {t['resumen']}" for t in titulares) or "(ninguno)"
        prompt = PROMPT.format(canal=NOMBRE_CANAL.title(), presenta=presenta, fecha=fecha_larga(hoy),
                               modo=MODOS[modo], palabras=json.dumps(palabras, ensure_ascii=False),
                               total=sum(palabras.values()),
                               datos=json.dumps(resumen_datos(merc, agenda, hoy), ensure_ascii=False, indent=1),
                               titulares=tit[:9000])
        for intento in range(2):
            try:
                g = _revisar(_claude(prompt, clave))
                for _ in range(2):  # Claude tiende a pasarse: se le pide recortar a la medida exacta
                    if _contar(g) <= sum(palabras.values()) * 1.1:
                        break
                    g = _acortar(g, palabras, clave)
                g["origen"] = "claude"
                return g
            except Exception as e:  # noqa: BLE001
                log.warning("Guion con Claude falló (intento %d): %s", intento + 1, e)
    g = guion_plantilla(merc, agenda, hoy, modo, factor)
    g["origen"] = "plantilla"
    return g


# ---------------------------------------------------------------- plantilla (sin IA)
def guion_plantilla(merc: dict, agenda: dict, hoy: date, modo: str = "diario", factor: float = 1.0) -> dict:
    rnd = random.Random(hoy.toordinal())
    sem = modo in ("semanal", "previa")
    cambio = (lambda a: a.get("semana")) if sem else (lambda a: a["cambio"])
    dia = DIAS[hoy.weekday()]

    def mov(clave, pasado=True):
        return movimiento(cambio(merc[clave]), pasado) if clave in merc else ""

    if modo == "noche":
        intro = f"Así ha ido este {dia} en los mercados, en un minuto. Y al final, lo que viene mañana."
    elif modo == "diario":
        intro = rnd.choice([
            f"Buenos días. Es {dia} y antes de que abra la bolsa te cuento cómo están los mercados en un minuto.",
            f"¿Toro u oso? Hoy es {fecha_larga(hoy)} y esto es lo que tienes que saber antes de que abra la bolsa.",
            f"Café en mano, que empezamos. Es {dia} y vamos con lo que mueve tu dinero hoy.",
        ])
    elif modo == "semanal":
        intro = f"Es sábado, así que toca repaso: así ha ido la semana en los mercados en un minuto."
    else:
        intro = f"Domingo de mercados cerrados. Te cuento cómo acabó la semana y lo que viene, en un minuto."

    partes = []
    if "ibex" in merc:
        a = merc["ibex"]
        if sem:
            partes.append(f"En la semana, el IBEX 35 {mov('ibex')} y se queda en {precio_hablado(a)}.")
        else:
            partes.append(f"El IBEX 35 {mov('ibex')} {cuando(a['fecha'], hoy)} y cerró en {precio_hablado(a)}.")
            if a.get("cerca_maximos"):
                partes.append("Está muy cerca de sus máximos del año.")
    eu = [k for k in ("stoxx", "dax") if k in merc]
    if eu:
        partes.append("En Europa, " + " y ".join(f"el {merc[k]['nombre']} {mov(k)}" for k in eu) + ".")
    us = [k for k in ("sp500", "nasdaq") if k in merc]
    if us:
        partes.append("En Wall Street, " + " y ".join(f"el {merc[k]['nombre']} {mov(k)}" for k in us) + ".")
    if "nikkei" in merc and not sem and factor >= 0.9:
        partes.append(f"Y esta madrugada en Tokio, el Nikkei {mov('nikkei')}.")
    bolsas = " ".join(partes)

    cripto = ""
    if "btc" in merc:
        b = merc["btc"]
        cripto = (f"El bitcoin está en {precio_hablado(b)}, "
                  + (f"y en la semana {movimiento(b.get('semana'))}." if sem else
                     f"y en las últimas 24 horas {movimiento(b['cambio'])}."))
        if "eth" in merc and factor >= 0.85:
            cripto += f" Ethereum, en {precio_hablado(merc['eth'])}."

    m = []
    if "oro" in merc:
        m.append(f"El oro cotiza a {precio_hablado(merc['oro'])} y {mov('oro', False).replace('terminó', 'está')}.")
    if "brent" in merc:
        m.append(f"El Brent, el petróleo de referencia en Europa, está en {precio_hablado(merc['brent'])}.")
    if "eurusd" in merc:
        m.append(f"Y el euro se cambia a {precio_hablado(merc['eurusd'])}.")
    materias = " ".join(m)

    orden = {"High": 0, "Medium": 1}
    evs = [e for e in agenda["eventos"] if e.get("traducido", True)]
    evs = sorted(evs, key=lambda e: orden.get(e.get("impacto"), 2))[:3]
    evs.sort(key=lambda e: (e["fecha"], e.get("hora") or ""))

    def limpio(t):
        if len(t) > 1 and t[1].islower():
            t = t[0].lower() + t[1:]
        return t.replace("(EIA)", "en Estados Unidos").replace("(API)", "en Estados Unidos").replace(
            "EE. UU.", "Estados Unidos")

    grupos = []  # mismo momento -> una sola frase
    for e in evs:
        momento = dia_hablado(e["fecha"]) if sem else hora_hablada(e.get("hora"))
        if grupos and grupos[-1][0] == momento:
            grupos[-1][1].append(limpio(e["titulo"]))
        else:
            grupos.append((momento, [limpio(e["titulo"])]))
    frases = " ".join(f"{m[0].upper() + m[1:]}, {' y '.join(t)}." for m, t in grupos)
    if evs and not sem:
        ag = ("Para mañana, apunta. " if modo == "noche" else "¿Qué hay hoy en la agenda? ") + frases
    elif evs:
        ag = "La semana que viene, ojo a esto. " + frases
    else:
        ag = "La agenda de hoy viene tranquila, sin datos de los gordos. Ideal para respirar."
    for p in agenda.get("proximas", []):
        if p["dias"] == 0 or any(p["banco"] in e["titulo"] for e in evs):
            continue
        que = "la Reserva Federal decide los tipos de interés" if p["banco"] == "FED" else \
            "el BCE, el banco que fija los tipos en Europa, se reúne"
        ag += f" Y apunta: {dia_hablado(p['fecha'])} {que}."
        break

    cierre = rnd.choice([
        "Y ahora te toca a ti: ¿toro u oso? Toro si crees que sube, oso si crees que baja. Te leo en comentarios.",
        "¿Hoy eres más de toro o de oso? Déjamelo en comentarios, que los leo todos.",
    ]) + " Recuerda que esto es información, no un consejo de inversión. Sígueme para tener la información actualizada cada día."

    seg = {"intro": intro, "bolsas": bolsas, "cripto": cripto, "materias": materias, "agenda": ag,
           "noticias": "", "cierre": cierre}
    return {"segmentos": seg, "caption": "", "titulares": [], "agenda_es": {}}
