"""Canjea el código de autorización de Google y guarda el refresh_token de YouTube cifrado.

Lo ejecuta el workflow "Autorizar YouTube" con la URL completa que muestra callback.html.
"""
from __future__ import annotations

import os
import sys
import urllib.parse

from .youtube import canjear_codigo

if __name__ == "__main__":
    entrada = (os.environ.get("CODIGO_YOUTUBE") or (sys.argv[1] if len(sys.argv) > 1 else "")).strip()
    if not entrada:
        sys.exit("Pasa la URL de callback.html o el código")
    if entrada.startswith("http"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(entrada).query)
        if "error" in q:
            sys.exit(f"Google devolvió un error: {q['error'][0]}")
        entrada = q["code"][0]
    cid, sec = os.environ.get("YT_CLIENT_ID", "").strip(), os.environ.get("YT_CLIENT_SECRET", "").strip()
    # GitHub oculta los secretos: solo se muestran datos para comprobar que están bien copiados
    print(f"::notice::YT_CLIENT_ID termina en {cid[-30:]!r} (longitud {len(cid)}); "
          f"YT_CLIENT_SECRET empieza por {sec[:7]!r} (longitud {len(sec)})")
    try:
        res = canjear_codigo(urllib.parse.unquote(entrada))
    except Exception as e:  # noqa: BLE001
        print(f"::error::{e}")
        sys.exit(1)
    print(f"✅ YouTube autorizado. Permisos: {res['scope']}")
