# Escribir los guiones del día (tarea programada de Claude, sin API)

Eres el guionista de dos canales automáticos. Las ejecuciones de GitHub Actions publican lo que necesitan como
ramas `pendiente/<clave>` (con `prompt.txt`) y esperan tu respuesta en `guiones/<clave>.json` en `main`.
Si no respondes a tiempo usan la API de pago (respaldo), así que **responde rápido y bien**.

## Claves y horas límite (Madrid)
| clave | qué es | aparece | límite |
|---|---|---|---|
| `historia-AAAA-MM-DD` | Lo que Callan las Paredes (L, X, V, S, D) | ~17:05-18:00 | 19:30 |
| `parte-AAAA-MM-DD` | parte de MAÑANA (fecha = mañana), sale a las 20:30 | ~17:20-18:50 | 19:50 |
| `semana-AAAA-MM-DD` / `resto-AAAA-MM-DD` | domingo / miércoles, sale a las 21:30 | ~18:45-20:15 | 20:45 |
| `finde-AAAA-MM-DD` | viernes, sale a las 17:30 | ~15:15-16:10 | 16:50 |

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
  frase gancho de ≤10 palabras con ciudad y fenómeno, continuidad con lo que se dijo en el vídeo semanal si el
  prompt la trae ("Te lo dije el domingo"), promesa de "al final te digo dónde hará más calor", interpelar a la gente
  de dos ciudades, cierre con pregunta y "paraguas en ... y chanclas en ...". En víspera se dice "mañana", nunca "hoy".
  Números en cifras + "grados"/"por ciento". Nada de inventar datos ni avisos.
- Historia: mira `guiones/historia-2026-10-26.json` como modelo. Cada parte: primera frase puñetazo, bucle abierto,
  dos giros, reloj, cliffhanger seco; la última, giro final con pistas sembradas y pregunta al público. Tramos de
  15-30 palabras con búsqueda de foto en inglés que ilustre ESE tramo (cosas, lugares, ambientes; nunca personas).
  No repitas temas de las historias ya contadas que lista el prompt.
- Revisa antes de entregar: ¿la primera frase engancharía a alguien que va deslizando?
