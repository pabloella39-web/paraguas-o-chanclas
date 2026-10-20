"""Configuración del canal económico: activos, voces, horario y textos fijos."""
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOMBRE_CANAL = "TORO U OSO"
CUENTA_TIKTOK = "@torouoso"
LEMA = "¿TORO U OSO?"          # pregunta del canal (toro = crees que sube, oso = crees que baja)
ZONA_HORARIA = "Europe/Madrid"
# Dos ediciones cada día laborable (sábado y domingo, solo la de la mañana)
HORA_PUBLICACION = {"manana": (8, 0), "noche": (21, 30)}
VENTANAS = {"manana": ((6, 40), (9, 30)), "noche": ((19, 55), (22, 45))}  # hora de Madrid
ESTADO_TIKTOK = "tiktok_token_economia.enc"
HISTORIAL = RAIZ / "historial_economia"

AVISO = "Información, no asesoramiento financiero"
MODELO_CLAUDE = "claude-sonnet-5-5"

# (clave, nombre en pantalla, grupo, símbolo Yahoo, símbolo CNBC, icono/bandera, unidad, decimales)
ACTIVOS = [
    ("ibex", "IBEX 35", "bolsa", "^IBEX", ".IBEX", "es", "puntos", 0),
    ("stoxx", "Euro Stoxx 50", "bolsa", "^STOXX50E", ".STOXX50E", "eu", "puntos", 0),
    ("dax", "DAX", "bolsa", "^GDAXI", ".GDAXI", "de", "puntos", 0),
    ("sp500", "S&P 500", "bolsa", "^GSPC", ".SPX", "us", "puntos", 0),
    ("nasdaq", "Nasdaq", "bolsa", "^IXIC", ".IXIC", "us", "puntos", 0),
    ("dow", "Dow Jones", "bolsa", "^DJI", ".DJI", "us", "puntos", 0),
    ("nikkei", "Nikkei", "bolsa", "^N225", ".N225", "jp", "puntos", 0),
    ("oro", "Oro", "materia", "GC=F", "@GC.1", "oro", "$/onza", 0),
    ("plata", "Plata", "materia", "SI=F", "@SI.1", "plata", "$/onza", 2),
    ("brent", "Brent", "materia", "BZ=F", "@LCO.1", "petroleo", "$/barril", 2),
    ("wti", "WTI", "materia", "CL=F", "@CL.1", "petroleo", "$/barril", 2),
    ("gas", "Gas TTF", "materia", "TTF=F", None, "gas", "€/MWh", 2),
    ("eurusd", "Euro/dólar", "divisa", "EURUSD=X", "EUR=", "eurusd", "$", 4),
    ("btc", "Bitcoin", "cripto", "BTC-USD", None, "btc", "$", 0),
    ("eth", "Ethereum", "cripto", "ETH-USD", None, "eth", "$", 0),
]

# Reuniones de política monetaria (respaldo por si falla el calendario económico).
# FED: federalreserve.gov (2027 provisional). BCE: ecb.europa.eu.
FOMC = [date(2026, 10, 28), date(2026, 12, 9), date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28),
        date(2027, 6, 9), date(2027, 7, 28), date(2027, 9, 15), date(2027, 10, 27), date(2027, 12, 8)]
BCE = [date(2026, 10, 29), date(2026, 12, 17), date(2027, 2, 4), date(2027, 3, 18), date(2027, 4, 29),
       date(2027, 6, 10), date(2027, 7, 22), date(2027, 9, 9), date(2027, 10, 28), date(2027, 12, 16)]

FUENTES_RSS = [
    ("Expansión", "https://e00-expansion.uecdn.es/rss/mercados.xml"),
    ("Expansión", "https://e00-expansion.uecdn.es/rss/portada.xml"),
    ("Cinco Días", "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/portada"),
    ("El País", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada"),
    ("Europa Press", "https://www.europapress.es/rss/rss.aspx?ch=00136"),
    ("Investing.com", "https://es.investing.com/rss/news.rss"),
    ("BCE", "https://www.ecb.europa.eu/rss/press.html"),
    ("Reserva Federal", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("Consejo de la UE", "https://www.consilium.europa.eu/es/rss/pressreleases.ashx"),
]

VOCES = {
    "masculina": {"edge": "es-ES-AlvaroNeural", "google": "MALE", "presenta": "un presentador"},
    "femenina": {"edge": "es-ES-ElviraNeural", "google": "FEMALE", "presenta": "una presentadora"},
}


def voz_del_dia(d: date) -> str:
    # Al revés que el canal del tiempo, para que cada mañana suenen las dos voces
    return "femenina" if d.toordinal() % 2 == 0 else "masculina"


def tipo_de_dia(d: date) -> str:
    """diario (lun-vie) · semanal (sábado: repaso de la semana) · previa (domingo: lo que viene)."""
    return {5: "semanal", 6: "previa"}.get(d.weekday(), "diario")


# Bloques del vídeo en orden
SEGMENTOS = ["intro", "bolsas", "cripto", "materias", "agenda", "noticias", "cierre"]
