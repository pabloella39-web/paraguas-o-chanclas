"""Avisos de AEMET vigentes en Canarias ahora mismo."""
import logging, os
from datetime import datetime
logging.basicConfig(level=logging.INFO)
from tiempo import especiales as e
todos = e.descargar_avisos(os.environ.get("AEMET_API_KEY", ""))
ahora = datetime.now().astimezone()
for a in todos:
    if a.get("poligono") and all(la < 30 for _, la in a["poligono"]) and a["nivel"] != "verde":
        print(a["nivel"], a["fenomeno"], a["zona"], a["inicio"], a["fin"])
print("relevantes:", [(a["zona"], a["nivel"]) for a in e.avisos_relevantes(todos, ahora)])
