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
    # Más ciudades y cabeceras de comarca: rotan en el mapa para que todo el mundo vea la suya de vez en cuando
    ("Ferrol", 43.484, -8.233, "norte"), ("Ponferrada", 42.546, -6.598, "norte"), ("Avilés", 43.556, -5.925, "norte"),
    ("Torrelavega", 43.349, -4.048, "norte"), ("Tudela", 42.065, -1.606, "norte"), ("Viveiro", 43.662, -7.594, "norte"),
    ("Monforte de Lemos", 42.521, -7.514, "norte"), ("Calahorra", 42.305, -1.965, "norte"),
    ("Miranda de Ebro", 42.686, -2.947, "norte"), ("Cangas de Onís", 43.351, -5.129, "norte"),
    ("Luarca", 43.543, -6.536, "norte"), ("Laredo", 43.411, -3.416, "norte"), ("Estella", 42.671, -2.030, "norte"),
    ("Talavera de la Reina", 39.963, -4.830, "interior"), ("Puertollano", 38.687, -4.108, "interior"),
    ("Tomelloso", 39.157, -3.022, "interior"), ("Aranda de Duero", 41.672, -3.689, "interior"),
    ("Medina del Campo", 41.311, -4.914, "interior"), ("Benavente", 42.003, -5.678, "interior"),
    ("Calatayud", 41.353, -1.643, "interior"), ("Alcañiz", 41.051, -0.133, "interior"),
    ("Barbastro", 42.036, 0.127, "interior"), ("Jaca", 42.570, -0.549, "interior"), ("Béjar", 40.386, -5.763, "interior"),
    ("Ciudad Rodrigo", 40.600, -6.533, "interior"), ("Astorga", 42.459, -6.056, "interior"),
    ("Hellín", 38.510, -1.700, "interior"), ("Villarrobledo", 39.270, -2.601, "interior"),
    ("Valdepeñas", 38.762, -3.385, "interior"), ("Alcázar de San Juan", 39.390, -3.208, "interior"),
    ("Sigüenza", 41.068, -2.643, "interior"), ("Molina de Aragón", 40.844, -1.886, "interior"),
    ("Aranjuez", 40.032, -3.604, "interior"), ("Ejea de los Caballeros", 42.126, -1.137, "interior"),
    ("Reus", 41.155, 1.107, "mediterraneo"), ("Tortosa", 40.812, 0.521, "mediterraneo"),
    ("Manresa", 41.728, 1.824, "mediterraneo"), ("Vic", 41.930, 2.254, "mediterraneo"),
    ("Figueres", 42.267, 2.961, "mediterraneo"), ("La Seu d'Urgell", 42.358, 1.456, "mediterraneo"),
    ("Gandia", 38.967, -0.181, "mediterraneo"), ("Alcoy", 38.698, -0.474, "mediterraneo"),
    ("Dénia", 38.840, 0.106, "mediterraneo"), ("Orihuela", 38.085, -0.944, "mediterraneo"),
    ("Lorca", 37.677, -1.701, "mediterraneo"), ("Requena", 39.488, -1.101, "mediterraneo"),
    ("Vinaròs", 40.470, 0.475, "mediterraneo"), ("Xàtiva", 38.990, -0.518, "mediterraneo"),
    ("Torrevieja", 37.978, -0.683, "mediterraneo"), ("Caravaca de la Cruz", 38.106, -1.861, "mediterraneo"),
    ("Yecla", 38.614, -1.115, "mediterraneo"),
    ("Mérida", 38.916, -6.344, "sur"), ("Plasencia", 40.030, -6.088, "sur"), ("Don Benito", 38.956, -5.861, "sur"),
    ("Zafra", 38.425, -6.417, "sur"), ("Navalmoral de la Mata", 39.892, -5.540, "sur"), ("Coria", 39.985, -6.536, "sur"),
    ("Linares", 38.095, -3.636, "sur"), ("Úbeda", 38.013, -3.370, "sur"), ("Andújar", 38.039, -4.051, "sur"),
    ("Lucena", 37.409, -4.485, "sur"), ("Écija", 37.542, -5.083, "sur"), ("Antequera", 37.019, -4.560, "sur"),
    ("Ronda", 36.742, -5.167, "sur"), ("Motril", 36.745, -3.518, "sur"), ("Baza", 37.490, -2.773, "sur"),
    ("Guadix", 37.300, -3.139, "sur"), ("El Ejido", 36.776, -2.815, "sur"), ("Osuna", 37.237, -5.103, "sur"),
    ("Utrera", 37.185, -5.781, "sur"), ("Sanlúcar de Barrameda", 36.778, -6.352, "sur"), ("Ayamonte", 37.213, -7.408, "sur"),
    ("Aracena", 37.893, -6.561, "sur"), ("Pozoblanco", 38.379, -4.849, "sur"), ("Llerena", 38.240, -6.016, "sur"),
    ("Manacor", 39.570, 3.209, "islas"), ("Pollença", 39.877, 3.016, "islas"), ("Ciutadella", 40.001, 3.840, "islas"),
    ("San Sebastián de La Gomera", 28.092, -17.111, "islas"), ("Valverde", 27.809, -17.915, "islas"),
    ("Puerto de la Cruz", 28.414, -16.548, "islas"), ("Maspalomas", 27.760, -15.586, "islas"),
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
    """La contraria a la del último vídeo publicado (parte, semanal o finde), para que se alternen siempre;
    sin registro, días pares masculina e impares femenina."""
    import json
    try:
        ultima = json.loads((RAIZ / "estado" / "ultima_voz.json").read_text(encoding="utf-8"))["voz"]
        return "femenina" if ultima == "masculina" else "masculina"
    except Exception:  # noqa: BLE001
        return "masculina" if fecha.toordinal() % 2 == 0 else "femenina"


def voz_para(tipo: str, fecha, importante: bool = False) -> str:
    """Reparto fijo: voz FEMENINA en los partes de diario (de lunes a viernes), SIEMPRE, aunque haya aviso; MASCULINA
    en los vídeos importantes (semanal, finde, vídeos de aviso naranja o rojo) y en los partes del fin de semana."""
    if tipo != "parte" or importante or fecha.weekday() >= 5:
        return "masculina"
    return "femenina"


def registrar_voz(tipo: str, fecha=None):
    """Se llama al publicar: la siguiente publicación usará la otra voz."""
    import json
    (RAIZ / "estado").mkdir(exist_ok=True)
    (RAIZ / "estado" / "ultima_voz.json").write_text(json.dumps({"voz": tipo, "fecha": str(fecha or "")}),
                                                      encoding="utf-8")
VELOCIDAD_EDGE = "+15%"  # punto de partida; se ajusta solo para cuadrar la duración

MODELO_CLAUDE = "claude-sonnet-5-5"
