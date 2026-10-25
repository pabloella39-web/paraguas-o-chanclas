"""Envía el último vídeo de prueba (rama pruebas-tiempo) a TikTok y pone su descripción en docs/hoy.json.

Uso: python -m tiempo.enviar_prueba <carpeta con meta.json y el .mp4>
Con UPLOADPOST_API_KEY se publica directamente; si no, va a la bandeja de borradores de TikTok.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from .config import RAIZ

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("enviar_prueba")


def main():
    carpeta = Path(sys.argv[1])
    meta = json.loads((carpeta / "meta.json").read_text(encoding="utf-8"))
    video = next(carpeta.glob("*.mp4"))
    caption = meta["caption"]

    hoy = RAIZ / "docs" / "hoy.json"
    try:
        previo = json.loads(hoy.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        previo = {}
    extras = previo.get("extras", []) if previo.get("fecha") == meta["fecha"] else []
    hoy.write_text(json.dumps({"fecha": meta["fecha"], "caption": caption, "voz": meta.get("voz"),
                               "duracion": meta["duracion"], "extras": extras}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    from . import uploadpost, tiktok
    if uploadpost.disponible() and os.environ.get("MODO_ENVIO") != "borrador":
        res = uploadpost.publicar_tiktok(video, caption, "tiempo")
    else:
        os.environ["TIKTOK_MODO"] = "borrador"
        res = tiktok.publicar(video, caption, meta.get("portada_ms", 0))  # sin reintentos: evita borradores repetidos
    log.info("Enviado a TikTok: %s", res)
    print(f"::notice::Vídeo {video.name} enviado a TikTok: {str(res)[:200]}")


if __name__ == "__main__":
    main()
