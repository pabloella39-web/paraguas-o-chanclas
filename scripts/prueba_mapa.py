"""Prueba del contraste de fuentes: AEMET frente a ECMWF, AROME, ICON y GFS, para mañana."""
import logging
from datetime import date, timedelta
from tiempo import contraste, fuentes
logging.basicConfig(level=logging.INFO)
for dia in (date.today() + timedelta(days=1), date.today() + timedelta(days=3)):
    prev, _ = fuentes.obtener_previsiones(dia)
    print("====", dia)
    for c in prev[:6]:
        print(c["nombre"], c["contraste"])
    print(contraste.texto(prev, str(dia)))
