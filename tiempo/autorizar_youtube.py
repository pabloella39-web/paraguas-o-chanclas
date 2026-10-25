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
    res = canjear_codigo(urllib.parse.unquote(entrada))
    print(f"✅ YouTube autorizado. Permisos: {res['scope']}")
