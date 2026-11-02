"""Lo que pasó de verdad tras un aviso naranja o rojo que publicamos (datos medidos por las estaciones de AEMET).

Se usa como UNA frase en el siguiente parte o vídeo semanal, solo cuando hubo aviso, y sin tono de "te lo dije".
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)
RAIZ = Path(__file__).resolve().parent.parent
HISTORIAL = RAIZ / "historial_especiales"
RADIO_KM = 30


def _km(la1, lo1, la2, lo2):
    x = math.radians(lo2 - lo1) * math.cos(math.radians((la1 + la2) / 2))
    return 6371 * math.hypot(x, math.radians(la2 - la1))


def _iso(s: str) -> datetime:
    s = s.replace("+0000", "+00:00")
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def avisos_terminados(ahora: datetime) -> list[dict]:
    """Avisos que publicamos y que terminaron en las últimas ~30 h (solo se comentan una vez)."""
    out = []
    for d in (ahora.date() - timedelta(days=1), ahora.date()):
        for f in sorted(HISTORIAL.glob(f"aviso-{d.isoformat()}-*.json")):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for a in meta.get("avisos") or []:
                try:
                    fin = _iso(a["fin"])
                except Exception:  # noqa: BLE001
                    continue
                if fin <= ahora and ahora - fin <= timedelta(hours=30):
                    out.append(a)
    return out


def observaciones(clave: str) -> list[dict]:
    from .fuentes import _aemet_get
    return json.loads(_aemet_get("/observacion/convencional/todas", clave))


def medir(aviso: dict, obs: list[dict]) -> dict | None:
    """Máximo medido en las estaciones cercanas a las ciudades afectadas durante el aviso."""
    from .poblaciones import GRANDES
    sitios = [(n, la, lo) for n, la, lo in GRANDES if n in (aviso.get("ciudades") or [])]
    if not sitios:
        return None
    ini, fin = _iso(aviso["inicio"]) - timedelta(hours=2), _iso(aviso["fin"]) + timedelta(hours=5)
    fen = aviso["fenomeno"].lower()
    por_estacion = {}
    for o in obs:
        try:
            t = _iso(o["fint"])
            la, lo = float(o["lat"]), float(o["lon"])
        except Exception:  # noqa: BLE001
            continue
        if not ini <= t <= fin:
            continue
        cerca = [n for n, cla, clo in sitios if _km(la, lo, cla, clo) <= RADIO_KM]
        if not cerca:
            continue
        e = por_estacion.setdefault(o["idema"], {"estacion": o.get("ubi", o["idema"]), "ciudad": cerca[0],
                                                 "lluvia": 0.0, "racha": 0.0, "horas": 0})
        e["horas"] += 1
        if isinstance(o.get("prec"), (int, float)):
            e["lluvia"] += o["prec"]
        if isinstance(o.get("vmax"), (int, float)):
            e["racha"] = max(e["racha"], o["vmax"] * 3.6)
    if not por_estacion:
        return None
    if "viento" in fen:
        e = max(por_estacion.values(), key=lambda x: x["racha"])
        return {**e, "tipo": "viento", "valor": round(e["racha"]), "unidad": "km/h"}
    if "lluvia" in fen or "tormenta" in fen:
        e = max(por_estacion.values(), key=lambda x: x["lluvia"])
        return {**e, "tipo": "lluvia", "valor": round(e["lluvia"]), "unidad": "litros por metro cuadrado"}
    return None


def _estacion_legible(s: str) -> str:
    return " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in s.replace(",", " ").split())


def nota(ahora: datetime | None = None, obs: list[dict] | None = None) -> str:
    """Texto para el prompt (vacío si no hubo aviso o no hay datos)."""
    ahora = ahora or datetime.now(timezone.utc)
    avisos = avisos_terminados(ahora)
    if not avisos:
        return ""
    try:
        obs = obs if obs is not None else observaciones(os.environ.get("AEMET_API_KEY", ""))
    except Exception as e:  # noqa: BLE001
        log.warning("Sin observaciones de AEMET para el aviso de ayer: %s", e)
        return ""
    lineas = []
    for a in avisos:
        m = medir(a, obs)
        if not m or m["horas"] < 2:
            continue
        cuando = "anoche" if _iso(a["inicio"]).astimezone(ZoneInfo("Europe/Madrid")).hour >= 18 else "ayer"
        lineas.append(f"{cuando} hubo aviso {a['nivel']} por {a['fenomeno']} en {', '.join(a['ciudades'][:3])}; "
                      f"la estación de AEMET {_estacion_legible(m['estacion'])} midió {m['valor']} {m['unidad']}"
                      + (" (máximo en la zona)" if m["tipo"] == "lluvia" else " de racha máxima")
                      + (f". Lo previsto: {a['descripcion'][:160].rstrip('. ')}" if a.get("descripcion") else ""))
    if not lineas:
        return ""
    return ("[DATO REAL] " + " | ".join(lineas) + ". Dedícale UNA sola frase corta, como dato y con naturalidad "
            "(por ejemplo «Barcelona amaneció con 47 litros caídos en la noche» o «Lo de anoche en Barcelona fue "
            "serio: 47 litros por metro cuadrado»). Varía la forma. PROHIBIDO presumir o sonar a «te lo dije»: nada de "
            "«lo dijimos», «te lo avisamos», «como ya te dijimos», «lo avisamos ayer». Si se quedó muy por debajo de "
            "lo previsto, dilo con naturalidad en media frase («al final fue menos de lo esperado») o no lo menciones.")


def resumen_aviso(gr: dict) -> dict:
    """Lo que se guarda en el historial del vídeo de aviso para poder comprobarlo después."""
    return {k: gr.get(k) for k in ("fenomeno", "nivel", "zonas", "ciudades", "inicio", "fin")} | \
        {"descripcion": (gr.get("descripcion") or "")[:300]}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    ahora = _iso(sys.argv[1]) if len(sys.argv) > 1 else None
    if ahora is None:
        print(nota() or "(nada)")
    else:
        obs = observaciones(os.environ.get("AEMET_API_KEY", ""))
        print(f"{len(obs)} observaciones; de {min(o['fint'] for o in obs)} a {max(o['fint'] for o in obs)}")
        print(nota(ahora, obs) or "(nada)")
