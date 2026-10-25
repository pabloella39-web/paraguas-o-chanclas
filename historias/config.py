"""Canal "Lo que Callan las Paredes": una historia de terror, crimen o misterio al día, en 2 o 3 partes."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ASSETS = RAIZ / "assets" / "historias"
HISTORIAL = RAIZ / "historial_historias"
NOMBRE = "LO QUE CALLAN LAS PAREDES"
CUENTA = "@loquecallanlasparedes"
PERFIL_UPLOADPOST = os.environ.get("UPLOADPOST_PERFIL_HISTORIAS", "").strip() or "torouoso"

ANCHO, ALTO, FPS = 1080, 1920, 30
DURACION_MIN_PARTE = 65.0          # cada parte dura al menos 1:05 (petición expresa)
VOZ_OBJETIVO = (66.0, 78.0)        # segundos de locución por parte (más la tarjeta final)
PALABRAS_PARTE = 170               # ≈2,3 palabras/s con estas voces → ~72 s; se corrige con el ritmo real medido

# Hora (Madrid) a la que sale la PARTE 1. Las demás se publican antes, de la última a la primera, para que en el
# perfil queden ordenadas de arriba abajo (Parte 1, Parte 2, Parte 3) y quien llegue por la 2 encuentre la 1.
HORA_PARTE_1 = (21, 0)
SEPARACION_MIN = 12

# Voz del narrador (ElevenLabs). Se fija con la variable HISTORIAS_VOZ tras escuchar las muestras.
VOZ_DEFECTO = "y4o1CguECnmbT8YSuREN"  # Rafa (provisional hasta que se elija)


def voz() -> str:
    return os.environ.get("HISTORIAS_VOZ", "").strip() or VOZ_DEFECTO


def tipo_del_dia(d: date) -> str:
    """Mezcla: sobre todo ficción original, leyendas españolas dos días por semana y un caso real a la semana."""
    return ("ficcion", "leyenda", "ficcion", "real", "ficcion", "leyenda", "ficcion")[d.toordinal() % 7]


ETIQUETA_TIPO = {"ficcion": "RELATO DE FICCIÓN", "leyenda": "LEYENDA", "real": "CASO REAL"}
