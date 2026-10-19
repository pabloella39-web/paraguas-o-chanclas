# Paraguas o Chanclas (@paraguasochanclas) — el tiempo en España en TikTok

Cada mañana, GitHub Actions:

1. Descarga la previsión del día de **AEMET OpenData** y de **Open-Meteo** (mediana de 4 modelos: ECMWF, ICON, Météo-France y GFS) para 22 ciudades y las fusiona con media ponderada (AEMET 50 %, Open-Meteo 30 %; si añades `GOOGLE_WEATHER_API_KEY`, Google entra con un 20 %). El estado del cielo oficial de AEMET manda.
2. Escribe un guion con **humor ligero** (Claude; si falla, una plantilla propia).
3. Genera la **voz IA en español** (Microsoft Edge TTS, voz `es-ES-AlvaroNeural`; respaldo: Google Text-to-Speech).
4. Monta un vídeo vertical 1080×1920 con el **mapa de España**, iconos, tarjetas por región, subtítulos y música de fondo original.
5. Garantiza una duración **entre 65 y 70 segundos** (ajusta el guion, el ritmo de la voz y las pausas; si no lo consigue, no publica).
6. **Espera a las 7:30 (hora de Madrid)** y lo publica en TikTok con la Content Posting API.

`salida/` contiene el MP4, `datos.json` y `meta.json` (guion y texto del post).

---

## 1. Claves que necesitas (secretos de GitHub)

| Secreto | Dónde se consigue | Coste |
|---|---|---|
| `AEMET_API_KEY` | https://opendata.aemet.es/centrodedescargas/altaUsuario (llega por email) | Gratis |
| `GOOGLE_WEATHER_API_KEY` (opcional) | Google Cloud Console (exige facturación) → activa **Weather API** → Clave de API | ~660 llamadas/mes, dentro del tramo gratuito |
| — | Open-Meteo no necesita clave | Gratis (uso no comercial) |
| `ANTHROPIC_API_KEY` | https://console.anthropic.com (opcional; sin ella se usa la plantilla) | Céntimos al mes |
| `TIKTOK_CLIENT_KEY` / `TIKTOK_CLIENT_SECRET` | Tu app en https://developers.tiktok.com | Gratis |
| `TIKTOK_REFRESH_TOKEN` | Con `scripts/obtener_token_tiktok.py` (paso 3) | — |
| `GH_PAT` (recomendado) | GitHub → Settings → Developer settings → Fine-grained token con permiso **Secrets: Read and write** sobre este repo. Sirve para guardar el refresh token cuando TikTok lo rota | — |

Si quieres voz de Google en lugar de Edge, añade `GOOGLE_TTS_API_KEY` y activa *Cloud Text-to-Speech API*.

## 2. Subir el proyecto a GitHub

1. Crea un repositorio (público = minutos de Actions ilimitados; privado = ~1.200 de los 2.000 min gratis al mes).
2. Sube todo el contenido de esta carpeta.
3. **Settings → Pages**: rama `main`, carpeta `/docs`. Tendrás:
   - `https://TU_USUARIO.github.io/TU_REPO/` (web de la app)
   - `.../privacidad.html` y `.../terminos.html` (TikTok los pide)
   - `.../callback.html` (redirect URI para autorizar)
4. **Settings → Secrets and variables → Actions**: añade los secretos de la tabla.

## 3. App de TikTok

1. Crea la cuenta de TikTok del canal.
2. En developers.tiktok.com crea una app (tipo *Web*) con esas URLs de web, privacidad y términos.
3. Añade los productos **Login Kit** y **Content Posting API**; activa **Direct Post**.
4. Scopes: `user.info.basic`, `video.publish`, `video.upload`.
5. Redirect URI: `https://TU_USUARIO.github.io/TU_REPO/callback.html`.
6. En tu ordenador: `pip install requests && python scripts/obtener_token_tiktok.py` → abre el enlace con la cuenta del canal, acepta, pega la URL de vuelta y guarda el `refresh_token` como secreto.

**Importante — auditoría de TikTok:** mientras la app no esté auditada, TikTok solo deja publicar en **privado** y la cuenta debe estar en **modo privado** al publicar. Para pruebas: pon la cuenta en privado. Después solicita la auditoría desde el portal de desarrolladores. Mientras tanto tienes dos opciones (variables en *Settings → Variables → Actions*):

- `TIKTOK_MODO = borrador` → el vídeo llega a tu bandeja de TikTok y tú pulsas publicar.
- `TIKTOK_PRIVACIDAD = SELF_ONLY` → se publica en privado (se cambia a público desde la app).

Tras la auditoría, deja `TIKTOK_MODO = directo` (por defecto) y se publicará en público solo.

## 4. Probar

- **Actions → Parte diario del tiempo → Run workflow**, sin marcar "Publicar": genera el vídeo y lo deja como artefacto descargable.
- Marca "Publicar" para probar la subida a TikTok al momento.
- En local: `pip install -r requirements.txt` (y ffmpeg) y `python -m tiempo.main` (con las claves como variables de entorno). `python -m tiempo.main --demo` hace un vídeo con datos inventados y sin voz.

## 5. Horario

GitHub programa en UTC, así que hay dos crons (04:45 y 05:45 UTC) y `tiempo/horario.py` deja pasar solo el que equivale a las **06:45 de Madrid** según sea horario de verano o de invierno. El vídeo se genera en unos 3–5 min y el proceso **espera hasta las 7:30 exactas** para publicar. Si GitHub retrasa el arranque más de 45 min (raro), publica en cuanto termina.

Cada día se guarda `historial/AAAA-MM-DD.json` con el guion: eso además evita que GitHub desactive el cron por inactividad (60 días). Si algo falla, GitHub te avisa por email y el vídeo queda como artefacto.

## 6. Personalizar

- Ciudades, regiones y voz: `tiempo/config.py`.
- Tono y chistes: el prompt en `tiempo/guion.py` (y las frases de la plantilla).
- Música propia: deja un `assets/musica.mp3` libre de derechos y se usará en vez de la generada.
- Colores y diseño: `tiempo/mapa.py` y `tiempo/video.py`.

## Atribuciones y normas

- AEMET permite reutilizar sus datos citando la fuente: el vídeo muestra siempre "Fuente: AEMET".
- Open-Meteo (CC BY 4.0): el vídeo muestra "Weather data by Open-Meteo.com". Su API gratuita es para uso no comercial: si el canal empieza a ganar dinero, contrata su plan comercial.
- Si usas Google, exige el texto exacto, sin traducir ni partir: "Source: Includes weather data from Google" (visible en todo el vídeo). Revisa los términos de Google Maps Platform si cambias el uso.
- El post se marca como contenido generado con IA (`is_aigc`), como pide TikTok.
- Mapa: provincias de España (click_that_hood, basado en datos públicos). Tipografía Inter (licencia OFL, en `assets/fonts`).
- Edge TTS es un servicio no oficial de Microsoft: si deja de funcionar, el sistema pasa automáticamente a Google TTS (necesita la API activada).
