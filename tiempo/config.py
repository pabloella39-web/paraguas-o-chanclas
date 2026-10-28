"""Configuración del canal: ciudades, regiones, vistas del mapa y parámetros del vídeo."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ASSETS = RAIZ / "assets"
FUENTES_TIPO = ASSETS / "fonts"

NOMBRE_CANAL = "PARAGUAS O CHANCLAS"
CUENTA_TIKTOK = "@paraguasochanclas"
ZONA_HORARIA = "Europe/Madrid"
HORA_PUBLICACION = (7, 30)

# Duración obligatoria del vídeo (segundos)
DURACION_MIN = 65.0
DURACION_MAX = 70.0
DURACION_OBJETIVO = 67.5

# Vídeo vertical TikTok
ANCHO, ALTO, FPS = 1080, 1920, 30

# Atribuciones obligatorias (el texto de Google NO se puede traducir ni partir en dos líneas)
ATRIBUCION_AEMET = "Fuente: AEMET"
ATRIBUCION_GOOGLE = "Source: Includes weather data from Google"
ATRIBUCION_OPENMETEO = "Weather data by Open-Meteo.com (CC BY 4.0)"

# Ciudades: código INE de municipio (AEMET), coordenadas (Google) y región
CIUDADES = [
    # Norte
    {"id": "15030", "nombre": "A Coruña", "lat": 43.362, "lon": -8.411, "region": "norte"},
    {"id": "33044", "nombre": "Oviedo", "lat": 43.361, "lon": -5.849, "region": "norte"},
    {"id": "39075", "nombre": "Santander", "lat": 43.462, "lon": -3.810, "region": "norte"},
    {"id": "48020", "nombre": "Bilbao", "lat": 43.263, "lon": -2.935, "region": "norte"},
    {"id": "31201", "nombre": "Pamplona", "lat": 42.812, "lon": -1.645, "region": "norte"},
    # Interior
    {"id": "28079", "nombre": "Madrid", "lat": 40.417, "lon": -3.704, "region": "interior"},
    {"id": "47186", "nombre": "Valladolid", "lat": 41.652, "lon": -4.724, "region": "interior"},
    {"id": "37274", "nombre": "Salamanca", "lat": 40.970, "lon": -5.663, "region": "interior"},
    {"id": "45168", "nombre": "Toledo", "lat": 39.863, "lon": -4.027, "region": "interior"},
    {"id": "50297", "nombre": "Zaragoza", "lat": 41.649, "lon": -0.889, "region": "interior"},
    # Mediterráneo
    {"id": "08019", "nombre": "Barcelona", "lat": 41.385, "lon": 2.173, "region": "mediterraneo"},
    {"id": "46250", "nombre": "Valencia", "lat": 39.470, "lon": -0.376, "region": "mediterraneo"},
    {"id": "03014", "nombre": "Alicante", "lat": 38.345, "lon": -0.481, "region": "mediterraneo"},
    {"id": "30030", "nombre": "Murcia", "lat": 37.992, "lon": -1.131, "region": "mediterraneo"},
    # Sur
    {"id": "41091", "nombre": "Sevilla", "lat": 37.389, "lon": -5.984, "region": "sur"},
    {"id": "29067", "nombre": "Málaga", "lat": 36.721, "lon": -4.421, "region": "sur"},
    {"id": "18087", "nombre": "Granada", "lat": 37.177, "lon": -3.599, "region": "sur"},
    {"id": "04013", "nombre": "Almería", "lat": 36.834, "lon": -2.464, "region": "sur"},
    {"id": "06015", "nombre": "Badajoz", "lat": 38.879, "lon": -6.970, "region": "sur"},
    {"id": "51001", "nombre": "Ceuta", "lat": 35.889, "lon": -5.321, "region": "sur"},
    {"id": "52001", "nombre": "Melilla", "lat": 35.292, "lon": -2.938, "region": "sur"},
    # Islas
    {"id": "07040", "nombre": "Palma", "lat": 39.570, "lon": 2.650, "region": "islas"},
    {"id": "35016", "nombre": "Las Palmas", "lat": 28.124, "lon": -15.430, "region": "islas"},
    {"id": "38038", "nombre": "S.C. Tenerife", "lat": 28.464, "lon": -16.251, "region": "islas"},
]

# Más ciudades por región (solo Open-Meteo, una única petición): el guion las nombra cuando tienen algo reseñable,
# para no repetir siempre las mismas capitales. No salen como marcadores en el mapa.
CIUDADES_EXTRA = [
    # Norte
    ("Vigo", 42.240, -8.721, "norte"), ("Ourense", 42.336, -7.864, "norte"), ("Pontevedra", 42.431, -8.644, "norte"),
    ("Lugo", 43.010, -7.556, "norte"), ("Santiago de Compostela", 42.878, -8.545, "norte"),
    ("Gijón", 43.532, -5.661, "norte"), ("San Sebastián", 43.318, -1.981, "norte"),
    ("Vitoria", 42.847, -2.672, "norte"), ("Logroño", 42.463, -2.445, "norte"),
    # Interior
    ("Burgos", 42.344, -3.697, "interior"), ("León", 42.599, -5.567, "interior"), ("Segovia", 40.948, -4.118, "interior"),
    ("Ávila", 40.656, -4.700, "interior"), ("Soria", 41.764, -2.468, "interior"), ("Cuenca", 40.070, -2.137, "interior"),
    ("Guadalajara", 40.633, -3.167, "interior"), ("Ciudad Real", 38.985, -3.927, "interior"),
    ("Albacete", 38.994, -1.858, "interior"), ("Teruel", 40.344, -1.106, "interior"), ("Huesca", 42.136, -0.409, "interior"),
    ("Zamora", 41.503, -5.745, "interior"), ("Palencia", 42.010, -4.528, "interior"),
    # Mediterráneo
    ("Girona", 41.979, 2.821, "mediterraneo"), ("Tarragona", 41.119, 1.245, "mediterraneo"),
    ("Lleida", 41.618, 0.620, "mediterraneo"), ("Castellón", 39.986, -0.051, "mediterraneo"),
    ("Elche", 38.267, -0.698, "mediterraneo"), ("Cartagena", 37.626, -0.996, "mediterraneo"),
    ("Benidorm", 38.541, -0.123, "mediterraneo"),
    # Sur
    ("Córdoba", 37.888, -4.779, "sur"), ("Jaén", 37.780, -3.785, "sur"), ("Huelva", 37.261, -6.945, "sur"),
    ("Cádiz", 36.527, -6.289, "sur"), ("Jerez de la Frontera", 36.685, -6.126, "sur"), ("Cáceres", 39.475, -6.372, "sur"),
    ("Marbella", 36.510, -4.883, "sur"), ("Algeciras", 36.141, -5.456, "sur"),
    # Islas
    ("Ibiza", 38.907, 1.432, "islas"), ("Mahón", 39.889, 4.262, "islas"), ("Arrecife", 28.963, -13.548, "islas"),
    ("Puerto del Rosario", 28.500, -13.862, "islas"), ("Santa Cruz de La Palma", 28.684, -17.765, "islas"),
]

REGIONES = {
    "norte": {
        "titulo": "NORTE",
        "provincias": ["A Coruña", "Lugo", "Ourense", "Pontevedra", "Asturias", "Cantabria",
                       "Bizkaia/Vizcaya", "Gipuzkoa/Guipúzcoa", "Araba/Álava", "Navarra", "La Rioja"],
        "vista": (-9.6, -0.4, 41.4, 44.2),
    },
    "interior": {
        "titulo": "INTERIOR",
        "provincias": ["León", "Palencia", "Burgos", "Soria", "Zamora", "Valladolid", "Segovia", "Ávila",
                       "Salamanca", "Madrid", "Guadalajara", "Cuenca", "Toledo", "Ciudad Real", "Albacete",
                       "Zaragoza", "Huesca", "Teruel"],
        "vista": (-7.3, 0.6, 38.9, 42.6),
    },
    "mediterraneo": {
        "titulo": "MEDITERRÁNEO",
        "provincias": ["Girona", "Barcelona", "Tarragona", "Lleida", "Castelló/Castellón",
                       "València/Valencia", "Alacant/Alicante", "Murcia"],
        "vista": (-2.9, 3.6, 37.2, 42.6),
    },
    "sur": {
        "titulo": "SUR",
        "provincias": ["Huelva", "Sevilla", "Cádiz", "Málaga", "Córdoba", "Jaén", "Granada", "Almería",
                       "Badajoz", "Cáceres", "Ceuta", "Melilla"],
        "vista": (-7.9, -1.4, 34.9, 39.7),
    },
    "islas": {
        "titulo": "BALEARES Y CANARIAS",
        "provincias": ["Illes Balears", "Las Palmas", "Santa Cruz De Tenerife"],
        "vista": None,  # vista general
    },
}

# Canarias se dibuja desplazada (recuadro) en la vista general
DESPLAZAMIENTO_CANARIAS = (6.0, 6.8)  # (+lon, +lat)
PROVINCIAS_CANARIAS = {"Las Palmas", "Santa Cruz De Tenerife"}
RECUADRO_CANARIAS = (-12.5, -7.1, 34.25, 36.35)
VISTA_GENERAL = (-12.8, 4.6, 34.0, 44.1)

# Orden de los bloques del vídeo
SEGMENTOS = ["intro", "general", "norte", "interior", "mediterraneo", "sur", "islas", "cierre"]

# Voz
VOZ_EDGE = "es-ES-AlvaroNeural"  # voz por defecto (se sustituye por la del día)
# Alternancia diaria: un día voz masculina y al siguiente femenina
VOCES = {
    "masculina": {"edge": "es-ES-AlvaroNeural", "google": "MALE", "presenta": "un presentador"},
    "femenina": {"edge": "es-ES-ElviraNeural", "google": "FEMALE", "presenta": "una presentadora"},
}


def voz_del_dia(fecha) -> str:
    """Días pares (contando desde el año 1) voz masculina, impares femenina."""
    return "masculina" if fecha.toordinal() % 2 == 0 else "femenina"
VELOCIDAD_EDGE = "+15%"  # punto de partida; se ajusta solo para cuadrar la duración

MODELO_CLAUDE = "claude-sonnet-5-5"
