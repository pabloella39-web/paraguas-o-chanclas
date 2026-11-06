"""Prueba: pueblos más fríos y calurosos frente a las capitales, y extremos observados por AEMET."""
import logging
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO)
from tiempo import pueblos
from tiempo.fuentes import obtener_previsiones

for k in (1, 2):
    d = date.today() + timedelta(days=k)
    prev, _ = obtener_previsiones(d)
    print(d, "capitales:", min((c["tmin"], c["nombre"]) for c in prev), max((c["tmax"], c["nombre"]) for c in prev))
    print(d, "pueblos:", pueblos.previstos(d))
    nota, ext = pueblos.texto(prev, d, date.today(), "mañana")
    print(nota)
    print({k: (v["nombre"], v.get("tmin"), v.get("tmax")) for k, v in ext.items()})
pueblos.registrar()
print(pueblos.observados(date.today()))
