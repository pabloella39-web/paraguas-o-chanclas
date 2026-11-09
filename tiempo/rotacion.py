"""Rotación de ciudades en el mapa: cada ciudad de España debe salir de vez en cuando (que todo el mundo vea la suya).
Se guarda el último día que salió cada una; al rellenar el mapa tienen preferencia las que llevan más tiempo sin salir."""
from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import RAIZ

ARCHIVO = RAIZ / "estado" / "mapa_rotacion.json"
_cache: dict | None = None


def _datos() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _cache = {}
    return _cache


def _hoy() -> date:
    return datetime.now(ZoneInfo("Europe/Madrid")).date()


def dias_sin_salir(nombre: str) -> int:
    """Días desde la última vez que salió en el mapa (las que nunca han salido: 60)."""
    d = _datos().get(nombre)
    if not d:
        return 60
    try:
        return max(0, (_hoy() - date.fromisoformat(d)).days)
    except ValueError:
        return 60


def bonus(nombre: str, tope: int = 20) -> float:
    """0 si salió hoy o ayer; crece con los días sin salir (hasta «tope» días)."""
    return min(max(dias_sin_salir(nombre) - 1, 0), tope) / tope


def registrar(nombres) -> None:
    datos = _datos()
    hoy = _hoy().isoformat()
    cambio = False
    for n in nombres:
        if datos.get(n) != hoy:
            datos[n] = hoy
            cambio = True
    if cambio:
        try:
            ARCHIVO.parent.mkdir(exist_ok=True)
            ARCHIVO.write_text(json.dumps(datos, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
