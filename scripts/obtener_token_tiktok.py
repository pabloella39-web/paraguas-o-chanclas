"""Autoriza tu cuenta de TikTok UNA vez y obtiene el refresh_token (válido 365 días).

Uso (en tu ordenador):
  pip install requests
  python scripts/obtener_token_tiktok.py

Te pedirá client_key, client_secret y la redirect URI que registraste en TikTok for Developers
(por ejemplo https://TU_USUARIO.github.io/TU_REPO/callback.html). Abre el enlace, acepta, y pega
aquí la URL completa a la que te redirige TikTok (o solo el código).
"""
import secrets
import sys
import urllib.parse

import requests

SCOPES = "user.info.basic,video.publish,video.upload"


def main():
    client_key = input("client_key: ").strip()
    client_secret = input("client_secret: ").strip()
    redirect = input("redirect_uri registrada: ").strip()
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": client_key, "response_type": "code", "scope": SCOPES,
        "redirect_uri": redirect, "state": state})
    print("\n1) Abre este enlace con la cuenta de TikTok del canal y acepta:\n\n" + url + "\n")
    pegado = input("2) Pega la URL a la que te ha redirigido (o el código): ").strip()
    if pegado.startswith("http"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(pegado).query)
        if q.get("state", [state])[0] != state:
            sys.exit("El parámetro state no coincide; vuelve a empezar.")
        code = q["code"][0]
    else:
        code = urllib.parse.unquote(pegado)
    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", data={
        "client_key": client_key, "client_secret": client_secret, "code": code,
        "grant_type": "authorization_code", "redirect_uri": redirect,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    j = r.json()
    if "refresh_token" not in j:
        sys.exit(f"Error: {j}")
    print("\n✅ Listo. Guarda esto como secreto TIKTOK_REFRESH_TOKEN en GitHub:\n")
    print(j["refresh_token"])
    print(f"\n(caduca en {int(j.get('refresh_expires_in', 0)) // 86400} días; scopes: {j.get('scope')})")


if __name__ == "__main__":
    main()
