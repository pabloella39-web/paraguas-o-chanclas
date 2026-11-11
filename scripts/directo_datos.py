"""Datos en vivo para la página del directo (docs/directo): avisos naranjas y rojos vigentes de AEMET, con sus zonas,
y lo medido hoy en las estaciones (lluvia acumulada y racha máxima). Escribe directo_datos/datos.json."""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tiempo.especiales import descargar_avisos  # noqa: E402
from tiempo.fuentes import _aemet_get  # noqa: E402

TZ = ZoneInfo("Europe/Madrid")
clave = os.environ["AEMET_API_KEY"].strip()
ahora = datetime.now(timezone.utc)
salida = Path("directo_datos"); salida.mkdir(exist_ok=True)
previo = {}
try:
    previo = json.loads((salida / "datos.json").read_text(encoding="utf-8"))
except Exception:  # noqa: BLE001
    pass
datos = {"actualizado": ahora.isoformat(timespec="seconds"), "avisos": previo.get("avisos", []),
         "avisos_hora": previo.get("avisos_hora"), "lluvia": previo.get("lluvia", []), "viento": previo.get("viento", []),
         "obs_hasta": previo.get("obs_hasta")}


def _iso(t):
    return datetime.fromisoformat(t)


try:
    grupos = {}
    for a in descargar_avisos(clave):
        if a["nivel"] not in ("naranja", "rojo"):
            continue
        try:
            ini, fin = _iso(a["inicio"]), _iso(a["fin"])
        except Exception:  # noqa: BLE001
            continue
        if not (ini - timedelta(minutes=30) <= ahora < fin):
            continue
        g = grupos.setdefault((a["nivel"], a["fenomeno"].lower()), {"nivel": a["nivel"], "fenomeno": a["fenomeno"].lower(),
                                                                     "zonas": [], "fin": a["fin"], "poligonos": []})
        zona = a["zona"].replace("Costa - ", "")
        if zona not in g["zonas"]:
            g["zonas"].append(zona)
            pol = a.get("poligono") or []
            paso = max(1, len(pol) // 60)                      # contorno simplificado
            if len(pol) >= 3:
                g["poligonos"].append([[round(la, 3), round(lo, 3)] for lo, la in pol[::paso]])
        if _iso(a["fin"]) > _iso(g["fin"]):
            g["fin"] = a["fin"]
    datos["avisos"] = sorted(grupos.values(), key=lambda g: (g["nivel"] != "rojo", g["fenomeno"]))
    datos["avisos_hora"] = ahora.isoformat(timespec="seconds")
    print("avisos:", [(g["nivel"], g["fenomeno"], len(g["zonas"])) for g in datos["avisos"]])
except Exception as e:  # noqa: BLE001
    print("avisos: fallo,", e)

try:
    obs = json.loads(_aemet_get("/observacion/convencional/todas", clave))
    hoy = ahora.astimezone(TZ).date()
    lluvia, viento, hasta = {}, {}, None
    for o in obs:
        try:
            t = _iso(o["fint"].replace("+0000", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        if t.astimezone(TZ).date() != hoy:
            continue
        hasta = t if hasta is None or t > hasta else hasta
        k = o["idema"]
        nombre = (o.get("ubi") or k).strip()
        if isinstance(o.get("prec"), (int, float)) and 0 <= o["prec"] < 200:
            lluvia[k] = (nombre, lluvia.get(k, (nombre, 0))[1] + o["prec"])
        if isinstance(o.get("vmax"), (int, float)) and 0 <= o["vmax"] < 80:
            viento[k] = (nombre, max(viento.get(k, (nombre, 0))[1], o["vmax"]))
    datos["lluvia"] = [[n, round(v)] for n, v in sorted(lluvia.values(), key=lambda t: -t[1])[:6] if v >= 1]
    datos["viento"] = [[n, round(v * 3.6)] for n, v in sorted(viento.values(), key=lambda t: -t[1])[:6] if v > 0]
    datos["obs_hasta"] = hasta.isoformat(timespec="seconds") if hasta else None
    print("estaciones:", len(lluvia), datos["lluvia"][:3], datos["viento"][:3], datos["obs_hasta"])
except Exception as e:  # noqa: BLE001
    print("observaciones: fallo,", e)

(salida / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
