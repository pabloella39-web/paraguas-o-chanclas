"""Municipios de España con más de 100.000 habitantes (padrón INE) y su ubicación aproximada, para saber qué
avisos de AEMET afectan a una gran población (punto dentro del polígono oficial de la zona de aviso)."""
from __future__ import annotations

GRANDES = [
    ("Madrid", 40.4168, -3.7038), ("Barcelona", 41.3874, 2.1686), ("Valencia", 39.4699, -0.3763),
    ("Sevilla", 37.3891, -5.9845), ("Zaragoza", 41.6488, -0.8891), ("Málaga", 36.7213, -4.4214),
    ("Murcia", 37.9922, -1.1307), ("Palma", 39.5696, 2.6502), ("Las Palmas de Gran Canaria", 28.1235, -15.4363),
    ("Bilbao", 43.2630, -2.9350), ("Alicante", 38.3452, -0.4810), ("Córdoba", 37.8882, -4.7794),
    ("Valladolid", 41.6523, -4.7245), ("Vigo", 42.2406, -8.7207), ("Gijón", 43.5322, -5.6611),
    ("L'Hospitalet de Llobregat", 41.3596, 2.0997), ("Vitoria-Gasteiz", 42.8467, -2.6716),
    ("A Coruña", 43.3623, -8.4115), ("Elche", 38.2669, -0.6984), ("Granada", 37.1773, -3.5986),
    ("Terrassa", 41.5610, 2.0089), ("Badalona", 41.4500, 2.2474), ("Sabadell", 41.5463, 2.1086),
    ("Oviedo", 43.3614, -5.8593), ("Cartagena", 37.6257, -0.9966), ("Móstoles", 40.3223, -3.8649),
    ("Jerez de la Frontera", 36.6850, -6.1261), ("Santa Cruz de Tenerife", 28.4636, -16.2518),
    ("Pamplona", 42.8125, -1.6458), ("Almería", 36.8340, -2.4637), ("Alcalá de Henares", 40.4818, -3.3643),
    ("Fuenlabrada", 40.2842, -3.7942), ("Leganés", 40.3272, -3.7635), ("San Sebastián", 43.3183, -1.9812),
    ("Getafe", 40.3057, -3.7329), ("Burgos", 42.3439, -3.6969), ("Albacete", 38.9943, -1.8585),
    ("Santander", 43.4623, -3.8099), ("Castellón de la Plana", 39.9864, -0.0513), ("Alcorcón", 40.3458, -3.8249),
    ("San Cristóbal de La Laguna", 28.4874, -16.3159), ("Logroño", 42.4627, -2.4450), ("Badajoz", 38.8794, -6.9707),
    ("Marbella", 36.5101, -4.8825), ("Salamanca", 40.9701, -5.6635), ("Huelva", 37.2614, -6.9447),
    ("Lleida", 41.6176, 0.6200), ("Tarragona", 41.1189, 1.2445), ("Dos Hermanas", 37.2865, -5.9209),
    ("Torrejón de Ardoz", 40.4582, -3.4800), ("Parla", 40.2377, -3.7676), ("Mataró", 41.5381, 2.4445),
    ("León", 42.5987, -5.5671), ("Algeciras", 36.1408, -5.4562), ("Cádiz", 36.5271, -6.2886),
    ("Santa Coloma de Gramenet", 41.4515, 2.2081), ("Alcobendas", 40.5475, -3.6420), ("Jaén", 37.7796, -3.7849),
    ("Ourense", 42.3358, -7.8639), ("Reus", 41.1561, 1.1069), ("Telde", 27.9924, -15.4194),
    ("Barakaldo", 43.2964, -2.9884), ("Lugo", 43.0097, -7.5568), ("Girona", 41.9794, 2.8214),
    ("Santiago de Compostela", 42.8782, -8.5448), ("Cáceres", 39.4753, -6.3724), ("Las Rozas", 40.4929, -3.8737),
    ("Lorca", 37.6772, -1.7008), ("Roquetas de Mar", 36.7642, -2.6146), ("Torrevieja", 37.9787, -0.6822),
]


def dentro(lon: float, lat: float, poligono: list[tuple[float, float]]) -> bool:
    """Punto en polígono (rayos). poligono = [(lon, lat), ...]."""
    n, res, j = len(poligono), False, len(poligono) - 1
    for i in range(n):
        xi, yi = poligono[i]
        xj, yj = poligono[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            res = not res
        j = i
    return res


def afectadas(poligonos: list, zona_txt: str = "") -> list[str]:
    """Grandes poblaciones dentro de alguno de los polígonos (o nombradas en la zona si no hay polígono)."""
    out = []
    for nombre, lat, lon in GRANDES:
        if any(len(p) >= 3 and dentro(lon, lat, p) for p in poligonos):
            out.append(nombre)
        elif not any(len(p) >= 3 for p in poligonos) and nombre.lower() in zona_txt.lower():
            out.append(nombre)
    return out
