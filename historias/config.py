"""Canal "Lo que Callan las Paredes": una historia de terror, crimen o misterio al día, en 2 o 3 partes."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ASSETS = RAIZ / "assets" / "historias"
HISTORIAL = RAIZ / "historial_historias"
# Formato: POV de historia (desde el 28/10/2026). Nombre y cuenta se cambian aquí cuando estén decididos.
NOMBRE = os.environ.get("HISTORIAS_NOMBRE", "").strip() or "TÚ ESTUVISTE ALLÍ"
CUENTA = os.environ.get("HISTORIAS_CUENTA", "").strip() or "@loquecallan.lasparedes"
PERFIL_UPLOADPOST = os.environ.get("UPLOADPOST_PERFIL_HISTORIAS", "").strip() or "torouoso"

ANCHO, ALTO, FPS = 1080, 1920, 30
DURACION_MIN_PARTE = 62.0          # un único vídeo POV de ~65-75 s
VOZ_OBJETIVO = (60.0, 70.0)        # segundos de locución (más la tarjeta final)
PALABRAS_PARTE = 155               # ≈2,4 palabras/s → ~65 s; se corrige con el ritmo real medido

# Hora (Madrid) a la que sale la PARTE 1. Las demás se publican antes, de la última a la primera, para que en el
# perfil queden ordenadas de arriba abajo (Parte 1, Parte 2, Parte 3) y quien llegue por la 2 encuentre la 1.
HORA_PARTE_1 = (21, 0)
SEPARACION_MIN = 12

# Voz del narrador (ElevenLabs). Se fija con la variable HISTORIAS_VOZ tras escuchar las muestras.
# Voz según quién narra la historia (primera persona): hombre → Rafa; mujer → Maite o Maia (se alternan)
VOZ_HOMBRE = "y4o1CguECnmbT8YSuREN"     # Rafa - Hoarse, Gripping & Nuanced
VOCES_MUJER = ["BXtvkfRgOYGPQKVRgufE",  # Maite Jiménez
               "jipeLrCHZ6ByxrU2JP9i"]  # Maia
VOZ_DEFECTO = VOZ_HOMBRE


def voz(narrador: str = "hombre", d: date | None = None) -> str:
    if narrador == "mujer":
        return VOCES_MUJER[(d.toordinal() // 2 if d else 0) % len(VOCES_MUJER)]
    return os.environ.get("HISTORIAS_VOZ", "").strip() or VOZ_HOMBRE


def tipo_del_dia(d: date) -> str:
    """Rotación de épocas y temas (sobre todo historia general; de vez en cuando historia de España y de pueblos)."""
    return ("guerra_mundial", "espana", "asia", "siglo_xx", "guerra_mundial", "antigua", "pueblos",
            "espana", "asia", "guerra_mundial", "siglo_xx", "antigua")[d.toordinal() % 12]


ETIQUETA_TIPO = {"guerra_mundial": "SEGUNDA GUERRA MUNDIAL", "espana": "HISTORIA DE ESPAÑA", "asia": "HISTORIA DE ASIA",
                 "siglo_xx": "SIGLO XX", "antigua": "HISTORIA ANTIGUA", "pueblos": "HISTORIA DE LOS PUEBLOS",
                 # tipos antiguos (historias ya publicadas)
                 "ficcion": "RELATO DE FICCIÓN", "leyenda": "LEYENDA", "real": "CASO REAL"}
