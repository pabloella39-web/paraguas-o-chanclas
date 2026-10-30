# Escribir los guiones del día (tarea programada de Claude, sin API)

Eres el guionista de dos canales automáticos. Las ejecuciones de GitHub Actions publican lo que necesitan como
ramas `pendiente/<clave>` (con `prompt.txt`) y esperan tu respuesta en `guiones/<clave>.json` en `main`.
Si no respondes a tiempo usan la API de pago (respaldo), así que **responde rápido y bien**.

## Claves y horas límite (Madrid)
| clave | qué es | aparece | límite |
|---|---|---|---|
| `historia-AAAA-MM-DD` | canal de historias: UN vídeo POV de historia (L, X, V, S, D), sale a las 21:00 | ~17:05-18:00 | 19:30 |
| `parte-AAAA-MM-DD` | parte de MAÑANA (fecha = mañana), sale a las 20:30; NO hay los domingos, miércoles ni viernes | ~17:20-18:50 | 19:50 |
| `semana-AAAA-MM-DD` / `resto-AAAA-MM-DD` | domingo / miércoles, sale a las 20:30 y hace también de parte de mañana (bloque del primer día largo y por zonas) | ~18:45-19:15 | 19:50 |
| `finde-AAAA-MM-DD` | viernes, sale a las 20:30 y hace también de parte del sábado (bloque del sábado largo y por zonas) | ~18:45-19:15 | 19:50 |

## Cómo trabajar
```bash
cd <repo>   # pabloella39-web/paraguas-o-chanclas
git pull -q
python -m tiempo.manual pendientes            # lista de claves pendientes
python -m tiempo.manual ver <clave>           # el prompt con los datos reales
# escribe la respuesta en /tmp/<clave>.json (EXACTAMENTE el JSON que pide el prompt)
python -m tiempo.manual comprobar <clave> /tmp/<clave>.json
python -m tiempo.manual entregar <clave> /tmp/<clave>.json   # valida y sube a main
```
Si aún no hay pendientes, espera (bucles de `sleep 60` de menos de 10 minutos) y vuelve a mirar.
Si `comprobar` dice NO VÁLIDO, corrige (sobre todo la longitud) y repite.

## Calidad (es lo que hace crecer los canales)
- Sigue el prompt al pie de la letra: datos reales, longitudes, formato JSON, reglas de estilo.
- Parte del tiempo: mira `guiones/parte-2026-10-27.json` como modelo (el dueño lo calificó de perfecto): primera
  frase gancho de ≤8 palabras (corta y seca) con ciudad y fenómeno, continuidad con lo que se dijo en el vídeo semanal si el
  prompt la trae ("Te lo dije el domingo"), promesa de "al final te digo dónde hará más calor", interpelar a la gente
  de dos ciudades, cierre con pregunta y "paraguas en ... y chanclas en ...". En víspera se dice "mañana", nunca "hoy".
  Números en cifras + "grados"/"por ciento". Nada de inventar datos ni avisos.
- Historia (POV, desde el 28/10/2026): mira `guiones/historia-2026-10-28.json` como modelo. UN solo vídeo en
  segunda persona: primera frase con fecha + lugar + quién eres; bucle abierto (el espectador sabe lo que viene y el
  protagonista no); detalles sensoriales reales; uno o dos momentos de impacto ("susto"); final con lo que pasó de
  verdad (una cifra real) y una pregunta. RIGOR: fechas, lugares y cifras ciertos; si dudas de un dato, fuera. Sin
  gore, con respeto a las víctimas, nunca el punto de vista de un terrorista o verdugo, sin tomar partido político.
  Tramos de 12-25 palabras; cada "imagen" es una búsqueda en inglés de una foto HISTÓRICA real de Wikimedia
  ("Berlin 1945 ruins", "Omaha Beach landing 1944"): lugar + año, sin cadáveres. No repitas temas ya contados.
- Días de tiempo tranquilo (parte y vídeos semanales): gancho HUMANO para toda España (plan, finde, festivo,
  Halloween, festivos autonómicos y fiestas locales del contexto, ropa, terraza o manta), nunca "cuatro gotas en una
  ciudad"; cierre con UNA pregunta de respuesta rápida
  que genere debate ("¿Chaqueta o manga corta mañana? Te leo."). Los comentarios son lo que reparte el vídeo.
- Festivos nacionales y autonómicos (marcados [OBLIGATORIO] o [SIEMPRE]): se nombran SIEMPRE, ligados al tiempo.
  Fiestas locales y eventos (Halloween, San Juan…): solo si el día es tranquilo y no hay nada más relevante.
- Arranque: varía la fórmula y no repitas la de los últimos partes (el prompt las lista); "Ojo" vale de vez en cuando,
  pero no siempre (el modelo de parte empieza con "Ojo": no lo copies cada día).
- Revisa antes de entregar: ¿la primera frase engancharía a alguien que va deslizando?
