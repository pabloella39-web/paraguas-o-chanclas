"""El gancho del día: el fenómeno más llamativo (avisos de AEMET, tormentas, lluvia fuerte, rachas, calor, frío…),
las ciudades afectadas (priorizando las que más nos ven) y el texto de urgencia para los primeros segundos.

Todo sale de datos reales: si no hay avisos no se habla de avisos; la urgencia se construye con lo que de verdad
destaca ese día.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

# Ciudades con más público según las estadísticas de TikTok (Madrid, Barcelona, Málaga, Valencia, Sevilla)
CIUDADES_PUBLICO = ["Madrid", "Barcelona", "Málaga", "Sevilla", "Valencia"]
COLOR_NIVEL = {"rojo": (230, 30, 40), "naranja": (255, 140, 0), "amarillo": (255, 205, 40)}
NIVEL_N = {"amarillo": 1, "naranja": 2, "rojo": 3}
ICONO_FENOMENO = {"tormentas": "tormenta", "lluvias": "lluvia", "nevadas": "nieve", "vientos": "viento",
                  "costeros": "viento", "temperaturas máximas": "sol", "temperaturas mínimas": "nieve",
                  "nieblas": "niebla", "polvo": "niebla", "aludes": "nieve"}


# Cómo se dice cada fenómeno de AEMET (en pantalla y en voz)
NOMBRE_FENOMENO = {"costeros": "oleaje", "vientos": "viento", "lluvias": "lluvia", "tormentas": "tormentas",
                   "nevadas": "nieve", "temperaturas máximas": "calor", "temperaturas mínimas": "frío",
                   "nieblas": "niebla", "polvo": "polvo en suspensión", "aludes": "aludes", "galernas": "galerna"}


def nombre_fenomeno(f: str) -> str:
    return NOMBRE_FENOMENO.get(f.lower().strip(), f.lower())


def avisos_de_hoy(hoy) -> list[dict]:
    """Avisos de AEMET (amarillos, naranjas y rojos) vigentes hoy, agrupados por fenómeno y nivel."""
    clave = os.environ.get("AEMET_API_KEY", "").strip()
    if not clave:
        return []
    from .especiales import agrupar, descargar_avisos
    try:
        avisos = descargar_avisos(clave)
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudieron leer los avisos de AEMET: %s", e)
        return []
    ahora = datetime.now().astimezone()
    fin_dia = ahora.replace(hour=23, minute=59) + timedelta(hours=2)
    if os.environ.get("VISPERA"):  # parte de mañana: avisos que afectan a mañana
        ahora = ahora.replace(hour=0, minute=0) + timedelta(days=1)
        fin_dia = ahora.replace(hour=23, minute=59)
    vigentes = []
    for a in avisos:
        try:
            ini, fin = datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"])
        except (TypeError, ValueError):
            continue
        if fin > ahora and ini < fin_dia:
            vigentes.append(a)
    grupos = agrupar(vigentes)
    log.info("Avisos de hoy: %s", [(g["nivel"], g["fenomeno"], len(g["zonas"])) for g in grupos])
    return grupos


def _ciudades_en_zonas(prev, zonas: list[str]) -> list[str]:
    texto = " ".join(zonas).lower()
    return [c["nombre"] for c in prev if c["nombre"].lower() in texto]


def _ordenar_publico(nombres: list[str]) -> list[str]:
    return sorted(dict.fromkeys(nombres), key=lambda n: CIUDADES_PUBLICO.index(n) if n in CIUDADES_PUBLICO else 99)


def fenomeno_del_dia(prev: list[dict], avisos: list[dict] | None = None) -> dict:
    """{icono, efecto, insignia, color, dato, ciudades, motivo}: lo que abre el vídeo."""
    # Solo los avisos NARANJA y ROJO abren el vídeo: los amarillos son frecuentes y locales, y cuando no se cumplen
    # (Murcia, 28/10/2026: aviso amarillo por lluvia y sol todo el día) el que queda mal es el canal.
    amarillos = [a for a in (avisos or []) if a.get("nivel") == "amarillo"]
    AMARILLOS[:] = amarillos
    avisos = [a for a in (avisos or []) if a.get("nivel") in ("naranja", "rojo")]
    if avisos:
        a = avisos[0]
        fen = a["fenomeno"].lower()
        icono = next((v for k, v in ICONO_FENOMENO.items() if k in fen), "lluvia")
        ciudades = _ordenar_publico(a.get("ciudades") or _ciudades_en_zonas(prev, a["zonas"]))
        zona = ciudades[0] if ciudades else a["zonas"][0].split(" de ")[-1].strip(" ()")
        c = next((x for x in prev if x["nombre"] == zona), None)
        if c and icono == "viento" and (c.get("racha") or 0) >= 40:
            dato = f"RACHAS DE {round(c['racha'])} KM/H EN {zona.upper()}"
        elif c and icono in ("lluvia", "tormenta") and c["lluvia"] >= 40:
            dato = f"LLUVIA {c['lluvia']} % EN {zona.upper()}"
        elif c and icono == "sol":
            dato = f"{c['tmax']}° EN {zona.upper()}"
        else:
            resto = len(a["zonas"]) - 1
            dato = zona.upper() + (f" Y {resto} ZONA{'S' if resto > 1 else ''} MÁS" if resto else "")
        return {"icono": icono, "efecto": icono, "insignia": f"AVISO {a['nivel'].upper()} · {nombre_fenomeno(a['fenomeno']).upper()}",
                "color": COLOR_NIVEL[a["nivel"]], "dato": dato,
                "ciudades": ciudades, "motivo": f"aviso {a['nivel']} por {nombre_fenomeno(a['fenomeno'])} en {', '.join(a['zonas'][:4])}",
                "nivel": a["nivel"]}
    def top(clave, filtro, rev=True):
        lista = [c for c in prev if filtro(c)]
        lista.sort(key=lambda c: ((c["nombre"] in CIUDADES_PUBLICO), c.get(clave) or 0), reverse=rev)
        return lista
    candidatos = [
        ("tormenta", top("lluvia", lambda c: c["icono"] == "tormenta"),
         lambda c: ("ALERTA POR TORMENTAS", f"TORMENTAS EN {c['nombre'].upper()}")),
        ("nieve", top("lluvia", lambda c: c["icono"] == "nieve"),
         lambda c: ("ATENCIÓN: NIEVE", f"NIEVE EN {c['nombre'].upper()}")),
        ("viento", top("racha", lambda c: (c.get("racha") or 0) >= 60),
         lambda c: ("RACHAS FUERTES", f"RACHAS DE {round(c['racha'])} KM/H EN {c['nombre'].upper()}")),
        ("lluvia", top("lluvia", lambda c: c["lluvia"] >= 70 or (c.get("lluvia_mm") or 0) >= 10),
         lambda c: ("OJO A LA LLUVIA", f"LLUVIA {c['lluvia']} % EN {c['nombre'].upper()}")),
        ("sol", top("tmax", lambda c: c["tmax"] >= 32),
         lambda c: ("CALOR FUERTE", f"{c['tmax']}° EN {c['nombre'].upper()}")),
        ("nieve", top("tmin", lambda c: c["tmin"] <= 1, rev=False),
         lambda c: ("HELADA", f"{c['tmin']}° EN {c['nombre'].upper()}")),
        ("viento", top("racha", lambda c: (c.get("racha") or 0) >= 45),
         lambda c: ("OJO AL VIENTO", f"RACHAS DE {round(c['racha'])} KM/H EN {c['nombre'].upper()}")),
        ("lluvia", top("lluvia", lambda c: c["lluvia"] >= 50),
         lambda c: ("HOY TOCA PARAGUAS", f"LLUVIA {c['lluvia']} % EN {c['nombre'].upper()}")),
        ("niebla", top("lluvia", lambda c: c["icono"] == "niebla"),
         lambda c: ("NIEBLA AL SALIR", f"NIEBLA EN {c['nombre'].upper()}")),
    ]
    for icono, lista, textos in candidatos:
        if lista:
            insignia, dato = textos(lista[0])
            nombres = _ordenar_publico([c["nombre"] for c in lista])
            return {"icono": icono, "efecto": icono, "insignia": insignia, "color": (255, 205, 40), "dato": dato,
                    "ciudades": nombres[:4], "motivo": f"{insignia.lower()}: {dato.lower()}", "nivel": None}
    calor = max(prev, key=lambda c: c["tmax"])
    return {"icono": "sol", "efecto": "sol", "insignia": "HOY TOCA CHANCLAS", "color": (255, 205, 40),
            "dato": f"{calor['tmax']}° EN {calor['nombre'].upper()}", "ciudades": [calor["nombre"]],
            "motivo": "día tranquilo y soleado", "nivel": None}


AMARILLOS = []   # avisos amarillos del día (para mencionarlos con prudencia, nunca como titular)


def para_guion(f: dict) -> str:
    """Texto para el prompt del guion."""
    extra = ""
    if AMARILLOS:
        zonas = "; ".join(f"{a['fenomeno']} en {', '.join(a['zonas'][:3])}" for a in AMARILLOS[:3])
        extra = (f" Avisos AMARILLOS de AEMET (NO son titular ni gancho): {zonas}. Si los mencionas, en su bloque, de pasada "
                 "y atribuidos ('AEMET mantiene aviso amarillo por...'), con la franja horaria, y sin prometer que "
                 "lloverá en toda la provincia.")
    return extra + (f"Fenómeno que abre el vídeo: {f['motivo']}. Ciudades afectadas (las primeras son las que más nos ven): "
            f"{', '.join(f['ciudades']) or 'ninguna concreta'}. "
            + ("Hay AVISO oficial de AEMET: puedes decir 'aviso " + f["nivel"] + "'." if f.get("nivel") else
               "NO hay avisos oficiales: no digas 'aviso' ni 'alerta oficial'; crea urgencia con el dato real "
               "(variando la fórmula: 'prepárate', 'atención', 'mañana sí', una pregunta…; nunca 'Ojo').")
            )
