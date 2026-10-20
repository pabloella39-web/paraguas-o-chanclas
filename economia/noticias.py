"""Titulares económicos recientes (RSS de medios y organismos). Claude los resume con sus palabras."""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from .config import FUENTES_RSS

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def _limpiar(txt: str | None, n: int = 240) -> str:
    txt = html.unescape(re.sub(r"<[^>]+>", " ", txt or ""))
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:n].rsplit(" ", 1)[0] + "…" if len(txt) > n else txt


def _fecha(item) -> datetime | None:
    for etiqueta in ("pubDate", "{http://purl.org/dc/elements/1.1/}date", "{http://www.w3.org/2005/Atom}updated"):
        el = item.find(etiqueta)
        if el is not None and el.text:
            try:
                d = parsedate_to_datetime(el.text.strip())
            except (TypeError, ValueError):
                try:
                    d = datetime.fromisoformat(el.text.strip().replace("Z", "+00:00"))
                except ValueError:
                    continue
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


def _clave(titulo: str) -> str:
    return " ".join(sorted(set(re.findall(r"\w{5,}", titulo.lower())))[:6])


def obtener_titulares(horas: int = 20, maximo: int = 45) -> list[dict]:
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    out, vistos = [], set()
    for fuente, url in FUENTES_RSS:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            raiz = ET.fromstring(r.content)
        except Exception as e:  # noqa: BLE001
            log.warning("RSS %s no disponible: %s", fuente, e)
            continue
        n = 0
        for item in raiz.iter("item"):
            titulo = _limpiar(item.findtext("title"), 160)
            d = _fecha(item)
            if not titulo or (d and d < limite):
                continue
            k = _clave(titulo)
            if k in vistos:
                continue
            vistos.add(k)
            out.append({"fuente": fuente, "titulo": titulo, "resumen": _limpiar(item.findtext("description")),
                        "hora": d.isoformat() if d else None})
            n += 1
            if n >= 10:
                break
    log.info("Titulares: %d de %d fuentes", len(out), len(FUENTES_RSS))
    return out[:maximo]
