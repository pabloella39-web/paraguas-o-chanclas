"""Canjea el código de autorización de TikTok y guarda el refresh_token cifrado.

Lo ejecuta el workflow "Autorizar TikTok" con la URL completa de callback.html (o solo el código).
"""
from __future__ import annotations

import os
import sys
import urllib.parse

from .tiktok import canjear_codigo

REDIRECT_URI = "https://pabloella39-web.github.io/paraguas-o-chanclas/callback.html"
SCOPES = "user.info.basic,video.publish,video.upload"


def url_autorizacion(client_key: str, state: str = "paraguas") -> str:
    return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": client_key, "response_type": "code", "scope": SCOPES,
        "redirect_uri": REDIRECT_URI, "state": state})


def extraer_codigo(texto: str) -> str:
    texto = texto.strip()
    if texto.startswith("http"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(texto).query)
        if "error" in q:
            sys.exit(f"TikTok devolvió un error: {q.get('error_description', q['error'])[0]}")
        return q["code"][0]
    return urllib.parse.unquote(texto)


if __name__ == "__main__":
    entrada = os.environ.get("CODIGO_TIKTOK") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not entrada:
        sys.exit("Pasa la URL de callback.html o el código")
    ck = os.environ.get("TIKTOK_CLIENT_KEY", "")
    # GitHub oculta el valor completo de los secretos; se muestra solo el principio para comprobarlo
    print(f"Client key en GitHub empieza por: {ck.strip()[:6]!r} (longitud {len(ck.strip())}; "
          f"espacios extra: {ck != ck.strip()}). La sandbox empieza por 'sbawoa' y mide 18.")
    print(f"Client secret: longitud {len(os.environ.get('TIKTOK_CLIENT_SECRET', '').strip())}")
    res = canjear_codigo(extraer_codigo(entrada), REDIRECT_URI)
    print(f"✅ TikTok autorizado. Permisos: {res['scope']}. Validez: {res['dias_validez']} días.")
